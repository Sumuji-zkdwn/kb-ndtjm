"""Regression checks for errors that would silently corrupt the DQI phase."""
import unittest
from wfs_dqi_single_site import MASK, RHS, SCRATCH_Q, prove, replacement


class IntegrationProofTest(unittest.TestCase):
    def test_adapted_kernel_has_exact_product_phase(self):
        self.assertTrue(prove(replacement())["ANF_exact"])

    def test_reversing_mask_endianness_is_rejected(self):
        bad = [(op, [MASK[-1-MASK.index(x)] if op == 0xa1 and i == 2 else x
                     for i,x in enumerate(vals)]) for op, vals in replacement()]
        with self.assertRaisesRegex(AssertionError, "phase"):
            prove(bad)

    def test_missing_frobenius_adapter_is_rejected(self):
        # This is the tempting but wrong direct UV^2 -> UV embedding.
        from wfs_dqi_single_site import linear_sqrt
        front, back = linear_sqrt()
        ops = replacement()
        bad = ops[len(front):-len(back)-1]+[ops[-1]]
        with self.assertRaisesRegex(AssertionError, "phase"):
            prove(bad)

    def test_omitted_uncompute_is_rejected(self):
        bad = replacement()
        index = next(i for i,(op,vals) in enumerate(bad) if op == 0xa1 and vals[1] == SCRATCH_Q)
        bad = bad[:index]+bad[index+1:]
        with self.assertRaises(AssertionError):
            prove(bad)


if __name__ == "__main__":
    unittest.main()
