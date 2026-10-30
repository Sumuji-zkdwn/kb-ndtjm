"""Reject unsafe operand substitution and stale measurement-record reuse."""
import unittest

from eea_quotient_dqi import backward_live_step, bit_mask, match_template, match_variants, template_variants


class TemplateTest(unittest.TestCase):
    def test_injective_renaming_with_quantum_and_classical_namespaces(self):
        old = [(0x31, [0, 1, 2]), (0x50, [2, 0]), (0xa0, [0, 1, 0])]
        new = [(6, []), (0x31, [11, 12, 13]), (0x50, [13, 49140]), (0xa0, [11, 12, 49140])]
        self.assertEqual(match_template(old, new), ({0: 11, 1: 12, 2: 13}, {0: 49140}))

    def test_aliased_control_target_rejected(self):
        with self.assertRaisesRegex(ValueError, 'aliased'):
            match_template([(0x31, [0, 1, 2])], [(0x31, [4, 5, 4])])

    def test_inconsistent_mapping_and_changed_gate_rejected(self):
        with self.assertRaisesRegex(ValueError, 'inconsistent'):
            match_template([(0x21, [0, 1]), (0x21, [0, 2])],
                           [(0x21, [4, 5]), (0x21, [6, 7])])
        with self.assertRaisesRegex(ValueError, 'opcode'):
            match_template([(0x21, [0, 1])], [(0x20, [4, 5])])

    def test_only_proved_first_parity_initialization_is_optional(self):
        variants = template_variants([(0x50, [0, 0]), (0xc2, [12, 0]), (0xa0, [1, 2, 12])])
        valid = [(0x50, [11, 49140]), (0x40, [49152]), (0xc2, [49152, 49140]),
                 (0xa0, [12, 13, 49152])]
        self.assertEqual(match_variants(variants, valid)[0], 'reused_parity')
        invalid = valid[:1] + valid[2:3] + valid[1:2] + valid[3:]
        with self.assertRaisesRegex(ValueError, 'neither'):
            match_variants(variants, invalid)


class MeasurementLivenessTest(unittest.TestCase):
    def scan(self, events):
        live, stack = 0, []
        for op, target, condition in reversed(events):
            live = backward_live_step(op, target, condition, live, stack)
        self.assertFalse(stack)
        return live

    def test_unconditional_overwrite_kills_old_record(self):
        self.assertEqual(self.scan([(0x50, 49140, None), (0xa0, None, 49140)]), 0)

    def test_conditional_overwrite_does_not_kill_skipped_path(self):
        events = [(0x81, None, 49153), (0x50, 49140, None), (0x01, None, None),
                  (0xa0, None, 49140)]
        self.assertEqual(self.scan(events), bit_mask(49140))

    def test_read_after_overwrite_within_same_branch_is_safe(self):
        events = [(0x81, None, 49153), (0x50, 49140, None), (0xa0, None, 49140),
                  (0x01, None, None)]
        self.assertEqual(self.scan(events), 0)

    def test_conditional_assignment_and_read_modify_write_preserve_liveness(self):
        self.assertEqual(self.scan([(0xc0, 49140, 49153), (0xa0, None, 49140)]), bit_mask(49140))
        self.assertEqual(self.scan([(0xc2, 49140, 49141)]), bit_mask(49140) | bit_mask(49141))


if __name__ == '__main__':
    unittest.main()
