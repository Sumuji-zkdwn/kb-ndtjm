"""Scalar phase integration: exact branch phases and pinned PR7 comparison."""
import copy
import json
import math
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'research/bm_port'))
from trace_phase5 import TracePhase5
from trace_phase5_probe import verify
from dqi_gate import sha, reuse_comparison_checkpoint, BM_TRACE3_CHECKPOINT_SHA


class ScalarTraceTest(unittest.TestCase):
    def test_exact_phase_composition_real_emitter_and_negative_mutations(self):
        report = verify(TracePhase5())
        self.assertEqual(report['status'], 'PASS')
        self.assertEqual(report['new_Toffoli_like_per_point'], 68)
        self.assertEqual(report['scalar']['negative_deleted_phase_gates_rejected'], 8)
        self.assertEqual(report['middle']['coefficient_comparisons'], 82944)
        self.assertEqual(report['middle']['independent_measurement_variables'], 54)
        self.assertEqual(report['candidate_total_operations'], 5629)
        # The production support modules emit the exact locally sealed candidate.
        self.assertEqual(report['circuit_sha256'],
                         '114437811d7887bcce8a4a6664744dd06af2bd9462a09f9d0442e70b1743094d')

    def test_pr7_comparison_is_pinned_and_changed_reference_is_rejected(self):
        checkpoint = ROOT / 'checkpoints/bm-tracephase3-20261027.json'
        self.assertEqual(sha(checkpoint), BM_TRACE3_CHECKPOINT_SHA)
        report = json.loads(checkpoint.read_text())['gates']['full-package']
        reference = copy.deepcopy(report['candidate'])
        verifier_hash = report['full']['verifier_sha256']
        verifier = SimpleNamespace(DEFAULT_NUM_SHOTS=102400, DEFAULT_LOG2_DELTA=-128.0,
            clopper_pearson_upper_bound=lambda k,n,d: -math.expm1(d*math.log(2)/n)+k/n,
            repetition_overhead=lambda e: math.log(2)/-math.log(0.5+2*math.sqrt(e)))
        with patch('dqi_gate.sha', side_effect=[BM_TRACE3_CHECKPOINT_SHA, verifier_hash]):
            result = reuse_comparison_checkpoint(checkpoint, reference, 'unused', verifier)
        self.assertEqual(result['cost'], 5282883023272.201)
        self.assertEqual(result['toffoli_count'], 719881)
        reference['candidate_sha256'] = '0' * 64
        with self.assertRaises(ValueError), patch('dqi_gate.sha', side_effect=[BM_TRACE3_CHECKPOINT_SHA, verifier_hash]):
            reuse_comparison_checkpoint(checkpoint, reference, 'unused', verifier)


if __name__ == '__main__':
    unittest.main()
