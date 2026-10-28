"""Freeze, execute, observe and compare two independent ARC3 experiment lines.

No Kaggle import/authentication in prepare, verify, compare, or tests.
Network mutations are separate commands. Receipts always identify exact versions.
"""
from __future__ import annotations

import argparse
import ast
import copy
from datetime import datetime, timezone
from decimal import Decimal
import hashlib
import json
import os
from pathlib import Path
import re
import tempfile
import time

HERE = Path(__file__).resolve().parent
COMPETITION = "arc-prize-2026-arc-agi-3"
OFFICIAL_ZIP_SHA256 = "c72400a32db5e48da9014baf893b48016b300e9a6a77bd5d505de2b1ec61d645"


def now():
    return datetime.now(timezone.utc).isoformat()


def encoded(value):
    return (json.dumps(value, sort_keys=True, ensure_ascii=False, indent=2) + "\n").encode("utf-8")


def digest(value):
    return hashlib.sha256(value).hexdigest()


def read(path):
    return json.loads(Path(path).read_text(encoding="utf-8-sig"))


def save(path, value, exclusive=False):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    if exclusive:
        with path.open("xb") as stream:
            stream.write(encoded(value))
            stream.flush()
            os.fsync(stream.fileno())
    else:
        temporary = path.with_name(path.name + ".tmp")
        temporary.write_bytes(encoded(value))
        temporary.replace(path)


def code_sources(notebook):
    return ["".join(c["source"]) if isinstance(c["source"], list) else c["source"]
            for c in notebook["cells"] if c["cell_type"] == "code"]


def code_hash(notebook):
    return digest(encoded(code_sources(notebook)))


def clean_notebook(notebook):
    result = copy.deepcopy(notebook)
    result["nbformat_minor"] = max(5, result.get("nbformat_minor", 0))
    # Remove historical execution evidence and source-specific Kaggle settings.
    result["metadata"] = {k: v for k, v in result.get("metadata", {}).items()
                          if k in ("kernelspec", "language_info")}
    for index, cell in enumerate(result["cells"]):
        cell.setdefault("id", f"cell-{index}")
        cell["metadata"] = {}
        if cell["cell_type"] == "code":
            cell["execution_count"], cell["outputs"] = None, []
    return result


def validate_notebook(notebook):
    import nbformat
    from IPython.core.inputtransformer2 import TransformerManager
    nbformat.validate(nbformat.from_dict(notebook))
    transform = TransformerManager()
    for i, source in enumerate(code_sources(notebook)):
        compile(transform.transform_cell(source), f"cell_{i}", "exec",
                flags=ast.PyCF_ALLOW_TOP_LEVEL_AWAIT)


def profiles():
    return read(HERE / "profiles.json")


def environment(api, out):
    """Read the exact original V3 metadata; do not start a session."""
    reference = "dfranzen/arc-agi-3-milestone-2-solution/3"
    with tempfile.TemporaryDirectory() as temporary:
        api.kernels_pull(reference, temporary, metadata=True, quiet=True)
        metadata = read(Path(temporary) / "kernel-metadata.json")
    observed = {"reference": reference, "observed_utc": now(),
                **{k: metadata.get(k) for k in ("docker_image", "dataset_sources", "model_sources", "competition_sources")}}
    save(Path(out).with_suffix(".observed.json"), observed)
    if not metadata.get("docker_image"):
        raise ValueError("V3 did not return a docker_image; environment cannot be frozen")
    expected = profiles()["gpu-baseline"]
    expected["competition_sources"] = [COMPETITION]
    for key in ("dataset_sources", "model_sources", "competition_sources"):
        observed = metadata.get(key, [])
        # Dataset refs may include numeric versions, which must be retained.
        def normalize(value):
            parts = value.split("/")
            if key == "dataset_sources":
                return "/".join(parts[:2])
            if key == "model_sources" and len(parts) == 5:
                # The API returns the framework enum as Transformers whereas
                # saved notebook references use transformers. Other parts and
                # the exact model version must still match.
                parts[2] = parts[2].lower()
            return "/".join(parts)
        if sorted(map(normalize, observed)) != sorted(map(normalize, expected[key])):
            raise ValueError(f"Original V3 {key} differ from the saved source audit: observed={observed!r}, expected={expected[key]!r}")
    save(out, {"reference": reference, "observed_utc": now(),
               "docker_image": metadata["docker_image"],
               **{k: metadata.get(k, []) for k in ("dataset_sources", "model_sources", "competition_sources")}},
         exclusive=True)
    return read(out)


def prepare(profile, out, label, hypothesis, notebook=None, environment_path=None, owner="sumuji"):
    config = copy.deepcopy(profiles()[profile])
    if not re.fullmatch(r"[a-z0-9-]{1,36}", label):
        raise ValueError("label must contain 1-36 lowercase letters, digits or hyphens")
    if not re.fullmatch(r"[a-zA-Z0-9_-]+", owner):
        raise ValueError("Invalid Kaggle owner")
    source = Path(notebook) if notebook else HERE / config["notebook"]
    raw = source.read_bytes()
    nb = clean_notebook(json.loads(raw))
    validate_notebook(nb)
    runtime = {"is_private": True, "enable_gpu": config["line"] == "gpu",
               "enable_tpu": False, "enable_internet": False,
               "dataset_sources": config["dataset_sources"],
               "model_sources": config["model_sources"],
               "competition_sources": [COMPETITION], "kernel_sources": [],
               "machine_shape": config.get("machine_shape"),
               "docker_image_pinning_type": "original"}
    blockers = []
    if config["line"] == "gpu":
        if environment_path:
            env = read(environment_path)
            if env["reference"] != "dfranzen/arc-agi-3-milestone-2-solution/3" or not env.get("docker_image"):
                raise ValueError("GPU environment must be read back from original V3")
            for key in ("docker_image", "dataset_sources", "model_sources", "competition_sources"):
                runtime[key] = env[key]
            if runtime["competition_sources"] != [COMPETITION]:
                raise ValueError("Wrong competition in GPU environment")
        else:
            blockers.append("resolve original V3 environment with resolve-environment, then prepare a new bundle")
    identity = {"profile": profile, "line": config["line"], "label": label,
                "hypothesis": hypothesis, "notebook_sha256": digest(encoded(nb)),
                "code_sha256": code_hash(nb), "runtime": runtime,
                "session_timeout_seconds": config["session_timeout_seconds"]}
    candidate = digest(encoded(identity))
    # Keep URLs/titles compact while retaining the candidate hash in full.
    prefix = f"arc3-{profile}-{label}"[:37].rstrip("-")
    slug = f"{prefix}-{candidate[:12]}"
    metadata = {"id": f"{owner}/{slug}", "title": slug,
                "code_file": "submission.ipynb", "language": "python",
                "kernel_type": "notebook", **runtime}
    out = Path(out)
    out.mkdir(parents=True, exist_ok=False)
    save(out / "submission.ipynb", nb, exclusive=True)
    save(out / "kernel-metadata.json", metadata, exclusive=True)
    manifest = {"schema_version": 1, "candidate_id": candidate,
                "identity": identity, "kernel": metadata["id"], "competition": COMPETITION,
                "source_notebook_sha256": digest(raw), "code_sources_preserved": code_hash(nb) == code_hash(json.loads(raw)),
                "created_utc": now(), "launch_blockers": blockers,
                "comparison_scope": "same-line, exact runtime metadata; public score is not private performance",
                "files": {name: digest((out / name).read_bytes())
                          for name in ("submission.ipynb", "kernel-metadata.json")}}
    save(out / "manifest.json", manifest, exclusive=True)
    return manifest


def verify(bundle, launch=False):
    bundle = Path(bundle)
    manifest = read(bundle / "manifest.json")
    for name, expected in manifest["files"].items():
        if name not in ("submission.ipynb", "kernel-metadata.json") or digest((bundle / name).read_bytes()) != expected:
            raise ValueError("Frozen candidate bytes changed: " + name)
    if set(manifest["files"]) != {"submission.ipynb", "kernel-metadata.json"}:
        raise ValueError("Incomplete candidate inventory")
    if digest(encoded(manifest["identity"])) != manifest["candidate_id"]:
        raise ValueError("Candidate identity changed")
    nb, meta = read(bundle / "submission.ipynb"), read(bundle / "kernel-metadata.json")
    if digest(encoded(nb)) != manifest["identity"]["notebook_sha256"] or code_hash(nb) != manifest["identity"]["code_sha256"]:
        raise ValueError("Notebook identity mismatch")
    runtime = {k: meta.get(k) for k in manifest["identity"]["runtime"]}
    if runtime != manifest["identity"]["runtime"] or meta["id"] != manifest["kernel"]:
        raise ValueError("Runtime or kernel identity mismatch")
    if not meta["is_private"] or meta["enable_internet"] or meta["competition_sources"] != [COMPETITION]:
        raise ValueError("Unexpected publication, internet or competition settings")
    validate_notebook(nb)
    if launch and manifest["launch_blockers"]:
        raise ValueError("; ".join(manifest["launch_blockers"]))
    return manifest


def event(bundle, name, **values):
    manifest = verify(bundle)
    value = {"candidate_id": manifest["candidate_id"], "observed_utc": now(), **values}
    save(Path(bundle) / "evidence" / name, value)
    return value


def receipt(bundle, name):
    value = read(Path(bundle) / "evidence" / name)
    if value["candidate_id"] != verify(bundle)["candidate_id"]:
        raise ValueError("Receipt belongs to another candidate")
    return value


def attach_connection_check(bundle, report_path):
    manifest = verify(bundle)
    report = read(report_path)
    profile = manifest["identity"]["profile"]
    if not report.get("passed") or not report.get("checks") or not all(c.get("passed") for c in report["checks"]):
        raise ValueError("Official connection checks did not pass")
    if report.get("competition_zip_sha256") != OFFICIAL_ZIP_SHA256:
        raise ValueError("Official competition ZIP differs from the audited reference")
    if report.get("notebook_code_sha256", {}).get(profile) != manifest["identity"]["code_sha256"]:
        raise ValueError("Connection report tested different notebook code")
    if manifest["identity"]["line"] == "cpu" and report.get("cpu_profile_tested") != profile:
        raise ValueError("Connection report tested another CPU policy")
    return event(bundle, "connection-check.json", passed=True, profile=profile,
                 code_sha256=manifest["identity"]["code_sha256"], report_sha256=cycle_file_digest(report_path),
                 report=report, scope="Official public SDK and simulated gateway; not hidden-game or model-inference validation")


def require_connection_check(bundle):
    manifest = verify(bundle)
    value = receipt(bundle, "connection-check.json")
    if not value.get("passed") or value.get("code_sha256") != manifest["identity"]["code_sha256"]:
        raise ValueError("Candidate needs matching official connection checks")
    if value.get("report", {}).get("competition_zip_sha256") != OFFICIAL_ZIP_SHA256:
        raise ValueError("Connection check used another official bundle")
    return value


def import_cpu_smoke(bundle, measured_bundle):
    """Reuse a full official-ZIP run only for identical notebook/config bytes."""
    manifest = verify(bundle, launch=True)
    measured = verify(measured_bundle)
    source = receipt(measured_bundle, "public-smoke.json")
    if manifest["identity"]["line"] != "cpu" or measured["identity"]["line"] != "cpu":
        raise ValueError("Measured CPU evidence requires CPU candidates")
    for key in ("notebook_sha256", "code_sha256", "runtime", "session_timeout_seconds"):
        if manifest["identity"][key] != measured["identity"][key]:
            raise ValueError("Measured CPU evidence tested different notebook/config bytes")
    if not source.get("passed") or source.get("errors") or not source.get("results") or source.get("official_zip_sha256") != OFFICIAL_ZIP_SHA256:
        raise ValueError("A successful official-ZIP CPU measurement is required")
    rows = copy.deepcopy(source["results"])
    for row in rows:
        if row.get("candidate_id") != measured["candidate_id"] or not row.get("official_loop_unchanged"):
            raise ValueError("Measured CPU result identity/loop differs")
        row["measured_candidate_id"] = row["candidate_id"]
        row["candidate_id"] = manifest["candidate_id"]
    return event(bundle, "public-smoke.json", passed=True, errors=[], results=rows,
                 official_zip_sha256=source["official_zip_sha256"], environment_sha256=source.get("environment_sha256", {}),
                 measured_utc=source["observed_utc"], source_candidate_id=measured["candidate_id"],
                 scope="Reused completed official-ZIP local regression for identical notebook/config bytes; not a Kaggle score")


def reuse_cpu_baseline_evidence(bundle):
    """Reuse measured evidence only for byte-identical payload/runtime conditions."""
    manifest = verify(bundle, launch=True)
    source_manifest = read(HERE / "baseline-evidence" / "cpu-manifest.json")
    source = read(HERE / "baseline-evidence" / "cpu-public-smoke.json")
    if source["candidate_id"] != source_manifest["candidate_id"] or not source["passed"]:
        raise ValueError("Invalid measured baseline evidence")
    for key in ("notebook_sha256", "code_sha256", "runtime", "session_timeout_seconds"):
        if manifest["identity"][key] != source_manifest["identity"][key]:
            raise ValueError("Changed CPU payload/runtime requires a fresh public-smoke run")
    rows = copy.deepcopy(source["results"])
    for row in rows:
        if row["candidate_id"] != source_manifest["candidate_id"]:
            raise ValueError("Measured baseline contains another candidate")
        row["measured_candidate_id"] = row["candidate_id"]
        row["candidate_id"] = manifest["candidate_id"]
    return event(bundle, "public-smoke.json", passed=True, errors=[], results=rows,
                 environment_sha256=source["environment_sha256"], measured_utc=source["observed_utc"],
                 source_candidate_id=source["candidate_id"],
                 scope="Reused measured local results for identical notebook bytes and runtime metadata; no new game execution")


def intent(bundle, name, **values):
    manifest = verify(bundle, launch=True)
    save(Path(bundle) / "evidence" / name,
         {"candidate_id": manifest["candidate_id"], "created_utc": now(), **values}, exclusive=True)


def remote_check(api, bundle, version):
    manifest = verify(bundle, launch=True)
    expected = read(Path(bundle) / "kernel-metadata.json")
    with tempfile.TemporaryDirectory() as temporary:
        api.kernels_pull(f"{manifest['kernel']}/{int(version)}", temporary, metadata=True, quiet=True)
        meta = read(Path(temporary) / "kernel-metadata.json")
        source = read(Path(temporary) / meta["code_file"])
    if code_hash(source) != manifest["identity"]["code_sha256"]:
        raise ValueError("Kaggle readback source differs from the frozen candidate")
    for key in ("id", "is_private", "enable_gpu", "enable_internet", "dataset_sources", "model_sources", "competition_sources"):
        left, right = meta.get(key), expected.get(key)
        if isinstance(left, list) and isinstance(right, list):
            left, right = sorted(left), sorted(right)
        if left != right:
            raise ValueError("Kaggle readback settings differ: " + key)
    if expected.get("docker_image") and meta.get("docker_image") != expected["docker_image"]:
        raise ValueError("Kaggle changed the pinned environment image")
    if expected.get("machine_shape") and meta.get("machine_shape") != expected["machine_shape"]:
        raise ValueError("Kaggle changed the requested accelerator")
    return event(bundle, "readback.json", kernel=manifest["kernel"], version=int(version),
                 code_sha256=code_hash(source), settings_match=True, docker_image=meta.get("docker_image"))


def start(api, bundle):
    manifest = verify(bundle, launch=True)
    evidence = Path(bundle) / "evidence"
    if manifest["identity"]["line"] == "cpu":
        smoke = receipt(bundle, "public-smoke.json")
        if not smoke.get("passed") or smoke.get("errors") or not smoke.get("results"):
            raise ValueError("The exact CPU candidate needs a successful public-smoke report")
        if any(r.get("candidate_id") != manifest["candidate_id"] or not r.get("official_loop_unchanged")
               for r in smoke["results"]):
            raise ValueError("CPU smoke results do not match the candidate and official loop")
    if (evidence / "kernel-receipt.json").exists():
        return receipt(bundle, "kernel-receipt.json")
    connection = require_connection_check(bundle)
    if manifest["identity"]["line"] == "cpu" and smoke.get("official_zip_sha256") != OFFICIAL_ZIP_SHA256:
        raise ValueError("A fresh CPU smoke using the official ZIP is required before launch")
    if (evidence / "kernel-intent.json").exists():
        raise ValueError("Previous push may have succeeded. Adopt its exact version; do not push again")
    if (api.get_config_value("username") or "").lower() != manifest["kernel"].split("/", 1)[0].lower():
        raise ValueError("Authenticated account does not own this candidate")
    owned = []
    for page in range(1, 101):
        items = api.kernels_list(page=page, page_size=100, mine=True) or []
        owned.extend(item.ref.lower() for item in items if item is not None)
        if len(items) < 100:
            break
    else:
        raise ValueError("Owned notebook inventory exceeds the scan bound")
    if manifest["kernel"].lower() in owned:
        raise ValueError("Candidate notebook already exists remotely. Adopt its version instead of pushing")
    # A fresh runner with no local receipts must not overwrite an existing candidate.
    with tempfile.TemporaryDirectory() as temporary:
        try:
            api.kernels_pull(manifest["kernel"], temporary, metadata=True, quiet=True)
        except Exception as exc:
            status = getattr(getattr(exc, "response", None), "status_code", None)
            # Kaggle also returns 403 for a nonexistent notebook. Accept that
            # only after authenticated ownership and the complete successful
            # own-notebook inventory above establish this candidate is absent.
            if status not in (403, 404):
                raise
        else:
            raise ValueError("Candidate notebook already exists remotely. Adopt its version instead of pushing")
    intent(bundle, "kernel-intent.json", kernel=manifest["kernel"], maximum_push_calls=1)
    try:
        result = api.kernels_push(str(bundle), timeout=str(manifest["identity"]["session_timeout_seconds"]),
                                  acc=manifest["identity"]["runtime"].get("machine_shape"))
    except Exception as exc:
        response = getattr(exc, "response", None)
        message = str(getattr(response, "text", ""))[:2000]
        token = os.environ.get("KAGGLE_API_TOKEN")
        if token:
            message = message.replace(token, "[redacted]")
        event(bundle, "push-http-error.json", status_code=getattr(response, "status_code", None),
              error_type=type(exc).__name__, message=message,
              recovery="Inspect/adopt exact remote version before any further start; the intent remains")
        raise
    # Persist a receipt before checking optional validation details.
    version = int(result.version_number or 0)
    saved = event(bundle, "kernel-receipt.json", kernel=manifest["kernel"], version=version,
                  error=result.error, url=result.url)
    invalid = {k: getattr(result, k, None) for k in (
        "invalid_dataset_sources", "invalid_model_sources", "invalid_competition_sources", "invalid_kernel_sources")}
    if result.error or any(invalid.values()) or version < 1:
        event(bundle, "push-error.json", error=result.error, invalid_sources=invalid)
        raise ValueError("Kaggle did not accept the exact requested candidate; see push-error.json")
    remote_check(api, bundle, version)
    return saved


def adopt(api, bundle, version):
    if int(version) < 1:
        raise ValueError("version must be positive")
    path = Path(bundle) / "evidence" / "kernel-receipt.json"
    if path.exists() and receipt(bundle, "kernel-receipt.json")["version"] != int(version):
        raise ValueError("Cannot replace an existing version receipt")
    checked = remote_check(api, bundle, version)
    return event(bundle, "kernel-receipt.json", kernel=checked["kernel"], version=int(version),
                 adopted_after_readback=True, error="")


def enum_name(value):
    return getattr(value, "name", str(value)).upper()


def observe_kernel(api, bundle):
    stored = receipt(bundle, "kernel-receipt.json")
    if stored.get("error") or stored["version"] < 1:
        raise ValueError("No accepted version to observe")
    status = api.kernels_status(f"{stored['kernel']}/{stored['version']}")
    return event(bundle, "kernel-status.json", kernel=stored["kernel"], version=stored["version"],
                 status=enum_name(status.status), failure_message=status.failure_message)


def marker(bundle):
    manifest = verify(bundle)
    return "ARC3-CYCLE-" + manifest["candidate_id"]


def submissions_with_marker(api, bundle):
    # Do not silently assume the first page is the complete history.
    matches = []
    for page in range(1, 101):
        items = api.competition_submissions(COMPETITION, page_number=page, page_size=100) or []
        matches.extend(s for s in items if s is not None and (s.description or "").split(" ", 1)[0] == marker(bundle))
        if len(items) < 100:
            return matches
    raise ValueError("Submission history exceeds scan bound; refusing an ambiguous mutation")


def reconcile_submission(api, bundle):
    matches = submissions_with_marker(api, bundle)
    if len(matches) != 1:
        raise ValueError(f"Expected one submission for this candidate; found {len(matches)}")
    existing = Path(bundle) / "evidence" / "submission-receipt.json"
    if existing.exists() and receipt(bundle, "submission-receipt.json")["ref"] != matches[0].ref:
        raise ValueError("Conflicting submission receipts")
    return event(bundle, "submission-receipt.json", ref=int(matches[0].ref), action="adopted_existing")


def active_submissions(api):
    """Keep official reruns bounded; normal CPU/GPU notebook runs stay separate."""
    active = []
    for page in range(1, 101):
        values = api.competition_submissions(COMPETITION, page_number=page, page_size=100) or []
        active.extend({"ref": int(s.ref), "status": enum_name(s.status)} for s in values if s is not None
                      and enum_name(getattr(s, "status", "")) in ("PENDING", "RUNNING"))
        if len(values) < 100:
            return active
    raise ValueError("Submission inventory exceeds scan bound")


def collect_output(api, bundle):
    """Collect diagnostics before any competition submission, including failures."""
    stored = receipt(bundle, "kernel-receipt.json")
    checked = remote_check(api, bundle, stored["version"])
    status = observe_kernel(api, bundle)
    if status["status"] not in ("COMPLETE", "ERROR", "CANCEL_ACKNOWLEDGED"):
        raise ValueError("Wait for a terminal notebook status before collecting final output")
    evidence = Path(bundle) / "evidence"
    output = evidence / "notebook-output"
    if (evidence / "output.json").exists():
        value = receipt(bundle, "output.json")
        if value["version"] != checked["version"]:
            raise ValueError("Output receipt belongs to another notebook version")
        for name, expected in value["files"].items():
            path = output / name
            if not path.is_file() or cycle_file_digest(path) != expected:
                raise ValueError("Collected notebook output changed")
        return value
    if output.exists():
        raise ValueError("Previous output collection exists without a receipt; inspect before retrying")
    output.mkdir()
    api.kernels_output(f"{checked['kernel']}/{checked['version']}", str(output), quiet=True,
                       file_pattern=r"(^|/)(submission[.]parquet|__result[.]json|__notebook[.]ipynb|.*[.]log|.*summary.*[.]json|.*diagnostic.*[.]json|.*[.]evidence[.]json)$")
    files = {p.relative_to(output).as_posix(): cycle_file_digest(p) for p in sorted(output.rglob("*")) if p.is_file()}
    return event(bundle, "output.json", kernel=checked["kernel"], version=checked["version"],
                 notebook_status=status["status"], files=files,
                 scope="Exact-version notebook output; not an official competition score")


def cycle_file_digest(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def require_gpu_validation(bundle):
    """A normal Notebook exit alone does not establish model/game connectivity."""
    evidence = Path(bundle) / "evidence"
    if not (evidence / "output.json").exists():
        raise ValueError("Collect exact-version GPU output before advancing the GPU line")
    files = list((evidence / "notebook-output").rglob("model-diagnostics.json"))
    if len(files) != 1:
        raise ValueError("GPU output lacks an unambiguous inference validation report")
    value = read(files[0])
    if not (value.get("passed") is True and value.get("backend_ready") is True
            and value.get("probe_completion_tokens", 0) > 0
            and value.get("game_generated_tokens", 0) > 0
            and value.get("non_reset_game_actions", 0) > 0):
        raise ValueError("GPU validation requires model tokens and a non-RESET game action")
    return value


def authorize_rejected_submission_retry(api, bundle, proof_path):
    """One reviewed HTTP 400 recovery; original and retry intents are retained."""
    if (Path(bundle) / "evidence/submission-receipt.json").exists():
        return receipt(bundle, "submission-receipt.json")
    if submissions_with_marker(api, bundle):
        return reconcile_submission(api, bundle)
    if active_submissions(api):
        raise ValueError("Wait for all active official evaluations before rejection recovery")
    original = receipt(bundle, "submission-intent.json")
    proof = read(proof_path)
    if not (proof.get("confirmed_http_rejection") is True and proof.get("status_code") == 400
            and proof.get("candidate_id") == verify(bundle)["candidate_id"]
            and proof.get("kernel") == original.get("kernel")
            and proof.get("version") == original.get("version")):
        raise ValueError("Recovery needs reviewed HTTP 400 evidence for the exact candidate and version")
    if (Path(bundle) / "evidence/submission-retry-intent.json").exists():
        raise ValueError("One retry was already attempted; reconcile without another retry")
    return event(bundle, "submission-retry-authorization.json", reviewed_proof=proof,
                 original_intent_sha256=cycle_file_digest(Path(bundle) / "evidence/submission-intent.json"),
                 marker_matches=0, active_submissions=0, maximum_additional_submit_calls=1)


def submit(api, bundle):
    verify(bundle, launch=True)
    evidence = Path(bundle) / "evidence"
    if (evidence / "submission-receipt.json").exists():
        return receipt(bundle, "submission-receipt.json")
    require_connection_check(bundle)
    if (evidence / "push-error.json").exists():
        raise ValueError("Rejected push cannot be submitted")
    stored = receipt(bundle, "kernel-receipt.json")
    checked = remote_check(api, bundle, stored["version"])
    status = observe_kernel(api, bundle)
    if status["status"] != "COMPLETE":
        raise ValueError("Notebook has not completed successfully")
    matches = submissions_with_marker(api, bundle)
    if matches:
        return reconcile_submission(api, bundle)
    active = active_submissions(api)
    if active:
        return event(bundle, "submission-deferred.json", action="deferred_without_submitting", active_submissions=active,
                     reason="Wait for the existing official evaluation before starting another one")
    retry = (evidence / "submission-intent.json").exists()
    if retry:
        authorization = evidence / "submission-retry-authorization.json"
        if not authorization.exists():
            raise ValueError("Previous submit may have succeeded. Reconcile; do not submit again")
        approved = receipt(bundle, authorization.name)
        if approved.get("original_intent_sha256") != cycle_file_digest(evidence / "submission-intent.json"):
            raise ValueError("Original submission intent changed after recovery review")
        if (evidence / "submission-retry-intent.json").exists():
            raise ValueError("Previous retry may have succeeded. Reconcile; do not retry again")
    # The remote output must exist for the exact completed version.
    collect_output(api, bundle)
    if verify(bundle)["identity"]["line"] == "gpu":
        require_gpu_validation(bundle)
    output = evidence / "notebook-output"
    parquet = output / "submission.parquet"
    if not parquet.is_file() or parquet.stat().st_size == 0:
        raise ValueError("Exact notebook version did not produce submission.parquet")
    intent(bundle, "submission-retry-intent.json" if retry else "submission-intent.json",
           kernel=checked["kernel"], version=checked["version"], maximum_submit_calls=1)
    try:
        result = api.competition_submit_code("submission.parquet", marker(bundle), COMPETITION,
                                             checked["kernel"], checked["version"], quiet=True)
    except Exception as exc:
        response = getattr(exc, "response", None)
        message = str(getattr(response, "text", ""))[:2000]
        token = os.environ.get("KAGGLE_API_TOKEN")
        if token:
            message = message.replace(token, "[redacted]")
        event(bundle, "submission-retry-http-error.json" if retry else "submission-http-error.json", status_code=getattr(response, "status_code", None),
              error_type=type(exc).__name__, message=message, recovery="Reconcile the candidate marker; do not resubmit automatically")
        raise
    saved = event(bundle, "submission-receipt.json", ref=int(result.ref or 0), message=result.message,
                  kernel=checked["kernel"], version=checked["version"],
                  action="submitted_once_after_reviewed_rejection" if retry else "submitted_once")
    if saved["ref"] < 1:
        raise ValueError("No submission ref returned; reconcile without resubmitting")
    return saved


def observe_score(api, bundle):
    stored = receipt(bundle, "submission-receipt.json")
    result = api.get_submission(stored["ref"])
    if int(result.ref) != stored["ref"] or (result.description or "").split(" ", 1)[0] != marker(bundle):
        raise ValueError("Official submission identity mismatch")
    value = event(bundle, "official-score.json", ref=int(result.ref), status=enum_name(result.status),
                  public_score=result.public_score, private_score=result.private_score,
                  error_description=result.error_description, description=result.description,
                  line=verify(bundle)["identity"]["line"], competition=COMPETITION)
    with (Path(bundle) / "evidence" / "score-history.jsonl").open("ab") as stream:
        stream.write(json.dumps(value, sort_keys=True).encode() + b"\n")
    return value


def require_comparable_execution(baseline, candidate):
    before, after = verify(baseline), verify(candidate)
    for key in ("line", "runtime", "session_timeout_seconds"):
        if before["identity"][key] != after["identity"][key]:
            raise ValueError("Incomparable experiment conditions: " + key)
    images = [receipt(path, "readback.json").get("docker_image") for path in (baseline, candidate)]
    if not all(images) or images[0] != images[1]:
        raise ValueError("Observed Kaggle runtime images differ or are missing")
    connection_reports = [require_connection_check(path)["report"] for path in (baseline, candidate)]
    for key in ("competition_zip_sha256", "gpu_source_zip_sha256"):
        if connection_reports[0].get(key) != connection_reports[1].get(key):
            raise ValueError("Connection input contents differ: " + key)
    return before, after


def compare(baseline, candidate):
    before, after = require_comparable_execution(baseline, candidate)
    values = [receipt(path, "official-score.json") for path in (baseline, candidate)]
    for value in values:
        if value["status"] != "COMPLETE" or value["public_score"] in (None, "") or value["competition"] != COMPETITION:
            raise ValueError("Both candidates need complete official public scores")
    old, new = (Decimal(str(value["public_score"])) for value in values)
    if not old.is_finite() or not new.is_finite():
        raise ValueError("Official scores must be finite")
    return {"line": before["identity"]["line"], "baseline": before["candidate_id"],
            "candidate": after["candidate_id"], "baseline_ref": values[0]["ref"], "candidate_ref": values[1]["ref"],
            "baseline_public_score": str(old), "candidate_public_score": str(new),
            "absolute_change": str(new-old), "improved_public_score": new > old,
            "scope": "Observed public scores for these two submissions; not private performance or causal attribution"}


def api_client():
    from kaggle.api.kaggle_api_extended import KaggleApi
    api = KaggleApi()
    api.authenticate()
    return api


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    p = commands.add_parser("prepare")
    p.add_argument("--profile", choices=profiles(), required=True)
    p.add_argument("--out", type=Path, required=True)
    p.add_argument("--label", required=True)
    p.add_argument("--hypothesis", required=True)
    p.add_argument("--notebook", type=Path)
    p.add_argument("--environment", type=Path)
    p.add_argument("--owner", default="sumuji")
    p = commands.add_parser("resolve-environment")
    p.add_argument("--out", type=Path, required=True)
    for name in ("verify", "start", "adopt-kernel", "observe-kernel", "collect-output", "submit", "reconcile-submission", "observe-score"):
        p = commands.add_parser(name)
        p.add_argument("--bundle", type=Path, required=True)
        if name == "adopt-kernel":
            p.add_argument("--version", type=int, required=True)
    p = commands.add_parser("compare")
    p.add_argument("--baseline", type=Path, required=True)
    p.add_argument("--candidate", type=Path, required=True)
    p.add_argument("--out", type=Path)
    p = commands.add_parser("attach-connection")
    p.add_argument("--bundle", type=Path, required=True)
    p.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    if args.command == "prepare":
        result = prepare(args.profile, args.out, args.label, args.hypothesis, args.notebook, args.environment, args.owner)
    elif args.command == "verify":
        result = verify(args.bundle)
    elif args.command == "compare":
        result = compare(args.baseline, args.candidate)
        if args.out:
            save(args.out, result, exclusive=True)
    elif args.command == "attach-connection":
        result = attach_connection_check(args.bundle, args.report)
    else:
        api = api_client()
        if args.command == "resolve-environment":
            result = environment(api, args.out)
        elif args.command == "adopt-kernel":
            result = adopt(api, args.bundle, args.version)
        else:
            result = {"start": start, "observe-kernel": observe_kernel, "collect-output": collect_output, "submit": submit,
                      "reconcile-submission": reconcile_submission, "observe-score": observe_score}[args.command](api, args.bundle)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
