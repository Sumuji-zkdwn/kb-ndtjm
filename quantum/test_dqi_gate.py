"""Prevent smoke budgets that cannot pass even with a perfect circuit."""
import math
import copy
import json
from pathlib import Path
from types import SimpleNamespace
import unittest

from dqi_gate import smoke_shot_count, validate_comparison_measurement, reuse_comparison_checkpoint, validate_full_batch


class SmokeConfidenceTest(unittest.TestCase):
    def verifier(self, maximum=102400):
        # Official zero-error Clopper-Pearson formula, verifier SHA f14274bc...194e65.
        return SimpleNamespace(DEFAULT_BATCH_SIZE=256, DEFAULT_NUM_SHOTS=maximum,
            DEFAULT_LOG2_DELTA=-128.0,
            clopper_pearson_upper_bound=lambda k,n,d: -math.expm1(d*math.log(2)/n))

    def test_minimum_valid_budget_without_relaxing_confidence(self):
        v = self.verifier()
        self.assertGreaterEqual(v.clopper_pearson_upper_bound(0,512,-128),1/16)
        n = smoke_shot_count(v)
        self.assertEqual(n,1536)
        self.assertLess(v.clopper_pearson_upper_bound(0,n,-128),1/16)
        self.assertGreaterEqual(v.clopper_pearson_upper_bound(0,n-256,-128),1/16)
        self.assertEqual(v.DEFAULT_LOG2_DELTA,-128)

    def test_insufficient_official_budget_is_rejected(self):
        with self.assertRaisesRegex(ValueError,"confidence"):
            smoke_shot_count(self.verifier(maximum=1280))

    def test_full_batch_preserves_exact_official_sample_count(self):
        validate_full_batch(self.verifier(),1024)
        for invalid in (0,-1,1536,True):
            with self.subTest(invalid=invalid),self.assertRaises(ValueError):
                validate_full_batch(self.verifier(),invalid)


class ComparisonEvidenceTest(unittest.TestCase):
    def setUp(self):
        path=Path(__file__).resolve().parents[1]/'checkpoints/eea-quotient-full-package-20261026.json'
        self.report=json.loads(path.read_text())['all_site_gates']['gates']['full-package']
        self.reference=copy.deepcopy(self.report['candidate'])
        self.verifier_sha=self.report['full']['verifier_sha256']
        self.verifier=SimpleNamespace(DEFAULT_NUM_SHOTS=102400,DEFAULT_LOG2_DELTA=-128.0,
            clopper_pearson_upper_bound=lambda k,n,d: -math.expm1(d*math.log(2)/n)+k/n,
            repetition_overhead=lambda e: math.log(2)/-math.log(0.5+2*math.sqrt(e)))

    def check(self):
        return validate_comparison_measurement(self.report,self.reference,self.verifier,self.verifier_sha)

    def test_recorded_reference_measurement_is_consistent(self):
        self.assertEqual(self.check()['cost'],19143921722159.74)

    def test_reference_bytes_header_or_verifier_hash_mismatch(self):
        for key,value in [('candidate_sha256','wrong'),('candidate_bytes',1),('dqi',{})]:
            with self.subTest(key=key):
                original=self.reference[key];self.reference[key]=value
                with self.assertRaisesRegex(ValueError,'reference'): self.check()
                self.reference[key]=original
        self.verifier_sha='wrong'
        with self.assertRaisesRegex(ValueError,'configuration'): self.check()

    def test_shots_seed_confidence_workers_or_status_mismatch(self):
        for key,value in [('num_shots',1536),('seed',9),('log2_delta',-64),('max_workers',2),('status','FAIL')]:
            with self.subTest(key=key):
                original=self.report['full'][key];self.report['full'][key]=value
                with self.assertRaises(ValueError): self.check()
                self.report['full'][key]=original
        self.report['status']='FAIL'
        with self.assertRaisesRegex(ValueError,'passed'): self.check()

    def test_tampered_nonfinite_cost_bound_or_count_is_rejected(self):
        for key,value in [('cost',1),('cost',math.nan),('effective_error_rate',0),
                          ('toffoli_count',math.inf),('value_errors',-1),('phase_errors',True)]:
            with self.subTest(key=key,value=value):
                original=self.report['full'][key];self.report['full'][key]=value
                with self.assertRaises(ValueError): self.check()
                self.report['full'][key]=original

    def test_value_and_phase_errors_are_added(self):
        full=self.report['full'];full['value_errors']=1;full['phase_errors']=2
        bound=self.verifier.clopper_pearson_upper_bound(3,102400,-128)
        full['effective_error_rate']=bound
        full['cost']=self.verifier.repetition_overhead(bound)*1893**2*full['toffoli_count']
        self.check()

    def test_unpinned_checkpoint_is_rejected_before_loading(self):
        with self.assertRaisesRegex(ValueError,'pinned'):
            reuse_comparison_checkpoint(__file__,self.reference,'missing',self.verifier)


if __name__ == '__main__':
    unittest.main()
