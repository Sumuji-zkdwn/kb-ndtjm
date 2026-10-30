"""One-shot SDK response probe, using only the dedicated synthetic Kaggle anchor.

Never prints the source, raw service response, user inputs, or credentials.
"""
import json
import os
import pathlib
import sys
import tempfile
import time
from urllib.parse import urlsplit

import router


TARGET = {
    "ref": "sumuji/dispatch-anchor-20261031-c9fa2c1d",
    "id": 141798233,
    "title": "dispatch-anchor-20261031-c9fa2c1d",
    "hash": "488c5213b6d5b19cdcfc7badc5397ba3064c23ba90081ca3d3f4751fe924501b",
    "gpu": False,
    "models": [],
}
REQ = {"id": "receipt-probe-20261031-d4", "previous_id": "receipt-probe-20261031-d3", "kind": "diagnostic"}


def category(response):
    ref = getattr(response, "ref", None)
    ident = getattr(response, "kernel_id", None)
    version = getattr(response, "version_number", None)
    fields = {}
    for f in router.FIELDS:
        v = getattr(response, f, None)
        fields[f] = "empty" if isinstance(v, list) and not v else "nonempty" if isinstance(v, list) else "missing_or_other"
    public_synthetic_ref = "redacted"
    if isinstance(ref, str):
        try:
            parsed = urlsplit(ref)
            # This one dedicated non-personal test identifier may be logged only
            # with a verified Kaggle origin and a simple path, never query/fragment.
            if (parsed.scheme == "https" and parsed.netloc in {"www.kaggle.com", "kaggle.com"}
                and not parsed.query and not parsed.fragment and TARGET["ref"] in parsed.path
                and all(c.isascii() and (c.isalnum() or c in "/-_.") for c in parsed.path)):
                public_synthetic_ref = ref
        except ValueError:
            pass
    return {
        "error_present": bool(getattr(response, "error", None)),
        "ref_category": "exact" if ref == TARGET["ref"] else "empty" if ref in (None, "") else "url_form" if isinstance(ref, str) and ref.rstrip("/").endswith("/" + TARGET["ref"]) else "other",
        "kernel_id_category": "exact" if ident == TARGET["id"] else "zero_or_missing" if ident in (0, None) else "other",
        "version_category": "four" if type(version) is int and version == 4 else "positive_other" if type(version) is int and version > 0 else "invalid",
        "synthetic_ref_if_safe": public_synthetic_ref,
        "invalid_fields": fields,
    }


def run(api):
    if os.environ.get("GITHUB_RUN_ATTEMPT") != "1":
        raise router.RouterError("action retries disabled")
    if router.state(api, TARGET["ref"]) != "COMPLETE":
        raise router.RouterError("anchor not complete")
    first_meta, first_nb = router.pull(api, TARGET)
    prepared, digest, history = router.prepare(first_nb, REQ, TARGET)
    if prepared is None:
        raise router.RouterError("probe marker already present; no second update")
    second_meta, second_nb = router.pull(api, TARGET)
    prepared2, digest2, history2 = router.prepare(second_nb, REQ, TARGET)
    keys = ("id", "id_no", "title", "is_private", "enable_gpu", "enable_tpu", "enable_internet",
            "dataset_sources", "kernel_sources", "competition_sources", "model_sources", "machine_shape", "docker_image", "keywords")
    if (prepared2 is None or digest != digest2 or history != history2 or
        any(first_meta.get(k) != second_meta.get(k) for k in keys) or router.state(api, TARGET["ref"]) != "COMPLETE"):
        raise router.RouterError("anchor changed during checks")
    meta = {"id": TARGET["ref"], "id_no": TARGET["id"], "title": TARGET["title"], "code_file": "job.ipynb",
            "language": "python", "kernel_type": "notebook", "is_private": True, "enable_gpu": False,
            "enable_internet": first_meta["enable_internet"], "keywords": first_meta["keywords"],
            "dataset_sources": [], "competition_sources": [], "kernel_sources": [], "model_sources": []}
    if first_meta.get("docker_image"):
        meta["docker_image"] = first_meta["docker_image"]
    with tempfile.TemporaryDirectory(prefix="synthetic-receipt-probe-") as tmp:
        path = pathlib.Path(tmp)
        (path / "job.ipynb").write_text(json.dumps(prepared), encoding="utf-8")
        (path / "kernel-metadata.json").write_text(json.dumps(meta), encoding="utf-8")
        response = router.quiet_call(api.kernels_push, str(path))
    info = category(response)
    print(json.dumps(info, sort_keys=True))
    # Probe only its own expected next v4; never blindly retry even on errors.
    if info["error_present"] or info["version_category"] != "four" or any(v != "empty" for v in info["invalid_fields"].values()):
        raise router.RouterError("response ambiguous; inspect anchor before any retry")
    deadline = time.monotonic() + 300
    ref = TARGET["ref"] + "/4"
    while time.monotonic() < deadline:
        status = router.state(api, ref)
        if status == "COMPLETE":
            _, nb = router.pull(api, TARGET, ref)
            after, _, ledger = router.prepare(nb, REQ, TARGET)
            if after is not None or ledger != [REQ["previous_id"], REQ["id"]]:
                raise router.RouterError("completed anchor source or marker mismatch")
            print(json.dumps({"version": 4, "version_specific_status": status, "marker_verified": True}))
            return
        if status in {"ERROR", "CANCEL_REQUESTED", "CANCEL_ACKNOWLEDGED"}:
            raise router.RouterError("probe execution failed")
        time.sleep(15)
    raise router.RouterError("probe timeout; do not retry")


def main():
    if not os.environ.get("KAGGLE_API_TOKEN"):
        raise router.RouterError("credential unavailable")
    from kaggle.api.kaggle_api_extended import KaggleApi
    api = KaggleApi()
    router.quiet_call(api.authenticate)
    run(api)


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        # The fixed category only, never raw network error details.
        print("Probe stopped: " + (str(exc) if isinstance(exc, router.RouterError) else "details suppressed"), file=sys.stderr)
        sys.exit(1)
