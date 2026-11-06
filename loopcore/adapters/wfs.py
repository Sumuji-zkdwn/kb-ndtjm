"""Private WFS adapter for the portable operator loop.

Reuses quantum/wfs_mobile_ci.py IN PLACE, avoiding public disclosure or
divergent copies of the original quantum circuit implementation.
This validates only local kernels; never claims full DQI verification.
"""
from __future__ import annotations

import json

from quantum import wfs_mobile_ci as source

DOMAIN = "wfs"
VARIANTS = (
    {"name": "google", "poly": 0x1053, "scale": 1},
    {"name": "public", "poly": 0x10EB, "scale": 1},
    {"name": "scaled52", "poly": 0x1053, "scale": 0x52},
)


def candidates():
    for model in VARIANTS:
        yield dict(model)


def build(model: dict, cycle: int) -> dict[str, bytes]:
    if model not in VARIANTS:
        raise ValueError("variant outside the reviewed finite catalogue")
    ops = source.compile_ops(model["poly"], model["scale"])
    kernel = "# Local WFS phase kernel. Not a full DQI circuit.\n" + "\n".join(ops) + "\n"
    metadata = json.dumps(model, sort_keys=True, indent=2) + "\n"
    return {"kernel.kmx": kernel.encode("utf-8"), "model.json": metadata.encode("utf-8")}


def check(model: dict, artifacts: dict[str, bytes], cycle: int) -> dict:
    if model not in VARIANTS:
        return {"passed": False, "reason": "unknown WFS configuration"}
    if artifacts != build(model, cycle):
        return {"passed": False, "reason": "candidate bytes differ from generator"}
    try:
        ops = artifacts["kernel.kmx"].decode("utf-8").splitlines()[1:]
        exact = source.verify_exact(ops, model["poly"], model["scale"])
        samples = source.verify_samples(ops, model["poly"], model["scale"], samples=120)
    except (AssertionError, ValueError, KeyError, IndexError) as exc:
        return {"passed": False, "reason": f"{type(exc).__name__}: {exc}"}
    return {
        "passed": True,
        "method": "GF2_ANF_exact_and_120_samples",
        "scope": "local WFS GF(2^12) phase kernel only",
        "variant": model["name"],
        "total_ops": exact["total_ops"],
        "op_counts": exact["op_counts"],
        "phase_monomials": exact["phase_monomials"],
        "restored_and_clean": exact["restored_and_clean"],
        "random_checks": samples,
        "kickmix_parser": "NOT_RUN_BY_THIS_ADAPTER",
        "official_dqi_verifier": "NOT_RUN",
        "kaggle_submission": "NOT_RUN",
    }
