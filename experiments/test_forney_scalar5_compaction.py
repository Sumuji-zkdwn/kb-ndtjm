"""Local-only checks for opt-in Forney workspace packing.

No full DQI verifier, Kickmix full-circuit parse, or Kaggle submission.
"""
from pathlib import Path
import json
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "research/bm_port"))
sys.path.insert(0, str(ROOT / "research/eea_boolean"))
sys.path.insert(0, str(ROOT / "quantum"))

from build_dqi import forney_workspace
from trace_phase import scalar5_unused_work_positions
from trace_phase5 import TracePhase5
from trace_phase5_probe import verify


class FakeBuilder:
    """The peak's exact live size and 3 held borrowable pivot IDs."""
    def __init__(self):
        self.live = set(range(2404))
        self.owners = {q: "held" for q in (860, 861, 862)}
        self.nq = 2404
        self.peak_live = 2404
    def qubits(self, n):
        allocated = list(range(self.nq, self.nq + n))
        self.nq += n
        self.live.update(allocated)
        self.peak_live = max(self.peak_live, len(self.live))
        return allocated
    def claim(self, name, qs):
        for q in qs:
            assert q in self.live and q not in self.owners
            self.owners[q] = name
    def release_recycle(self, name, qs):
        for q in qs:
            assert self.owners[q] == name
            del self.owners[q]
            self.live.remove(q)


class WorkspaceCompaction(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.phase = TracePhase5()
        cls.omitted = scalar5_unused_work_positions(cls.phase)

    def test_exact_emitter_reads_no_omitted_slot(self):
        p = self.phase
        blocks = [p.forward, p.erase] + [
            ops for ops in p.middle_steps() if ops is not None
        ]
        touched = {q for ops in blocks for _, qs, _ in ops for q in qs}
        omitted_canonical = {12 + (work_index - 36) for work_index in self.omitted
                             if 36 <= work_index <= 68}
        self.assertFalse(touched & omitted_canonical)
        self.assertIn(80, self.omitted)
        # Five removed physical allocations is the expected current hypothesis;
        # a changed compiler that uses these wires must fail this regression.
        self.assertEqual(self.omitted, (65, 66, 67, 68, 80))

    def test_default_allocation_is_unchanged(self):
        b = FakeBuilder()
        with forney_workspace(b, (860, 861, 862)) as work:
            self.assertEqual(work, list(range(2404, 2482)) + [860, 861, 862])
            self.assertEqual(b.peak_live, 2482)
        self.assertEqual(len(b.live), 2404)

    def test_compaction_bijection_and_restored_owners(self):
        b = FakeBuilder()
        held_owners = {q: b.owners[q] for q in (860, 861, 862)}
        with forney_workspace(b, (860, 861, 862),
                              omit_positions=self.omitted) as work:
            self.assertEqual(len(work), 81)
            self.assertEqual([i for i, q in enumerate(work) if q is None],
                             list(self.omitted))
            physical = [q for q in work if q is not None]
            self.assertEqual(len(physical), len(set(physical)))
            self.assertEqual(set(physical) & set(held_owners), set(held_owners))
            self.assertEqual(b.peak_live, 2477)
            mapping = work[12:24] + work[36:69] + work[24:36] + [work[79]]
            self.assertEqual(len(mapping), 58)
            for ops in [self.phase.forward, self.phase.erase] + [
                part for part in self.phase.middle_steps() if part is not None
            ]:
                for _, operands, _ in ops:
                    for q in operands:
                        self.assertLess(q, len(mapping))
                        self.assertIsNotNone(mapping[q])
        self.assertEqual(len(b.live), 2404)
        self.assertEqual({q: b.owners[q] for q in held_owners}, held_owners)

    def test_unsafe_omission_is_rejected(self):
        for invalid in ((-1,), (81,), (1, 1), ("41",)):
            with self.subTest(invalid=invalid):
                with self.assertRaises(ValueError):
                    with forney_workspace(FakeBuilder(), (860, 861, 862),
                                          omit_positions=invalid):
                        pass

    def test_existing_local_phase_proof_unchanged(self):
        result = verify(self.phase)
        self.assertEqual(result["status"], "PASS")
        self.assertEqual(result["new_Toffoli_like_per_point"], 68)

    @classmethod
    def tearDownClass(cls):
        print(json.dumps({"candidate_omitted_slots": list(cls.omitted),
                          "baseline_qubits": 2482,
                          "projected_compact_qubits": 2482 - len(cls.omitted),
                          "scope": "local register-bijection plus existing exact phase proof; no full DQI verifier"}))


if __name__ == "__main__":
    unittest.main()
