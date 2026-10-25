import unittest

import numpy as np

from mul45_dqi import encoded, match_arrays
from probe import certify, compile_ops, decomposition, reference_ops


class MultiplierContractTest(unittest.TestCase):
    def test_arbitrary_target_and_both_inputs_match_reference(self):
        terms, _ = decomposition()
        self.assertEqual(certify(compile_ops(terms))['status'], 'PASS')
        self.assertEqual(certify(reference_ops())['status'], 'PASS')

    def test_missing_nonlinear_term_is_rejected(self):
        operations = compile_ops(decomposition()[0])
        del operations[next(i for i, (name, _) in enumerate(operations) if name == 'CCX')]
        with self.assertRaises(AssertionError):
            certify(operations)

    def test_measurement_or_phase_gate_is_not_accepted_as_unitary_certificate(self):
        with self.assertRaises(ValueError):
            certify([('Z', [0])])


class ActualOperandMatchingTest(unittest.TestCase):
    def setUp(self):
        self.data, self.arrays = encoded(reference_ops())
        self.mapping = np.asarray(list(range(100, 136))[::-1], dtype='<u4')
        self.actual = {p: self.mapping[v] for p, v in self.arrays.items()}
        self.ops = np.frombuffer(self.data[1], dtype='u1').copy()

    def test_permuted_actual_wires_and_info_tags(self):
        ops = np.r_[np.uint8(6), self.ops, np.uint8(6)]
        np.testing.assert_array_equal(match_arrays(ops, self.actual, self.data, self.arrays), self.mapping)

    def test_consistently_aliased_wire_is_rejected(self):
        actual = {p: np.where(v == self.mapping[0], self.mapping[1], v) for p, v in self.actual.items()}
        with self.assertRaises(AssertionError):
            match_arrays(self.ops, actual, self.data, self.arrays)

    def test_changed_instruction_or_operand_is_rejected(self):
        ops = self.ops.copy()
        ops[0] ^= 1
        with self.assertRaises(AssertionError):
            match_arrays(ops, self.actual, self.data, self.arrays)
        actual = {p: v.copy() for p, v in self.actual.items()}
        actual[2][0] += 100
        with self.assertRaises(AssertionError):
            match_arrays(self.ops, actual, self.data, self.arrays)


if __name__ == '__main__':
    unittest.main()
