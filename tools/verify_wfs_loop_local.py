#!/usr/bin/env python3
"""Offline, standard-library-only local WFS verification for the PRIVATE repo.

Executes the actual quantum/wfs_mobile_ci.py and private loopcore adapter.
Does NOT run Kickmix, the full DQI verifier or submit to Kaggle.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import platform
from pathlib import Path
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from quantum import wfs_mobile_ci as original
from loopcore.adapters import wfs
from loopcore.engine import audit, run_one


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def verify() -> dict:
    cases = []
    with tempfile.TemporaryDirectory(prefix="wfs-loop-verify-") as td:
        root = Path(td)
        for cycle, model in enumerate(wfs.candidates(), 1):
            result = run_one(root, "wfs")
            assert result["status"] == "verified" and result["cycle"] == cycle
            assert result["model"] == model
            ops = original.compile_ops(model["poly"], model["scale"])
            artifact = root / "cycles" / f"{cycle:05d}" / "kernel.kmx"
            lines = artifact.read_text(encoding="utf-8").splitlines()
            assert lines[1:] == ops, "generated kernel differs from original compiler"
            exact = original.verify_exact(ops, model["poly"], model["scale"])
            assert exact["phase_ANF_exact"] and exact["restored_and_clean"]
            assert original.verify_samples(ops, model["poly"], model["scale"], samples=120) == 120
            cases.append({
                "model": model,
                "cycle": cycle,
                "total_ops": exact["total_ops"],
                "op_counts": exact["op_counts"],
                "phase_monomials": exact["phase_monomials"],
                "variables": exact["variables"],
                "local_phase_anfs_match": True,
                "registers_restored": True,
                "seeded_samples": 120,
                "kernel_sha256": digest(artifact),
            })
        assert [row["total_ops"] for row in cases] == [432, 520, 522]
        assert run_one(root, "wfs")["status"] == "exhausted"
        checked = audit(root, "wfs", rerun_checks=True)
        assert checked["passed"] and checked["cycles"] == 3 and checked["recomputed_domain_checks"]
        return {
            "status": "PASS",
            "scope": "local WFS GF(2^12) phase-kernel compiler and extracted loop only",
            "python": platform.python_version(),
            "original_source_sha256": digest(ROOT / "quantum/wfs_mobile_ci.py"),
            "private_adapter_sha256": digest(ROOT / "loopcore/adapters/wfs.py"),
            "controller_sha256": digest(ROOT / "loopcore/engine.py"),
            "cases": cases,
            "reentry": {"cycles": 3, "saturated": True, "full_recheck": True},
            "kickmix_parser": "NOT_RUN",
            "official_dqi_verifier": "NOT_RUN",
            "kaggle_submission": "NOT_RUN",
            "github_actions_status": "NOT_CHECKED_BY_THIS_SCRIPT",
        }


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--output", type=Path, help="write JSON evidence file")
    args = p.parse_args()
    result = verify()
    content = json.dumps(result, sort_keys=True, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(content, encoding="utf-8")
    print(content, end="")


if __name__ == "__main__":
    main()
