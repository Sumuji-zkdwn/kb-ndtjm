"""Independent checks of information boundaries and search bookkeeping."""
import copy
import unittest

import numpy as np

from arc2.solver import SolverConfig, State, _apply, _color_maps, _rank_outputs, solve_task, state_key
from arc2.types import Rule


class SolverReviewTests(unittest.TestCase):
    def test_state_equivalence_includes_test_inputs_and_grid_shape(self):
        train = np.array([[1,0],[0,1]], dtype=np.uint8)
        test = np.array([[1,2],[3,4]], dtype=np.uint8)
        self.assertNotEqual(state_key((train,test)), state_key((train,test.T)))
        self.assertNotEqual(state_key((np.array([[1,2]]),)),
                            state_key((np.array([[1],[2]]),)))

    def test_different_test_predictions_survive_identical_training_behavior(self):
        task = {'train':[{'input':[[1,0],[0,1]], 'output':[[1,0],[0,1]]}],
                'test':[{'input':[[1,2],[3,4]]}]}
        result = solve_task(task, SolverConfig(time_limit=10, max_depth=1, max_states=1000))
        self.assertGreater(result['diagnostics']['unique_exact_training_predictions'], 1)
        prediction = result['attempts'][0]
        self.assertNotEqual(prediction['attempt_1'], prediction['attempt_2'])

    def test_public_test_answer_field_is_never_read(self):
        task = {'train':[{'input':[[0,1],[0,0]], 'output':[[0,2],[0,0]]}],
                'test':[{'input':[[0,1,0],[0,0,0]]}]}
        poisoned = copy.deepcopy(task)
        # An invalid output is stronger than an ordinary wrong label: parsing
        # it would fail the grid validator, while correct inference ignores it.
        poisoned['test'][0]['output'] = 'DO NOT READ THIS TEST ANSWER'
        config = SolverConfig(time_limit=10, max_depth=1, max_states=1000)
        a, b = solve_task(task, config), solve_task(poisoned, config)
        self.assertEqual(a['attempts'], b['attempts'])
        self.assertFalse(b['diagnostics']['test_output_access'])

    def test_foreground_generalization_retains_a_separate_test_prediction(self):
        train = np.array([[0,1]], dtype=np.uint8)
        test = np.array([[0,7]], dtype=np.uint8)
        target = np.array([[0,2]], dtype=np.uint8)
        rules = _color_maps((train,test), (target,))
        self.assertEqual(len(rules), 2)
        self.assertTrue(all(np.array_equal(r.fn(train), target) for r in rules))
        self.assertNotEqual(rules[0].fn(test).tolist(), rules[1].fn(test).tolist())

    def test_rule_cannot_mutate_shared_search_inputs(self):
        source = np.array([[1]], dtype=np.uint8)
        source.flags.writeable = False
        def bad_rule(grid):
            grid[0,0] = 9
            return grid
        errors = {}
        self.assertIsNone(_apply(Rule('attempted_mutation',bad_rule), (source,), errors))
        self.assertEqual(source.tolist(), [[1]])
        self.assertTrue(any('ValueError' in s for s in errors))

    def test_terminal_recolors_obey_the_state_budget(self):
        task = {'train':[{'input':[[0,1]], 'output':[[0,2]]}],
                'test':[{'input':[[0,7]]}]}
        result = solve_task(task, SolverConfig(time_limit=10, max_states=2, max_depth=1))
        self.assertLessEqual(result['diagnostics']['generated_states'], 2)

    def test_weak_partial_votes_do_not_override_exact_evidence(self):
        target = np.array([[1]], dtype=np.uint8)
        output_a = np.array([[2]], dtype=np.uint8)
        output_b = np.array([[3]], dtype=np.uint8)
        exact_a = State((target,output_a), ('complex',), ('object',), 4.0, 1.0, True)
        exact_b = State((target,output_b), ('simple',), ('geometry',), 1.0, 1.0, True)
        partial = State((np.array([[0]]),output_a), ('partial',), ('identity',), 0.0, .2, False)
        ranked = _rank_outputs([exact_a,exact_b,partial], 1)
        np.testing.assert_array_equal(ranked[0][2], output_b)


if __name__ == '__main__':
    unittest.main()
