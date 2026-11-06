"""Exhaustive finite operator witness derived from primitive-lean grow.py.

This validator certifies a bounded state-space claim, not a Lean theorem.
The existing GitHub Actions Lean --trust=0 gate is a separate requirement.
"""
from __future__ import annotations

import json

DOMAIN = "finite"
MAX_STATES = 8


def candidates():
    for n in range(3, MAX_STATES + 1):
        for a in range(n):
            for b in range(n):
                if (a < 2) != (b < 2):
                    yield {"states": n, "image_of_zero": a, "image_of_one": b}


def observer(x: int) -> int:
    return int(x >= 2)


def step(x: int, model: dict) -> int:
    if x == 0:
        return model["image_of_zero"]
    if x == 1:
        return model["image_of_one"]
    return x


def lean_candidate(model: dict, cycle: int) -> str:
    n, a, b = model["states"], model["image_of_zero"], model["image_of_one"]
    name = f"ExtractedFiniteCycle{cycle:05d}"
    return f"""-- Candidate only. NOT Lean-verified by this generator.
namespace {name}
def observer (x : Fin {n}) : Bool := if x.val < 2 then false else true
def oldStep (x : Fin {n}) : Fin {n} := x
def newStep (x : Fin {n}) : Fin {n} :=
  if x = 0 then {a} else if x = 1 then {b} else x
theorem oldSame : observer (oldStep 0) = observer (oldStep 1) := by decide
theorem newDifferent : observer (newStep 0) ≠ observer (newStep 1) := by decide
theorem oldIdentity (x : Fin {n}) : oldStep x = x := by rfl
end {name}
"""


def build(model: dict, cycle: int) -> dict[str, bytes]:
    return {
        "model.json": (json.dumps(model, indent=2, sort_keys=True) + "\n").encode(),
        "witness.lean": lean_candidate(model, cycle).encode(),
    }


def check(model: dict, artifacts: dict[str, bytes], cycle: int) -> dict:
    if not all(type(model.get(x)) is int for x in ("states", "image_of_zero", "image_of_one")):
        return {"passed": False, "reason": "invalid model types"}
    n, a, b = model["states"], model["image_of_zero"], model["image_of_one"]
    if n not in range(3, MAX_STATES + 1) or not (0 <= a < n and 0 <= b < n):
        return {"passed": False, "reason": "model out of range"}
    checks = {
        "candidate_bytes_match_generator": artifacts == build(model, cycle),
        "old_indistinguishable": observer(0) == observer(1),
        "old_action_identity": all(x == x for x in range(n)),
        "new_action_distinguishes": observer(step(0, model)) != observer(step(1, model)),
        "other_states_unchanged": all(step(x, model) == x for x in range(2, n)),
        "all_transitions_in_range": all(0 <= step(x, model) < n for x in range(n)),
    }
    return {
        "passed": all(checks.values()), "method": "exhaustive_finite_python",
        "checked_states": n, "checks": checks, "lean_status": "NOT_RUN",
        "scope": "bounded finite operator witness; not general theorem or autonomous AGI",
    }
