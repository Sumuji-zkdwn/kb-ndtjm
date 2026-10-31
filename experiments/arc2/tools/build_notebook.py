"""Build a self-contained, internet-disabled Kaggle notebook from local sources."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path


def code_cell(source: str) -> dict:
    return {"cell_type": "code", "execution_count": None, "metadata": {}, "outputs": [], "source": source.splitlines(keepends=True)}


def markdown_cell(source: str) -> dict:
    return {"cell_type": "markdown", "metadata": {}, "source": source.splitlines(keepends=True)}


def build_notebook(source_root: Path, output: Path) -> dict:
    paths = sorted((source_root / "arc2").rglob("*.py"))
    if not paths or not (source_root / "arc2/solver.py").is_file():
        raise ValueError("The source root must contain the complete arc2 package")
    if not (source_root / "LICENSE").is_file():
        raise ValueError("The source root must contain the package LICENSE")
    paths.append(source_root / "LICENSE")
    vendor = source_root / "vendor/icecuber"
    if vendor.is_dir():
        paths += sorted(p for p in vendor.rglob("*") if p.is_file() and (
            p.suffix in {".cpp", ".hpp", ".h", ".cc"}
            or p.name in {"LICENSE", "PROVENANCE.md", "SOURCE_MANIFEST.json"}
        ))
    sources = {str(path.relative_to(source_root)): path.read_text(encoding="utf-8") for path in paths}
    hashes = {key: hashlib.sha256(text.encode()).hexdigest() for key, text in sources.items()}
    setup = '''from pathlib import Path
import json, os, subprocess, sys

# The notebook contains every source file. No download or pip install is needed.
# Bound numerical library threads before importing NumPy in worker processes.
for name in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS", "NUMEXPR_NUM_THREADS"):
    os.environ[name] = "1"
RUNTIME_ROOT = Path("/kaggle/working/arc2_runtime") if Path("/kaggle/working").is_dir() else Path.cwd() / "arc2_runtime"
RUNTIME_ROOT.mkdir(parents=True, exist_ok=True)
'''
    setup += "PACKAGE_FILES = " + repr(sources) + "\n"
    setup += '''for relative, contents in PACKAGE_FILES.items():
    destination = RUNTIME_ROOT / relative
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(contents, encoding="utf-8")
print("Embedded source files written:", len(PACKAGE_FILES))
'''
    config = '''# You may set ARC2_CHALLENGES to an explicit local challenges file.
# Automatic discovery accepts only the competition's test-challenges filenames.
explicit_path = os.environ.get("ARC2_CHALLENGES")
if explicit_path:
    CHALLENGES = Path(explicit_path)
    if not CHALLENGES.is_file():
        raise FileNotFoundError(CHALLENGES)
else:
    roots = [Path("/kaggle/input/competitions/arc-prize-2026-arc-agi-2"),
             Path("/kaggle/input/arc-prize-2026-arc-agi-2")]
    names = ("arc-agi_test_challenges.json", "arc_agi_test_challenges.json")
    candidates = sorted({(root / name).resolve() for root in roots for name in names if (root / name).is_file()})
    if not candidates and Path("/kaggle/input").is_dir():
        candidates = sorted({p.resolve() for name in names for p in Path("/kaggle/input").rglob(name)
                             if "arc-prize-2026-arc-agi-2" in p.parts})
    if len(candidates) != 1:
        raise RuntimeError("Expected one ARC-AGI-2 test-challenges file; found " + str(candidates) +
                           ". Attach the competition data or set ARC2_CHALLENGES explicitly.")
    CHALLENGES = candidates[0]

OUTPUT_ROOT = Path("/kaggle/working") if Path("/kaggle/working").is_dir() else Path.cwd()
SUBMISSION = OUTPUT_ROOT / "submission.json"
DIAGNOSTICS = OUTPUT_ROOT / "arc2_diagnostics.json"
SECONDS_PER_TASK = float(os.environ.get("ARC2_SECONDS_PER_TASK", "8.0"))
TOTAL_SECONDS = 11 * 60 * 60
MAX_STATES = int(os.environ.get("ARC2_MAX_STATES", "4000"))
BEAM_WIDTH = int(os.environ.get("ARC2_BEAM_WIDTH", "32"))
MAX_DEPTH = int(os.environ.get("ARC2_MAX_DEPTH", "3"))
BACKEND = os.environ.get("ARC2_BACKEND", "hybrid")  # "python" disables C++ search.
CPP_FRACTION = float(os.environ.get("ARC2_CPP_FRACTION", "0.6"))
CPP_MEMORY_MB = int(os.environ.get("ARC2_CPP_MEMORY_MB", "768"))
COMPILE_SECONDS = 180.0
print("Challenges:", CHALLENGES)
print("Total wall budget:", TOTAL_SECONDS, "seconds")
'''
    run = '''# Prepare the optional C++ backend once, before any per-task time budget.
# The full source and upstream MIT license are embedded above; no download occurs.
sys.path.insert(0, str(RUNTIME_ROOT))
from arc2.runner import prepare_requested_backend, atomic_json, challenge_for_solver, fallback_attempts
challenges = json.loads(CHALLENGES.read_text(encoding="utf-8"))
initial = {task_id: fallback_attempts(challenge_for_solver(task)) for task_id, task in challenges.items()}
atomic_json(SUBMISSION, initial)
BACKEND_PREPARATION = prepare_requested_backend(BACKEND, COMPILE_SECONDS)
EFFECTIVE_BACKEND = BACKEND_PREPARATION["effective"]
print("Backend preparation:", BACKEND_PREPARATION)
command = [sys.executable, "-m", "arc2", "solve",
           "--challenges", str(CHALLENGES), "--output", str(SUBMISSION),
           "--diagnostics", str(DIAGNOSTICS),
           "--seconds-per-task", str(SECONDS_PER_TASK),
           "--total-seconds", str(TOTAL_SECONDS),
           "--max-states", str(MAX_STATES), "--beam-width", str(BEAM_WIDTH),
           "--max-depth", str(MAX_DEPTH), "--backend", EFFECTIVE_BACKEND,
           "--cpp-fraction", str(CPP_FRACTION), "--cpp-memory-mb", str(CPP_MEMORY_MB),
           "--compile-seconds", str(COMPILE_SECONDS)]
subprocess.run(command, cwd=RUNTIME_ROOT, check=True)
from arc2.runner import validate_submission
challenges = json.loads(CHALLENGES.read_text(encoding="utf-8"))
submission = json.loads(SUBMISSION.read_text(encoding="utf-8"))
assert validate_submission(submission, challenges), "Submission schema validation failed"
diagnostics = json.loads(DIAGNOSTICS.read_text(encoding="utf-8"))
diagnostics["notebook_backend_preparation"] = BACKEND_PREPARATION
atomic_json(DIAGNOSTICS, diagnostics)
print("Ready:", SUBMISSION, "tasks:", len(submission), "test outputs:", sum(map(len, submission.values())))
'''
    notebook = {
        "cells": [
            markdown_cell("# ARC-AGI-2 — symbolic candidate\n\n"
                          "CPUとNumPyで動作する独立候補です。任意のC++探索バックエンドを同梱し、"
                          "コンパイラが利用できない場合はPython探索で実行します。インターネットを無効にして実行できます。\n\n"
                          "各問題の例示入出力だけから規則を探し、テスト入力ごとに2候補を出力します。"
                          "途中終了に備え、`submission.json`は最初から全問題を含み、問題ごとに更新します。\n\n"
                          "既定条件は1問8秒・4000状態・ビーム幅32・深さ3・C++時間配分0.6・C++メモリ768MBです。"
                          "設定セルまたは`ARC2_`環境変数で変更できます。条件を変更した場合は改めて評価してください。\n\n"
                          "公式採点への提出はこのNotebookには含まれません。Kaggle上の設定ではCPU、"
                          "Internet off、出力ファイル`submission.json`を使用してください。\n"),
            code_cell(setup), code_cell(config), code_cell(run),
        ],
        "metadata": {
            "kernelspec": {"display_name": "Python 3", "language": "python", "name": "python3"},
            "language_info": {"name": "python", "version": "3.11"},
            "arc2_source_sha256": hashes,
            "arc2_network_required": False,
            "arc2_default_config": {"time_limit": 8.0, "max_states": 4000, "beam_width": 32,
                                    "max_depth": 3, "cpp_fraction": 0.6, "cpp_memory_mb": 768,
                                    "backend": "hybrid", "total_seconds": 39600},
        },
        "nbformat": 4,
        "nbformat_minor": 5,
    }
    for index, cell in enumerate(notebook["cells"]):
        cell["id"] = f"arc2-{index:02d}"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(notebook, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    return {"notebook": str(output), "bytes": output.stat().st_size, "source_sha256": hashes}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    output = args.output or args.source_root / "arc2_kaggle.ipynb"
    print(json.dumps(build_notebook(args.source_root, output), indent=2))


if __name__ == "__main__":
    main()
