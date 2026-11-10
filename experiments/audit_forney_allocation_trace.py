"""Independently replay the pinned PR #8 allocation ledger, without DQI generation.

The gzip is data, not executable code. Every event must have internally
consistent live/free/peak counters, and the precise scalar5 peak is fixed.
"""
from collections import Counter
from pathlib import Path
import gzip
import hashlib
import json

ROOT = Path(__file__).resolve().parents[1]
TRACE = ROOT / "checkpoints/bm-blindcoop-allocations-20261027.json.gz"
EXPECTED_SHA256 = "b3e1da07973a999798a4558f4fdbc386a9f0a34fcbd14591dfe02361b5768d97"
EXPECTED_OWNERS = {
    "syn": 840, "stk": 665, "bb": 444, "sig": 432,
    "held": 23, "forney": 78,
}


def audit():
    packed = TRACE.read_bytes()
    digest = hashlib.sha256(packed).hexdigest()
    if digest != EXPECTED_SHA256:
        raise AssertionError(("source ledger hash changed", digest))
    events = json.loads(gzip.decompress(packed))
    if len(events) != 6257:
        raise AssertionError(("event count", len(events)))
    action_counts = Counter()
    live = {}
    next_id = 0
    max_live = 0
    last_op = -1
    peak = None
    peak_owners = None
    for i, event in enumerate(events):
        action = event["action"]
        wires = event["wires"]
        action_counts[action] += 1
        if event["op_index"] < last_op:
            raise AssertionError(("nonmonotone operation index", i))
        last_op = event["op_index"]
        if len(wires) != len(set(wires)):
            raise AssertionError(("duplicate wires in event", i))
        if action == "allocate":
            for q in wires:
                if q in live:
                    raise AssertionError(("double allocation", i, q))
                if q < next_id:
                    raise AssertionError(("fresh allocation reused old index", i, q))
                live[q] = None
                next_id = q + 1
        elif action == "reclaim":
            for q in wires:
                if q in live or q >= next_id:
                    raise AssertionError(("invalid reclaim", i, q))
                live[q] = event["owner"]
        elif action == "claim":
            for q in wires:
                if q not in live:
                    raise AssertionError(("claim on non-live wire", i, q))
                live[q] = event["owner"]
        elif action == "release":
            for q in wires:
                if q not in live:
                    raise AssertionError(("release on non-live wire", i, q))
                live[q] = None
        elif action == "recycle":
            for q in wires:
                if q not in live:
                    raise AssertionError(("double recycle", i, q))
                del live[q]
        elif action not in ("phase_enter", "phase_exit"):
            raise AssertionError(("unexpected allocation action", action))
        max_live = max(max_live, len(live))
        expected = (next_id, len(live), next_id - len(live), max_live)
        observed = (event["qubits"], event["live"],
                    event["free"], event["peak_live"])
        if observed != expected:
            raise AssertionError(("counter mismatch", i, observed, expected))
        if event["live"] == 2482 and peak is None:
            peak = (i, event["op_index"])
        if i == 5212:
            peak_owners = Counter(v for v in live.values())
    if peak != (5211, 13971812):
        raise AssertionError(("wrong peak position", peak))
    if dict(peak_owners) != EXPECTED_OWNERS:
        raise AssertionError(("wrong peak ownership", peak_owners))
    if len(live) != 840 or max_live != 2482 or next_id != 2482:
        raise AssertionError(("unexpected final allocator state", len(live), max_live, next_id))
    result = {
        "status": "PASS",
        "source_sha256": digest,
        "events": len(events),
        "peak_live": max_live,
        "peak_event": peak[0],
        "peak_op_index": peak[1],
        "pre_forney_live": 2404,
        "forney_new_allocation": 78,
        "borrowed_held_pivots": 3,
        "peak_owners": dict(peak_owners),
        "action_counts": dict(action_counts),
        "final_live": len(live),
        "scope": "allocator invariants and ownership only; not a quantum correctness proof",
    }
    print(json.dumps(result, indent=2))
    return result


if __name__ == "__main__":
    audit()
