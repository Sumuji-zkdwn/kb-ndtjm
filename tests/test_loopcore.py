"""The private repo tests both portable adapters and real local WFS source."""
import json
from pathlib import Path
import tempfile
import unittest

from loopcore.adapters import finite, wfs
from loopcore.engine import audit, run_one


class PortableOperatorLoopTests(unittest.TestCase):
    def test_all_84_finite_witnesses(self):
        for i, model in enumerate(finite.candidates(), 1):
            self.assertTrue(finite.check(model, finite.build(model, i), i)["passed"])
        self.assertEqual(len(list(finite.candidates())), 84)

    def test_wfs_three_reference_kernels(self):
        for i, (model, expected) in enumerate(zip(wfs.candidates(), (432, 520, 522)), 1):
            files = wfs.build(model, i)
            report = wfs.check(model, files, i)
            self.assertTrue(report["passed"], msg=str(report))
            self.assertEqual(report["total_ops"], expected)
            self.assertEqual(report["op_counts"]["CCZ"], 12)
            self.assertEqual(report["op_counts"]["CX_IF"], 288)
            self.assertEqual(report["official_dqi_verifier"], "NOT_RUN")

    def test_three_persistent_feedback_cycles_and_stop(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for i in range(3):
                self.assertEqual(run_one(root, "wfs")["cycle"], i + 1)
            self.assertEqual(run_one(root, "wfs")["status"], "exhausted")
            self.assertTrue(audit(root, "wfs", rerun_checks=True)["passed"])
            ledger = json.loads((root / "ledger.json").read_text())
            self.assertEqual(ledger["cycles"][1]["previous_sha256"],
                             ledger["cycles"][0]["record_sha256"])

    def test_tamper_blocks_future_validation(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            run_one(root, "wfs")
            victim = root / "cycles" / "00001" / "kernel.kmx"
            victim.write_bytes(victim.read_bytes() + b"# corrupt\n")
            with self.assertRaisesRegex(ValueError, "hash mismatch"):
                audit(root, "wfs")
            with self.assertRaisesRegex(ValueError, "hash mismatch"):
                run_one(root, "wfs")

    def test_modified_gate_rejected(self):
        model = next(wfs.candidates())
        files = wfs.build(model, 1)
        files["kernel.kmx"] = files["kernel.kmx"].replace(b"CCZ", b"CX")
        self.assertFalse(wfs.check(model, files, 1)["passed"])


if __name__ == "__main__":
    unittest.main()
