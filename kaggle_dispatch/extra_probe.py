"""Read-only, privacy-conscious diagnostics for three owned Kaggle notebooks.

Run alongside the existing owned_probe.py. Emits only numeric identities,
fingerprints, and booleans; never emits source, response bodies, or secrets.
"""
import json
import os
import subprocess
import sys

import owned_probe

TARGETS = {
    "search_curve": {
        "ref": "sumuji/search-curve-bridge-kaggle",
        "gpu": False,
        "model_sources": [],
        "expected_hash": "bab19d71ff050cba201a09240529bf09624a3cfaec9aee8b4fbbaffbff2f352b",
    },
    "arc3_memory": {
        "ref": "sumuji/arc3-memory-regression-kaggle",
        "gpu": False,
        "model_sources": [],
        "expected_hash": "10f3c5139969a56a7a688092e60c38b72be53c3c23d91b805978a41ed855990e",
    },
    "tbp_forest": {
        "ref": "sumuji/research-models-tbp-forest-kaggle",
        "gpu": False,
        "model_sources": [],
        "expected_hash": "f69df62dc526be37a650db8f395dcdd60eeeb400d6f0dff7f702b462c5720ee5",
    },
}


def main():
    if not os.environ.get("KAGGLE_API_TOKEN"):
        raise RuntimeError("Kaggle credential unavailable")
    owned_probe.TARGETS = TARGETS
    for kind, target in TARGETS.items():
        result = owned_probe.pull(kind)
        result["local_source_matches"] = (
            result["canonical_cell_sha256"] == target["expected_hash"]
        )
        print(json.dumps(result, sort_keys=True))
    print("Read-only probes finished; no notebook updated")


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError, subprocess.TimeoutExpired, owned_probe.ProbeError, RuntimeError):
        print("Probe failed; details suppressed; no update attempted", file=sys.stderr)
        sys.exit(1)
