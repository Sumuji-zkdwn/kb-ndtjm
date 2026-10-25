"""Reject substitutions that break the proved pure 36-wire interface."""
import unittest

from multiply42_dqi import match_product


class ProductMappingTest(unittest.TestCase):
    def setUp(self):
        self.template = [(0x31, [q, q+12, q+24]) for q in range(12)]
        self.mapping = list(range(100, 136))[::-1]
        self.actual = [(op, [self.mapping[q] for q in v]) for op, v in self.template]

    def test_arbitrary_injective_mapping_and_metadata(self):
        self.assertEqual(match_product(self.template, [(6, [])] + self.actual), self.mapping)

    def test_alias_missing_gate_and_changed_phase_gate_are_rejected(self):
        alias = [(op, [100 if q == 101 else q for q in v]) for op, v in self.actual]
        phase = [(0x30, self.actual[0][1])] + self.actual[1:]
        for broken in (alias, self.actual[:-1], phase):
            with self.subTest(broken=broken[:1]), self.assertRaises(ValueError):
                match_product(self.template, broken)

    def test_classical_instruction_or_condition_is_rejected(self):
        for broken in (self.actual + [(0x40, [0])],
                       [(0xb1, self.actual[0][1] + [0])] + self.actual[1:]):
            with self.subTest(broken=broken[:1]), self.assertRaises(ValueError):
                match_product(self.template, broken)

    def test_incomplete_contract_is_rejected_even_when_both_sides_match(self):
        with self.assertRaisesRegex(ValueError, '36 distinct'):
            match_product(self.template[:-1], self.actual[:-1])


if __name__ == '__main__':
    unittest.main()
