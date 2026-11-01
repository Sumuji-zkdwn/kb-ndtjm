"""Offline exact-model regressions; no SDK, network, or game execution."""

from fractions import Fraction as F
import json
import unittest

try:
    from .finite_model import (
        first_mode, mobius, mode_power, reconstruct_adjacent, report, rotate,
        state_space, trace, trace4, wfs2,
    )
except ImportError:  # unittest discover -s this_directory
    from finite_model import (
        first_mode, mobius, mode_power, reconstruct_adjacent, report, rotate,
        state_space, trace, trace4, wfs2,
    )


class FiniteTemporalModelTests(unittest.TestCase):
    def test_nine_state_closure_and_period_dividing_four(self):
        states = state_space()
        self.assertEqual(len(states), 9)
        for state in states:
            with self.subTest(state=state):
                self.assertIn(rotate(state), states)
                self.assertEqual(rotate(rotate(state)), (-state[0], -state[1]))
                self.assertEqual(rotate(rotate(rotate(rotate(state)))), state)
        self.assertEqual(rotate((0, 0)), (0, 0))

    def test_every_state_has_the_exact_ordered_trace(self):
        for x, u in state_space():
            with self.subTest(x=x, u=u):
                self.assertEqual(trace4((x, u)), (x, -u, -x, u))

    def test_full_even_and_last_signature_counts(self):
        traces = [trace4(state) for state in state_space()]
        self.assertEqual(len(set(traces)), 9)
        self.assertEqual(len({values[::2] for values in traces}), 3)
        self.assertEqual(len({values[-1] for values in traces}), 3)

    def test_exact_dft_normalization_and_sign_for_all_states(self):
        for x, u in state_space():
            with self.subTest(x=x, u=u):
                coefficient = first_mode(trace4((x, u)))
                self.assertEqual(coefficient, (x / 2, u / 2))
                self.assertTrue(all(isinstance(value, F) for value in coefficient))
        self.assertEqual(first_mode(trace4((0, 1))), (F(0), F(1, 2)))

    def test_reversing_time_changes_the_imaginary_sign(self):
        values = trace4((F(2, 3), F(3, 5)))
        reversed_values = (values[0], values[3], values[2], values[1])
        real, imag = first_mode(values)
        self.assertEqual(first_mode(reversed_values), (real, -imag))
        self.assertNotEqual(first_mode(reversed_values), first_mode(values))

    def test_two_adjacent_readings_reconstruct_every_toy_state(self):
        for state in state_space():
            with self.subTest(state=state):
                values = trace4(state)
                self.assertEqual(reconstruct_adjacent(*values[:2]), state)
                self.assertEqual(reconstruct_adjacent(*values[1:3]), rotate(state))

    def test_even_observations_hide_the_proved_witness(self):
        first, second = trace4((0, 0)), trace4((0, 1))
        self.assertEqual(first[::2], second[::2])
        self.assertNotEqual(first, second)
        self.assertNotEqual(first_mode(first), first_mode(second))

    def test_last_packet_collision_has_different_next_observation(self):
        first, second = trace((1, 0), 5), trace((-1, 0), 5)
        self.assertEqual(first[:4], (1, 0, -1, 0))
        self.assertEqual(second[:4], (-1, 0, 1, 0))
        self.assertEqual(first[3], second[3])
        self.assertNotEqual(first[:4], second[:4])
        self.assertNotEqual(first[4], second[4])

    def test_power_only_is_a_lossy_negative_control(self):
        states = ((1, 0), (0, 1), (-1, 0), (0, -1))
        coefficients = {first_mode(trace4(state)) for state in states}
        powers = {mode_power(trace4(state)) for state in states}
        self.assertEqual(len(coefficients), 4)
        self.assertEqual(powers, {F(1, 4)})

    def test_positive_rational_coordinate_and_reciprocal_conjugacy(self):
        for intensity in (F(1, 8), F(1, 4), F(1, 2), F(1), F(2), F(3), F(8)):
            with self.subTest(intensity=intensity):
                coordinate = wfs2(intensity)
                self.assertGreater(coordinate, -F(1, 2))
                self.assertEqual(1 + 2 * coordinate, intensity * intensity)
                self.assertEqual(mobius(coordinate), wfs2(1 / intensity))

    def test_mobius_involution_on_rational_domain_points(self):
        # Include points not constructed from a rational square, and near the boundary.
        for coordinate in (F(-499, 1000), F(-1, 3), F(0), F(1, 7), F(3), F(1000)):
            with self.subTest(coordinate=coordinate):
                mapped = mobius(coordinate)
                self.assertGreater(mapped, -F(1, 2))
                self.assertEqual((1 + 2 * coordinate) * (1 + 2 * mapped), 1)
                self.assertEqual(mobius(mapped), coordinate)

    def test_excluded_domain_is_rejected_explicitly(self):
        for coordinate in (-F(1, 2), F(-1), F(-100)):
            with self.subTest(coordinate=coordinate):
                with self.assertRaises(ValueError):
                    mobius(coordinate)
        for intensity in (0, -1, -F(1, 3)):
            with self.subTest(intensity=intensity):
                with self.assertRaises(ValueError):
                    wfs2(intensity)

    def test_inexact_input_and_wrong_trace_length_are_rejected(self):
        with self.assertRaises(TypeError):
            first_mode((0, 0.5, 0, -0.5))
        with self.assertRaises(TypeError):
            mobius(0.0)
        for values in ((), (1, 2), (1, 2, 3, 4, 5)):
            with self.subTest(values=values):
                with self.assertRaises(ValueError):
                    first_mode(values)
        with self.assertRaises(ValueError):
            trace((0, 1), -1)

    def test_report_is_json_friendly_and_limits_its_claims(self):
        result = json.loads(json.dumps(report()))
        self.assertTrue(result["all_checks_passed"])
        self.assertFalse(result["real_game_correspondence_established"])
        self.assertFalse(result["game_performance_improvement_established"])
        self.assertEqual(result["state_count"], 9)
        self.assertEqual(result["signature_counts"], {
            "ordered_four_observations": 9,
            "even_observations": 3,
            "last_observation_only": 3,
        })


if __name__ == "__main__":
    unittest.main()
