"""Collect the preserved dialogue and official evaluation records for the report.

Run from this checkout after retaining the sibling experiment directories. This
copies records without changing the originals and checks the report's arithmetic.
"""

from decimal import Decimal
import hashlib
import json
from pathlib import Path
import shutil


REPO = Path(__file__).resolve().parents[2]
WORKSPACE = REPO.parent
HERE = Path(__file__).resolve().parent


def read(path):
    return json.loads(path.read_text(encoding="utf-8"))


def sha(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def collect():
    groups = {
        "initial": ("dqi_pr7_blind_coop_20261027", [
            "session.json", "private_change_record.json", "theory_baseline.txt",
            "theory_after_dialogue.txt", "algebra_verification.json", "dialogue_verification.json",
            *[f"{kind}_{n:02}.txt" for n in range(1, 4) for kind in ("prompt", "reply")]]),
        "fusion": ("fusion_experiment_20261027", [
            "provenance.json", "fusion_verification.json", "scalar_verification.json",
            *[f"{kind}_{n:02}.txt" for n in range(4, 7) for kind in ("prompt", "reply")]]),
        "dual": ("dual_gemini_20261027", [
            "provenance.json", "private_change_record.json", "cleanup_counterexample.json",
            "optimized_verification.json", "intermediate56_optimized_verification.json",
            *[f"a_{kind}_{n:02}.txt" for n in range(1, 4) for kind in ("prompt", "reply")],
            *[f"b_{kind}_{n:02}.txt" for n in range(1, 5) for kind in ("prompt", "reply")],
            *[f"b_reply_{n:02}.ax.txt" for n in range(1, 5)]]),
        "official": ("kaggle_submission_pr8_20261027", [
            "comparison.json", "submitted-package-audit.json", "completed-workflow.json",
            "official-api/pr7-official-api.json", "official-api/pr8-official-api.json",
            "official-api/receipt.json", "official-api/status-history.jsonl"]),
    }
    sources = []
    for group, (directory, names) in groups.items():
        for name in names:
            source = WORKSPACE / directory / name
            target = HERE / "records" / group / name
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, target)
            assert sha(source) == sha(target)
            if target.suffix == ".json":
                read(target)
            sources.append({"workspace_source": source.relative_to(WORKSPACE).as_posix(),
                "report_copy": target.relative_to(REPO).as_posix(),
                "sha256": sha(target), "bytes": target.stat().st_size})
    image_source = WORKSPACE / "kaggle_submission_pr8_20261027/pr7-pr8-official-scores.jpg"
    image_target = REPO / "docs/assets/dqi-pr7-pr8-kaggle-20261027.jpg"
    image_target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(image_source, image_target)
    assert sha(image_source) == sha(image_target)
    sources.append({"workspace_source": image_source.relative_to(WORKSPACE).as_posix(),
        "report_copy": image_target.relative_to(REPO).as_posix(),
        "sha256": sha(image_target), "bytes": image_target.stat().st_size})

    initial = read(HERE / "records/initial/session.json")
    fusion = read(HERE / "records/fusion/fusion_verification.json")
    local = read(HERE / "records/dual/optimized_verification.json")
    pr7 = read(REPO / "checkpoints/bm-tracephase3-20261027.json")
    pr8 = read(REPO / "checkpoints/bm-blindcoop-20261027.json")
    official = read(HERE / "records/official/comparison.json")
    assert initial["user_messages_sent"] == initial["assistant_replies_received"] == 3
    assert local["status"] == fusion["status"] == "PASS"
    assert official["pr7_official"]["status"] == official["pr8_official"]["status"] == "COMPLETE"
    assert official["submitted_package_audit"]["only_dqi_changed"]
    old, new = pr7["generation_snapshot"], pr8["generation_snapshot"]
    assert old["static_Toffoli"] - new["static_Toffoli"] == 4095
    assert old["ops"] - new["ops"] == 4095 * (local["baseline_total_operations"] - local["candidate_total_operations"])
    assert old["qubits"] == new["qubits"] == 2482
    old_score = Decimal(official["pr7_official"]["public_score"])
    new_score = Decimal(official["pr8_official"]["public_score"])
    assert new_score - old_score == Decimal("0.00317")
    assert str((new_score / old_score - 1) * 100) == official["relative_public_score_change_percent"]
    summary = {
        "compiled_for": "2026-10-27 blind-cooperation procedure and PR7-to-PR8 report",
        "case_scope": "One sequential artifact improvement with official public scoring",
        "procedure_basis": {"workspace_source": "AGENTS.md", "sha256": sha(WORKSPACE / "AGENTS.md")},
        "conversation_A": initial["conversation_url"],
        "conversation_B": "https://gemini.google.com/app/3fedcaad74021583",
        "stages_and_exchanges": {"initial_A": 3, "fusion_A": 3, "dual_A": 3, "dual_B": 4},
        "local_phase_Toffoli": {"PR7": 69, "PR8": 68},
        "local_total_operations": {"PR7": local["baseline_total_operations"],
            "first_fusion": fusion["candidate_total_operations"], "PR8": local["candidate_total_operations"]},
        "full_DQI": {"PR7_Toffoli": old["static_Toffoli"], "PR8_Toffoli": new["static_Toffoli"],
            "saved_Toffoli": 4095, "PR7_operations": old["ops"], "PR8_operations": new["ops"],
            "saved_operations": old["ops"] - new["ops"], "Q_each": new["qubits"]},
        "official_public_score": {"PR7": str(old_score), "PR8": str(new_score),
            "absolute_change": str(new_score-old_score),
            "relative_change_percent": official["relative_public_score_change_percent"]},
        "official_score_record": "records/official/comparison.json",
        "initial_private_change": "records/initial/private_change_record.json",
        "later_private_change": "records/dual/private_change_record.json",
        "published_metric_reference": {
            "saved_source": "C:/Users/Dalcia/Research/02_Projects/quantum_circuit_compilation_2026-10-25/data/public_metric/v10/google-quantum-ai-metric.ipynb",
            "sha256_checked_for_report": "d9b8717ff09e52232c55047d504662369e9525207c769d3759ea25d4e9ae538f",
            "formula": "geometric_mean(baseline_cost_i / cost_i) over the three benchmarks",
        },
        "private_changes_were_disclosed_to_Gemini": False,
        "original_record_hashes_and_copies_match": True,
        "source_files": sources,
    }
    (HERE / "evidence.json").write_text(json.dumps(summary, indent=2, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n")
    print(json.dumps({"status": "PASS", "preserved_source_files": len(sources),
        "official_score": str(new_score), "score_change": str(new_score-old_score),
        "saved_full_instructions": old["ops"]-new["ops"]}))


if __name__ == "__main__":
    collect()
