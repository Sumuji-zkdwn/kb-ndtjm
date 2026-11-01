"""Exercise pure observation code extracted from the unchanged ARC3 notebooks.

The complete notebook bytes are checked before parsing. No notebook cells,
installers, model launchers, environment actions, or submission paths execute.
Only the named observation class/functions below are compiled from their ASTs.
This is not an execution test of the full GPU harness or its deployment bundle.
"""
from __future__ import annotations

import ast
from collections import defaultdict
from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
from typing import Any, Sequence


SOURCE_COMMIT = "06ec316097d4bf22a44bfbd82dceb63f717680c4"
NOTEBOOKS = Path(__file__).resolve().parent.parent / "cycle" / "notebooks"
PINNED = {
    "cpu": ("cpu-c8b.ipynb", "03788c46195a6e48c8d865d67788f0d542472f0a29c4dffb67a9eabaf6874b8c"),
    "gpu": ("gpu-baseline-connected.ipynb", "f74e393d583dda6a3800dfd48f7b95e399074185b1e46a2bc7e5db464a05185a"),
}
ANIMATION_FILE = "ARC3-Inference/inference/utils/animation.py"
GPU_FUNCTIONS = (
    "normalize_frames", "collapse_frames", "_transient_cells",
    "summarize_animation", "_animation_chain",
)


def _checked_notebook(kind: str, path: str | Path | None = None) -> tuple[dict, str]:
    filename, expected = PINNED[kind]
    raw = (Path(path) if path is not None else NOTEBOOKS / filename).read_bytes()
    actual = hashlib.sha256(raw).hexdigest()
    if actual != expected:
        raise ValueError(f"Pinned {kind} notebook SHA-256 differs: {actual}")
    return json.loads(raw), actual


def _one_cell(notebook: dict, prefix: str) -> str:
    found = []
    for cell in notebook["cells"]:
        if cell.get("cell_type") != "code":
            continue
        source = cell.get("source", "")
        source = "".join(source) if isinstance(source, list) else source
        if source.startswith(prefix):
            found.append(source)
    if len(found) != 1:
        raise ValueError("Expected exactly one pinned code cell: " + prefix)
    return found[0]


def _cpu_module(notebook: dict) -> str:
    cell = _one_cell(notebook, "%%writefile /tmp/my_agent.py\n")
    tree = ast.parse(cell.split("\n", 1)[1])
    values = []
    for node in tree.body:
        if (isinstance(node, ast.Assign)
                and any(isinstance(target, ast.Name) and target.id == "_SOURCES"
                        for target in node.targets)):
            values.append(ast.literal_eval(node.value))
    if len(values) != 1 or not isinstance(values[0], dict):
        raise ValueError("Expected one literal CPU source bundle")
    return values[0]["agent.py"]


def _gpu_patch(notebook: dict) -> str:
    cell = _one_cell(notebook, "%%writefile /kaggle/harness-changes.patch\n")
    return cell.split("\n", 1)[1]


def _new_file_source(patch: str, path: str) -> str:
    marker = f"diff --git a/{path} b/{path}\n"
    if patch.count(marker) != 1:
        raise ValueError("Expected exactly one complete animation source")
    section = patch.split(marker, 1)[1].split("\ndiff --git ", 1)[0]
    if "--- /dev/null\n" not in section:
        raise ValueError("Animation file is not a complete added source")
    return "\n".join(line[1:] for line in section.splitlines()
                     if line.startswith("+") and not line.startswith("+++")) + "\n"


def _added_function(patch: str, name: str) -> str:
    lines = patch.splitlines()
    starts = [index for index, line in enumerate(lines)
              if line.startswith(f"+def {name}(")]
    if len(starts) != 1:
        raise ValueError("Expected exactly one added function: " + name)
    result = []
    for line in lines[starts[0]:]:
        if not line.startswith("+") or line.startswith("+++"):
            break
        if result and line.startswith("+def "):
            break
        result.append(line[1:])
    source = "\n".join(result)
    tree = ast.parse(source)
    if len(tree.body) != 1 or not isinstance(tree.body[0], ast.FunctionDef):
        raise ValueError("Expected one complete added function body")
    return source


def _compile_selected(nodes: list[ast.stmt], namespace: dict, label: str) -> None:
    # Postponed annotations avoid importing the game engine just for type names.
    future = ast.ImportFrom(module="__future__", names=[ast.alias(name="annotations")], level=0)
    module = ast.fix_missing_locations(ast.Module(body=[future, *nodes], type_ignores=[]))
    exec(compile(module, label, "exec"), namespace)


def load_cpu_observation(path: str | Path | None = None):
    """Return the exact deployed CPU Observation class, without importing its policy."""
    import numpy as np

    notebook, _ = _checked_notebook("cpu", path)
    module = ast.parse(_cpu_module(notebook))
    nodes = [node for node in module.body
             if isinstance(node, ast.ClassDef) and node.name == "Observation"]
    if len(nodes) != 1:
        raise ValueError("Expected exactly one CPU Observation class")
    namespace = {"__name__": __name__, "dataclass": dataclass, "hashlib": hashlib, "np": np}
    _compile_selected(nodes, namespace, "pinned_cpu_notebook::agent.Observation")
    return namespace["Observation"]


def load_gpu_observation_functions(path: str | Path | None = None) -> dict[str, Any]:
    """Return named, exact deployed pure GPU animation functions."""
    notebook, _ = _checked_notebook("gpu", path)
    patch = _gpu_patch(notebook)
    animation = ast.parse(_new_file_source(patch, ANIMATION_FILE))
    names = set(GPU_FUNCTIONS) - {"_animation_chain"}
    nodes = [node for node in animation.body
             if isinstance(node, ast.FunctionDef) and node.name in names]
    if {node.name for node in nodes} != names:
        raise ValueError("Missing expected deployed animation functions")
    nodes += ast.parse(_added_function(patch, "_animation_chain")).body
    namespace = {"Any": Any, "Sequence": Sequence, "defaultdict": defaultdict}
    _compile_selected(nodes, namespace, "pinned_gpu_notebook::animation_functions")
    return {name: namespace[name] for name in GPU_FUNCTIONS}


def source_report() -> dict:
    """Hash-checked source provenance; no full-runtime validation is claimed."""
    cpu, cpu_hash = _checked_notebook("cpu")
    gpu, gpu_hash = _checked_notebook("gpu")
    patch = _gpu_patch(gpu)
    sources = {
        "cpu_agent_py": _cpu_module(cpu),
        "gpu_animation_py": _new_file_source(patch, ANIMATION_FILE),
        "gpu_animation_chain": _added_function(patch, "_animation_chain"),
    }
    return {
        "repository": "Sumuji-zkdwn/kb-ndtjm",
        "source_commit": SOURCE_COMMIT,
        "notebooks": {
            kind: {"path": "experiments/arc3/cycle/notebooks/" + PINNED[kind][0],
                   "sha256": digest}
            for kind, digest in (("cpu", cpu_hash), ("gpu", gpu_hash))
        },
        "extracted_source_sha256": {
            name: hashlib.sha256(source.encode("utf-8")).hexdigest()
            for name, source in sources.items()
        },
        "tested_production_code": ["CPU agent.Observation.from_frame", "CPU agent.Observation.key",
                                   *["GPU " + name for name in GPU_FUNCTIONS]],
        "execution_scope": "Only named AST-extracted pure observation code; no notebook cells executed",
        "full_gpu_runtime_test": "NOT_RUN",
        "official_submission": "NOT_RUN",
        "game_performance_improvement": "NOT_MEASURED",
    }
