"""Bounded, fail-closed Kaggle notebook dispatch; never submits competitions."""
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
OWNER = "sumuji"
KNOWN_PRIVATE_CONTROL = "sumuji/quartic-energy-kaggle"
ALLOWED = {
    "synthetic-smoke": {"path": "notebooks/synthetic_smoke.ipynb", "gpu": False, "model_sources": []},
}
REQ_KEYS = {"id", "kind", "source_sha256"}
ID_RE = re.compile(r"^[a-z0-9][a-z0-9-]{5,29}$")
HASH_RE = re.compile(r"^[0-9a-f]{64}$")


class DispatchError(Exception):
    pass


def validate(request):
    if not isinstance(request, dict) or set(request) != REQ_KEYS:
        raise DispatchError("Request must contain exactly id, kind, source_sha256")
    job_id, kind, digest = request["id"], request["kind"], request["source_sha256"]
    if not isinstance(job_id, str) or not ID_RE.fullmatch(job_id):
        raise DispatchError("Invalid job id")
    if not isinstance(kind, str) or kind not in ALLOWED:
        raise DispatchError("Unregistered job kind")
    if not isinstance(digest, str) or not HASH_RE.fullmatch(digest):
        raise DispatchError("Invalid source digest")
    entry = ALLOWED[kind]
    path = (ROOT / entry["path"]).resolve()
    if not path.is_relative_to(ROOT / "notebooks") or not path.is_file():
        raise DispatchError("Registered source not found inside notebook directory")
    raw = path.read_bytes()
    if len(raw) > 1_000_000 or hashlib.sha256(raw).hexdigest() != digest:
        raise DispatchError("Notebook size or digest mismatch")
    nb = json.loads(raw)
    if nb.get("nbformat") != 4 or not isinstance(nb.get("cells"), list):
        raise DispatchError("Invalid notebook")
    return path, entry


def metadata(request, entry):
    slug = "dispatch-" + request["id"]
    return {"id": f"{OWNER}/{slug}", "title": slug, "code_file": "job.ipynb",
            "language": "python", "kernel_type": "notebook", "is_private": True,
            "enable_gpu": entry["gpu"], "enable_internet": False,
            "machine_shape": "NvidiaTeslaT4" if entry["gpu"] else "",
            "dataset_sources": [], "competition_sources": [], "kernel_sources": [],
            "model_sources": entry["model_sources"]}


def call(args, timeout=120):
    # Do not print subprocess stdout/stderr: it may contain sensitive information.
    p = subprocess.run([sys.executable, "-m", "kaggle", *args], capture_output=True,
                       text=True, timeout=timeout, check=False)
    return p.returncode, p.stdout, p.stderr


def classify(code, out, err):
    data = (out + "\n" + err).lower()
    if code != 0:
        # A 403, an auth/network error, or an unclear response is NOT proof of absence.
        return "absent" if re.search(r"\b404\b", data) else "unknown"
    for state in ("complete", "error", "cancelacknowledged", "cancelled", "running", "queued", "pending"):
        if re.search(r"\b" + state + r"\b", data):
            return state
    return "existing"


def diagnostic(code, out, err):
    """Return only controlled labels, never remote output or credentials."""
    data = (out + "\n" + err).lower()
    state = classify(code, out, err)
    if code == 0:
        category = "accessible_" + state
    elif "permission 'kernels.get' was denied" in data:
        # CLI 2.2.5 maps BOTH 401 and 403 to the same ValueError, including
        # nonexistent and inaccessible private notebooks. This is ambiguous.
        category = "permission_or_missing_ambiguous"
    elif re.search(r"\b401\b", data):
        category = "http_401"
    elif re.search(r"\b403\b", data):
        category = "http_403"
    elif re.search(r"\b404\b", data):
        category = "http_404"
    elif "authentication required" in data:
        category = "authentication_required"
    elif "timed out" in data or "timeout" in data:
        category = "timeout"
    else:
        category = "other_error"
    return {"return_code": code, "category": category}


def main():
    req = json.loads((ROOT / "request.json").read_text(encoding="utf-8"))
    path, entry = validate(req)
    if not os.environ.get("KAGGLE_API_TOKEN"):
        raise DispatchError("Kaggle credential is unavailable")
    meta = metadata(req, entry)
    ref = meta["id"]
    reference_code, reference_out, reference_err = call(["kernels", "status", KNOWN_PRIVATE_CONTROL])
    code, out, err = call(["kernels", "status", ref])
    before = classify(code, out, err)
    print(json.dumps({"job_id": req["id"], "kind": req["kind"], "kernel": ref,
                      "source_sha256": req["source_sha256"], "preflight": before,
                      "known_private_control": diagnostic(reference_code, reference_out, reference_err),
                      "target_diagnostic": diagnostic(code, out, err)}))
    if os.environ.get("KAGGLE_DIAGNOSTIC_ONLY") == "1":
        print("Diagnostic-only mode: no notebook upload attempted")
        return
    if reference_code != 0 or classify(reference_code, reference_out, reference_err) == "existing":
        raise DispatchError("Known private control inaccessible or unrecognised; no upload attempted")
    if before == "unknown":
        raise DispatchError("Cannot establish absence; no upload attempted")
    if before != "absent":
        raise DispatchError("Kernel already exists; no duplicate upload attempted")
    with tempfile.TemporaryDirectory(prefix="bounded-kaggle-") as td:
        folder = Path(td)
        (folder / "job.ipynb").write_bytes(path.read_bytes())
        (folder / "kernel-metadata.json").write_text(json.dumps(meta), encoding="utf-8")
        code, _, _ = call(["kernels", "push", "-p", str(folder)])
    if code:
        # Submission result could be ambiguous: do not retry automatically.
        raise DispatchError("Upload outcome uncertain; inspect this kernel before any retry")
    print(json.dumps({"kernel": ref, "push": "accepted", "privacy_requested": True}))
    deadline = time.monotonic() + 900
    while time.monotonic() < deadline:
        time.sleep(20)
        code, out, err = call(["kernels", "status", ref])
        state = classify(code, out, err)
        if state == "complete":
            print(json.dumps({"kernel": ref, "status": state, "version_note": "unique kernel slug; verify saved version and outputs in Kaggle"}))
            return
        if state in ("error", "cancelled", "cancelacknowledged", "unknown", "absent"):
            raise DispatchError("Remote run failed or status is ambiguous; inspect Kaggle")
    raise DispatchError("Polling timed out; remote job may still be active; do not retry blindly")


if __name__ == "__main__":
    try:
        main()
    except (DispatchError, OSError, subprocess.TimeoutExpired, json.JSONDecodeError) as exc:
        print(f"Dispatch stopped: {exc}", file=sys.stderr)
        sys.exit(1)
