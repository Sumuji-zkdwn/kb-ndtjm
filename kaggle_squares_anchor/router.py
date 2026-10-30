"""Bounded explicit-request dispatcher for preverified private CPU notebooks.

Research code stays in Kaggle, and is transiently pulled into the Actions job.
This is not an interceptor for local applications. No competition submissions.
"""
import contextlib
import hashlib
import io
import json
import os
import re
import sys
import tempfile
import time
from pathlib import Path
from urllib.parse import urlsplit

from owned_probe import canonical

ID_RE = re.compile(r"^[a-z0-9][a-z0-9-]{5,39}$")
V1 = "KAGGLE-DISPATCH-REQUEST-v1:"
V2 = "KAGGLE-DISPATCH-LEDGER-v2:"
MAX_LEDGER = 128
TARGETS = {
    "ideas-43-rerun": {"ref": "sumuji/dalcia-ideas-43-kaggle", "id": 141796740,
                       "title": "dalcia_ideas_43_kaggle", "hash": "b75ee0f50e03854dca11e51f5b6b4bc4f011b1fff41f67d085ca1cf26f0f00f6", "gpu": False, "models": []},
    "search-curve-rerun": {"ref": "sumuji/search-curve-bridge-kaggle", "id": 141794119,
                           "title": "search_curve_bridge_kaggle", "hash": "bab19d71ff050cba201a09240529bf09624a3cfaec9aee8b4fbbaffbff2f352b", "gpu": False, "models": []},
    "arc3-memory-rerun": {"ref": "sumuji/arc3-memory-regression-kaggle", "id": 141796811,
                          "title": "arc3_memory_regression_kaggle", "hash": "10f3c5139969a56a7a688092e60c38b72be53c3c23d91b805978a41ed855990e", "gpu": False, "models": []},
    "tbp-forest-rerun": {"ref": "sumuji/research-models-tbp-forest-kaggle", "id": 141798383,
                         "title": "research_models_tbp_forest_kaggle", "hash": "f69df62dc526be37a650db8f395dcdd60eeeb400d6f0dff7f702b462c5720ee5", "gpu": False, "models": []},
    "qwen25-rerun": {"ref": "sumuji/qwen25-7b-kaggle-smoke", "id": 141794310,
                     "title": "qwen25_7b_kaggle_smoke", "hash": "0b23c42fb4f289b6a2aa9f24a18a1a678570bbf19e132265d4dabd2d74999c46", "gpu": True,
                     "models": ["qwen-lm/qwen2.5/Transformers/7b-instruct/1"], "machine_shape": "NvidiaTeslaT4"},
}
FIELDS = ("invalid_tags", "invalid_dataset_sources", "invalid_competition_sources",
          "invalid_kernel_sources", "invalid_model_sources")


class RouterError(Exception):
    pass


def check_request(req):
    if not isinstance(req, dict) or set(req) != {"id", "kind", "previous_id"}:
        raise RouterError("invalid request fields")
    if req["kind"] not in TARGETS:
        raise RouterError("unregistered request kind")
    if not isinstance(req["id"], str) or not ID_RE.fullmatch(req["id"]):
        raise RouterError("invalid request id")
    prev = req["previous_id"]
    if not isinstance(prev, str) or (prev != "none" and not ID_RE.fullmatch(prev)):
        raise RouterError("invalid previous id")
    if req["id"] == prev:
        raise RouterError("request and previous id must differ")
    return TARGETS[req["kind"]]


def check_metadata(meta, target):
    if (meta.get("id") != target["ref"] or meta.get("id_no") != target["id"]
        or meta.get("is_private") is not True or meta.get("title") != target["title"]):
        raise RouterError("notebook identity or privacy mismatch")
    if meta.get("language") != "python" or meta.get("kernel_type") != "notebook":
        raise RouterError("unexpected notebook type")
    if meta.get("enable_gpu") is not target["gpu"] or meta.get("enable_tpu") not in (False, None):
        raise RouterError("unexpected accelerator")
    for field in ("dataset_sources", "kernel_sources", "competition_sources"):
        if meta.get(field) != []:
            raise RouterError("unexpected source input")
    if meta.get("model_sources") != target["models"]:
        raise RouterError("unexpected model input")
    if target["gpu"] and meta.get("machine_shape") != target["machine_shape"]:
        raise RouterError("unexpected GPU machine shape")
    if type(meta.get("enable_internet")) is not bool:
        raise RouterError("internet setting missing")
    if not isinstance(meta.get("keywords"), list):
        raise RouterError("tag metadata unavailable")


def source(cell):
    s = cell.get("source")
    if isinstance(s, list) and all(isinstance(x, str) for x in s):
        s = "".join(s)
    if not isinstance(s, str):
        raise RouterError("invalid cell source")
    return s.replace("\r\n", "\n")


def prepare(nb, req, target):
    if not isinstance(nb, dict) or nb.get("nbformat") != 4 or not isinstance(nb.get("cells"), list):
        raise RouterError("invalid notebook")
    result = json.loads(json.dumps(nb))
    cells = result["cells"]
    markers = [(i, source(c)) for i, c in enumerate(cells)
               if source(c).startswith((V1, V2))]
    ledger = []
    if markers:
        if len(markers) != 1 or markers[0][0] != len(cells) - 1 or cells[-1].get("cell_type") != "markdown":
            raise RouterError("invalid dispatch marker position")
        text = markers[0][1]
        if text.startswith(V1):
            previous = text[len(V1):].strip()
            if not ID_RE.fullmatch(previous) or text != V1 + previous + "\n":
                raise RouterError("invalid legacy marker")
            ledger = [previous]
        else:
            encoded = text[len(V2):]
            try:
                ledger = json.loads(encoded)
            except ValueError:
                raise RouterError("invalid ledger")
            if (not isinstance(ledger, list) or not ledger or len(ledger) > MAX_LEDGER
                or any(not isinstance(x, str) or not ID_RE.fullmatch(x) for x in ledger)
                or len(ledger) != len(set(ledger))
                or encoded != json.dumps(ledger, separators=(",", ":")) + "\n"):
                raise RouterError("invalid ledger contents")
        cells.pop()
    digest, count = canonical(result)
    if digest != target["hash"]:
        raise RouterError("notebook source fingerprint mismatch")
    if req["id"] in ledger:
        return None, digest, ledger
    if req["previous_id"] != (ledger[-1] if ledger else "none"):
        raise RouterError("previous id does not match notebook ledger")
    if len(ledger) >= MAX_LEDGER:
        raise RouterError("ledger capacity reached")
    ledger.append(req["id"])
    for cell in cells:
        if cell.get("cell_type") == "code":
            cell["outputs"] = []
            cell["execution_count"] = None
    cells.append({"cell_type": "markdown", "metadata": {},
                  "id": hashlib.sha256(req["id"].encode()).hexdigest()[:12],
                  "source": V2 + json.dumps(ledger, separators=(",", ":")) + "\n"})
    return result, digest, ledger


def trusted_receipt_ref(value, expected):
    """Accept the exact ref or an exact, unadorned Kaggle URL for this ref."""
    if value in {expected, "/code/" + expected}:
        return True
    if not isinstance(value, str):
        return False
    try:
        parsed = urlsplit(value)
    except ValueError:
        return False
    return (parsed.scheme == "https" and parsed.netloc in {"kaggle.com", "www.kaggle.com"}
            and not parsed.query and not parsed.fragment
            and parsed.path in {"/" + expected, "/code/" + expected})


def receipt_identity_categories(response, target):
    """Return only fixed labels, never network data, for post-push diagnosis."""
    ref = getattr(response, "ref", None)
    ident = getattr(response, "kernel_id", None)
    if trusted_receipt_ref(ref, target["ref"]):
        ref_kind = "trusted_exact"
    elif ref in (None, ""):
        ref_kind = "missing"
    elif isinstance(ref, str):
        try:
            parsed = urlsplit(ref)
            host = parsed.netloc in {"www.kaggle.com", "kaggle.com"} and parsed.scheme == "https"
            path = parsed.path.rstrip("/") in {"/" + target["ref"], "/code/" + target["ref"]}
            if host and path and parsed.query:
                ref_kind = "kaggle_exact_path_with_query"
            elif host and path and parsed.fragment:
                ref_kind = "kaggle_exact_path_with_fragment"
            elif host and path:
                ref_kind = "kaggle_exact_path_with_trailing_slash"
            elif host:
                ref_kind = "other_kaggle_url"
            else:
                ref_kind = "other_nonempty"
        except ValueError:
            ref_kind = "invalid_url"
    else:
        ref_kind = "other_type"
    if type(ident) is int and ident == target["id"]:
        ident_kind = "exact"
    elif ident in (0, None):
        ident_kind = "zero_or_missing"
    else:
        ident_kind = "other"
    return {"ref_category": ref_kind, "kernel_id_category": ident_kind}


def check_receipt(response, target):
    if response is None or getattr(response, "error", None):
        raise RouterError("push failed or response ambiguous")
    for name in FIELDS:
        value = getattr(response, name, None)
        if not isinstance(value, list) or value:
            raise RouterError("push returned invalid or missing source diagnostics")
    if not trusted_receipt_ref(getattr(response, "ref", None), target["ref"]) or getattr(response, "kernel_id", None) != target["id"]:
        print(json.dumps({"receipt_identity_diagnostic": receipt_identity_categories(response, target)}))
        raise RouterError("push response identity mismatch")
    number = getattr(response, "version_number", None)
    if type(number) is not int or number <= 0:
        raise RouterError("push response version unavailable")
    return number


def quiet_call(method, *args, **kwargs):
    with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
        return method(*args, **kwargs)


def pull(api, target, ref=None):
    with tempfile.TemporaryDirectory(prefix="kaggle-private-read-") as tmp:
        quiet_call(api.kernels_pull, ref or target["ref"], tmp, metadata=True, quiet=True)
        p = Path(tmp)
        meta = json.loads((p / "kernel-metadata.json").read_text(encoding="utf-8"))
        check_metadata(meta, target)
        filename = meta.get("code_file")
        if not isinstance(filename, str) or Path(filename).name != filename:
            raise RouterError("unexpected filename")
        nb_path = p / filename
        if nb_path.stat().st_size > 2_000_000:
            raise RouterError("notebook too large")
        return meta, json.loads(nb_path.read_text(encoding="utf-8"))


def state(api, ref):
    result = quiet_call(api.kernels_status, ref)
    status = getattr(getattr(result, "status", None), "name", None)
    if status not in {"QUEUED", "RUNNING", "COMPLETE", "ERROR", "CANCEL_REQUESTED", "CANCEL_ACKNOWLEDGED", "NEW_SCRIPT"}:
        raise RouterError("unknown remote state")
    return status


def run(api, req, timeout_seconds=840, sleep=time.sleep):
    target = check_request(req)
    if os.environ.get("GITHUB_RUN_ATTEMPT") != "1":
        raise RouterError("automatic action retries disabled")
    if state(api, target["ref"]) != "COMPLETE":
        raise RouterError("current notebook not complete")
    meta, nb = pull(api, target)
    prepared, digest, history = prepare(nb, req, target)
    if prepared is None:
        print(json.dumps({"request": req["id"], "result": "already_present_no_push"}))
        return None
    meta2, nb2 = pull(api, target)
    p2, h2, history2 = prepare(nb2, req, target)
    relevant = ("id", "id_no", "title", "is_private", "enable_gpu", "enable_tpu", "enable_internet",
                "dataset_sources", "kernel_sources", "competition_sources", "model_sources", "machine_shape",
                "docker_image", "keywords")
    if (p2 is None or digest != h2 or history != history2 or
        any(meta.get(k) != meta2.get(k) for k in relevant) or state(api, target["ref"]) != "COMPLETE"):
        raise RouterError("notebook changed during preflight")
    payload = {"id": target["ref"], "id_no": target["id"], "title": target["title"],
               "code_file": "job.ipynb", "language": "python", "kernel_type": "notebook",
               "is_private": True, "enable_gpu": target["gpu"], "enable_internet": meta["enable_internet"],
               "dataset_sources": [], "competition_sources": [], "kernel_sources": [], "model_sources": target["models"]}
    payload["keywords"] = meta["keywords"]
    if target["gpu"]:
        payload["machine_shape"] = target["machine_shape"]
    if meta.get("docker_image"):
        payload["docker_image"] = meta["docker_image"]
    with tempfile.TemporaryDirectory(prefix="kaggle-private-send-") as tmp:
        p = Path(tmp)
        (p / "job.ipynb").write_text(json.dumps(prepared, ensure_ascii=False), encoding="utf-8")
        (p / "kernel-metadata.json").write_text(json.dumps(payload), encoding="utf-8")
        response = quiet_call(api.kernels_push, str(p))
    version = check_receipt(response, target)
    print(json.dumps({"request": req["id"], "kind": req["kind"], "accepted_version": version,
                      "source_hash": digest, "completion": "pending"}))
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        status = state(api, f"{target['ref']}/{version}")
        if status == "COMPLETE":
            _, done = pull(api, target, f"{target['ref']}/{version}")
            # A second prepare returns None only when exact requested id is present.
            completed, fingerprint, _ = prepare(done, req, target)
            if completed is not None or fingerprint != digest:
                raise RouterError("completed version identity mismatch")
            print(json.dumps({"request": req["id"], "version": version,
                              "version_specific_status": "COMPLETE", "source_marker_verified": True}))
            return version
        if status in {"ERROR", "CANCEL_REQUESTED", "CANCEL_ACKNOWLEDGED"}:
            raise RouterError("remote version failed or was cancelled")
        sleep(20)
    raise RouterError("remote state timed out; inspect before any retry")


def main():
    req = json.loads((Path(__file__).parent / "request.json").read_text(encoding="utf-8"))
    check_request(req)
    if not os.environ.get("KAGGLE_API_TOKEN"):
        raise RouterError("Kaggle credential unavailable")
    from kaggle.api.kaggle_api_extended import KaggleApi
    api = KaggleApi()
    quiet_call(api.authenticate)
    run(api, req)


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        # Do not leak traceback, credential, source, or remote exception text.
        label = str(exc) if isinstance(exc, RouterError) else "remote or local error; details suppressed"
        print("Dispatch stopped: " + label, file=sys.stderr)
        sys.exit(1)
