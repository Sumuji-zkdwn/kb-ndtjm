"""Bounded, feedback-guided mutations of the existing observation-only CPU policy.

No model API, game identifiers, environment source, or human baselines are used
by the proposal generator. All changes are made in derived notebook copies.
"""
from __future__ import annotations

import ast
import copy
import hashlib
import json
import re

SPACE = {
    "stagnation": (24, 48, 64, 96, 128, 192),
    "repeat_visits": (1, 2, 3, 4, 6),
    "failure_penalty": (0, 1, 2, 3, 4, 6),
    "base_priority_levels": (1, 2, 3, 4),
}
PATTERNS = {
    "stagnation": ("experiment_coverage_c8.py", r"(self\.stagnation >= )(\d+)"),
    "repeat_visits": ("experiment_coverage_c8.py", r"(self\.visits\[key\] >= )(\d+)"),
    "failure_penalty": ("experiment_coverage_c8.py", r"(- )(\d+)( \* failure)"),
    "base_priority_levels": ("experiment_coverage_guarded.py", r"(self\.stats\['level_gains_under_base'\]>=)(\d+)"),
}


def unpack(notebook):
    entries = []
    for index, cell in enumerate(notebook["cells"]):
        src = cell.get("source", "")
        src = "".join(src) if isinstance(src, list) else src
        if cell["cell_type"] == "code" and src.startswith("%%writefile /tmp/my_agent.py\n"):
            payload = src.split("\n", 1)[1]
            assignments = [node for node in ast.parse(payload).body if isinstance(node, ast.Assign)
                           and any(isinstance(t, ast.Name) and t.id == "_SOURCES" for t in node.targets)]
            if len(assignments) != 1:
                raise ValueError("Expected exactly one literal _SOURCES assignment")
            assignment = assignments[0]
            modules = ast.literal_eval(assignment.value)
            if not isinstance(modules, dict) or not all(isinstance(k, str) and isinstance(v, str) for k, v in modules.items()):
                raise ValueError("Invalid bundled modules")
            entries.append((index, payload, assignment, modules))
    if len(entries) != 1:
        raise ValueError("Expected exactly one packaged CPU agent")
    return entries[0]


def parameters(notebook):
    modules = unpack(notebook)[3]
    result = {}
    for key, (module, pattern) in PATTERNS.items():
        matches = list(re.finditer(pattern, modules[module]))
        if len(matches) != 1:
            raise ValueError("Unsupported or ambiguous policy parameter: " + key)
        value = int(matches[0].group(2))
        if value not in SPACE[key]:
            raise ValueError("Parameter outside bounded search space: " + key)
        result[key] = value
    return result


def signature(params):
    return json.dumps(params, sort_keys=True, separators=(",", ":"))


def derive(notebook, params):
    if set(params) != set(SPACE) or any(type(v) is not int or v not in SPACE[k] for k, v in params.items()):
        raise ValueError("Parameters outside the declared policy search space")
    result = copy.deepcopy(notebook)
    index, payload, assignment, modules = unpack(result)
    for key, (module, pattern) in PATTERNS.items():
        matches = list(re.finditer(pattern, modules[module]))
        if len(matches) != 1:
            raise ValueError("Mutation anchor changed: " + key)
        hit = matches[0]
        modules[module] = modules[module][:hit.start(2)] + str(params[key]) + modules[module][hit.end(2):]
    for name, source in modules.items():
        compile(source, name, "exec")
    literal = ast.get_source_segment(payload, assignment.value)
    if payload.count(literal) != 1:
        raise ValueError("Ambiguous source literal")
    payload = payload.replace(literal, repr(modules), 1)
    namespace = "arc_auto_" + hashlib.sha256(signature(params).encode()).hexdigest()[:20]
    payload, count = re.subn(r'(Path\(tempfile\.gettempdir\(\)\) / )"[a-zA-Z0-9_]+"',
                            lambda m: m.group(1) + repr(namespace), payload)
    if count != 1:
        raise ValueError("Expected one isolated module directory")
    compile(payload, "derived_agent.py", "exec")
    result["cells"][index]["source"] = "%%writefile /tmp/my_agent.py\n" + payload
    return result


def propose(incumbent, tried, summary):
    """Choose untried one-coordinate neighbours, ordered by measured symptoms.

    Failed/no-progress scenes prioritise earlier exploration. Frequent game-over
    transitions instead prioritise more cautious actions. Rejected neighbours are
    never repeated; after an adoption the neighbourhood moves with the incumbent.
    """
    tried = set(tried)
    failure_rate = summary.get("failure_rate", 0)
    if failure_rate > 0.04:
        order = [("failure_penalty", 1), ("stagnation", -1), ("repeat_visits", -1), ("base_priority_levels", 1)]
        symptom = "Frequent GAME_OVER transitions: test stronger failure avoidance first."
    else:
        order = [("stagnation", -1), ("repeat_visits", -1), ("base_priority_levels", 1), ("failure_penalty", -1)]
        symptom = "Limited progress: test earlier exploration and broader coverage first."
    for direction in (1, -1):
        for key, preferred in order:
            values = SPACE[key]
            offset = values.index(incumbent[key]) + preferred * direction
            if not 0 <= offset < len(values):
                continue
            candidate = {**incumbent, key: values[offset]}
            if signature(candidate) in tried:
                continue
            return {"parameters": candidate, "changed": key, "before": incumbent[key],
                    "after": values[offset], "hypothesis": symptom,
                    "method": "feedback-guided finite coordinate search"}
    return None
