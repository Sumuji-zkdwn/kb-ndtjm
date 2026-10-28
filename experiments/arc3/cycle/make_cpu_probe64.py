"""Derive one bounded CPU experiment while preserving the c8b notebook."""
import ast
import copy
import json
from pathlib import Path
import cycle


def build():
    original = cycle.read(cycle.HERE / "notebooks/cpu-c8b.ipynb")
    candidate = copy.deepcopy(original)
    for cell in candidate["cells"]:
        source = "".join(cell["source"]) if isinstance(cell["source"], list) else cell["source"]
        if cell["cell_type"] != "code" or not source.startswith("%%writefile /tmp/my_agent.py\n"):
            continue
        payload = source.split("\n", 1)[1]
        assignment = next(n for n in ast.parse(payload).body if isinstance(n, ast.Assign)
                          and any(isinstance(t, ast.Name) and t.id == "_SOURCES" for t in n.targets))
        modules = ast.literal_eval(assignment.value)
        name = "experiment_coverage_c8.py"
        before = modules[name]
        assert before.count("self.stagnation >= 96") == 1
        modules[name] = before.replace("self.stagnation >= 96", "self.stagnation >= 64")
        literal = ast.get_source_segment(payload, assignment.value)
        payload = payload.replace(literal, repr(modules), 1)
        # Separate temporary module directory for the derived candidate.
        payload = payload.replace("arc_coverage_c8b_54689f81d3ca89d0", "arc_coverage_probe64_" + cycle.digest(modules[name].encode())[:16])
        cell["source"] = "%%writefile /tmp/my_agent.py\n" + payload
    candidate["cells"].insert(0, {"cell_type": "markdown", "metadata": {}, "id": "probe64-hypothesis",
        "source": "# CPU c8b: earlier coverage probe (64)\nOne policy change: the stagnant-scene intervention threshold is 64 instead of 96 decisions.\nHypothesis: earlier action coverage may reduce repeated ineffective actions on unfamiliar environments.\nThis is an experimental candidate; no hidden-game improvement is claimed. The c8b source is retained.\n"})
    target = cycle.HERE / "notebooks/cpu-c8b-probe64.ipynb"
    cycle.save(target, cycle.clean_notebook(candidate))
    cycle.save(cycle.HERE / "DERIVED_CANDIDATES.json", {"cpu-c8b-probe64": {
        "baseline": "cpu-c8b", "baseline_code_sha256": cycle.code_hash(original),
        "candidate_code_sha256": cycle.code_hash(candidate), "policy_change": {"stagnation_threshold": {"before": 96, "after": 64}},
        "packaging_change": "Unique temporary module directory; algorithm otherwise retained",
        "official_score": None, "status": "candidate, not an adopted improvement"}})
    print(target)


if __name__ == "__main__":
    build()
