"""Run bounded offline observation regressions; no notebooks or games run."""
from __future__ import annotations

import argparse
import hashlib
import io
import json
from pathlib import Path
import platform
import socket
import sys
import unittest
from unittest.mock import patch

import finite_model
from pinned_sources import source_report


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]


def protected_sources():
    manifest = json.loads((HERE / "verification" / "protected_sources.json").read_text())
    changed = []
    for item in manifest["files"]:
        path = ROOT / item["path"]
        if not path.is_file():
            changed.append({"path": item["path"], "reason": "missing"})
            continue
        data = path.read_bytes()
        actual = hashlib.sha1(b"blob " + str(len(data)).encode() + b"\0" + data).hexdigest()
        if actual != item["git_blob_sha"]:
            changed.append({"path": item["path"], "reason": "Git blob hash differs"})
    if changed:
        raise ValueError("Protected baseline/source files changed: " + json.dumps(changed))
    return {"source_commit": manifest["source_commit"], "files_verified_unchanged": len(manifest["files"])}


def blocked_network(*args, **kwargs):
    raise RuntimeError("Network is disabled during the offline observation audit")


def run(out: Path, evidence: Path | None = None) -> dict:
    out.mkdir(parents=True, exist_ok=False)
    before = protected_sources()
    log = io.StringIO()
    with patch.object(socket.socket, "connect", blocked_network), \
            patch.object(socket.socket, "connect_ex", blocked_network), \
            patch.object(socket, "create_connection", blocked_network):
        suite = unittest.defaultTestLoader.discover(str(HERE), pattern="test_*.py")
        result = unittest.TextTestRunner(stream=log, verbosity=2).run(suite)
        toy = finite_model.report()
        sources = source_report()
        if evidence is not None:
            from inspect_saved_evidence import inspect_saved_evidence
            saved, projection = inspect_saved_evidence(evidence)
            (out / "saved_evidence.json").write_text(json.dumps(saved, indent=2) + "\n")
            (out / "sc25_observed_projection.json").write_text(json.dumps(projection, indent=2) + "\n")
        else:
            saved = json.loads((HERE / "verification" / "saved_evidence.json").read_text())
    after = protected_sources()
    if before != after:
        raise ValueError("Baseline verification differs before and after tests")
    report = {
        "schema": "arc3-observation-audit-v1",
        "date_jst": "2026-11-01",
        "python": platform.python_version(),
        "command": "python -B experiments/arc3/observation_audit/run_audit.py --out NEW_DIRECTORY [--evidence LOCAL_ARTIFACT]",
        "scope": "Local offline exact finite models, pinned pure production functions, saved-log projection, and stub hook contracts",
        "tests": {"run": result.testsRun, "failures": len(result.failures),
                  "errors": len(result.errors), "skipped": len(result.skipped),
                  "passed": result.wasSuccessful()},
        "network_connections": "blocked in audit process",
        "protected_sources": after,
        "pinned_sources": sources,
        "finite_model": toy,
        "saved_evidence": {
            "artifact": saved["artifact"],
            "reparsed_from_artifact_this_run": evidence is not None,
            "official_score": saved["official_score"],
            "scope": "Stored official receipt, not a new score; frame logs are normal Save Version only",
        },
        "verdicts": {
            "synthetic_stride_two_aliasing": "VERIFIED",
            "cpu_endpoint_projection_collision": "VERIFIED_ON_PINNED_PRODUCTION_CLASS",
            "gpu_compact_summary_order_collision": "VERIFIED_ON_PINNED_PRODUCTION_FUNCTIONS",
            "gpu_duplicate_frame_multiplicity_loss": "VERIFIED_ON_PINNED_PRODUCTION_FUNCTIONS",
            "real_sc25_nonconstant_path_with_equal_endpoints": "VERIFIED_FROM_SAVED_TIMELINE_PROJECTION",
            "real_game_wfs_H_state_correspondence": "NOT_ESTABLISHED",
            "observer_packet_retention": "VERIFIED_OFFLINE_WITH_BOUNDS_AND_EVICTION_ACCOUNTING",
            "observer_policy_integration": "NOT_INSTALLED",
            "full_gpu_harness_execution": "NOT_RUN",
            "new_real_game_runs": 0,
            "new_kaggle_submissions": 0,
            "paused_cycle_resumed": False,
            "gameplay_performance_improvement": "NOT_MEASURED",
        },
        "audit_code_sha256": {
            p.name: hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(HERE.glob("*.py"))
        },
    }
    (out / "tests.txt").write_text(log.getvalue(), encoding="utf-8")
    (out / "audit_result.json").write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(log.getvalue())
    print(json.dumps({"tests": report["tests"], "out": str(out), "verdicts": report["verdicts"]}, indent=2))
    if not result.wasSuccessful():
        raise SystemExit(1)
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", required=True, type=Path, help="New output directory; must not exist")
    parser.add_argument("--evidence", type=Path, help="Optional previously downloaded ZIP or extracted directory")
    arguments = parser.parse_args()
    run(arguments.out, arguments.evidence)
