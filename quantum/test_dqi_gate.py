"""Prevent smoke budgets that cannot pass even with a perfect circuit."""
import math
from types import SimpleNamespace
import unittest

from dqi_gate import smoke_shot_count


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


if __name__ == '__main__':
    unittest.main()
