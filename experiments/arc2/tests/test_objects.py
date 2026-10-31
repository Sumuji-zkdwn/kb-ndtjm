import time
import unittest

import numpy as np

from arc2.objects import object_rules


class ObjectRulesTests(unittest.TestCase):
    def rules_for(self, examples):
        return {r.name: r for r in object_rules(examples)}

    def test_largest_component_crop_preserves_internal_holes(self):
        grid = np.array([[0,0,0,0,0,0], [0,2,2,2,0,4],
                         [0,2,0,2,0,0], [0,2,2,2,0,0]])
        rules = self.rules_for([{'input': grid.tolist(), 'output': [[2,2,2],[2,0,2],[2,2,2]]}])
        rule = rules['objects:zero:4:mono1:crop:largest']
        np.testing.assert_array_equal(rule.fn(grid), [[2,2,2],[2,0,2],[2,2,2]])

    def test_ambiguous_largest_component_is_not_silently_tiebroken(self):
        grid = np.array([[2,2,0,3,3]])
        rules = self.rules_for([{'input': grid.tolist(), 'output': grid.tolist()}])
        self.assertIsNone(rules['objects:zero:4:mono1:crop:largest'].fn(grid))

    def test_hole_fill_preserves_a_different_colored_marker(self):
        grid = np.array([[0,0,0,0,0], [0,2,2,2,0], [0,2,0,2,0],
                         [0,2,3,2,0], [0,2,2,2,0], [0,0,0,0,0]])
        wanted = grid.copy(); wanted[2,2] = 2
        rules = self.rules_for([{'input': grid.tolist(), 'output': wanted.tolist()}])
        out = rules['objects:zero:4:fill_holes'].fn(grid)
        np.testing.assert_array_equal(out, wanted)
        self.assertEqual(out[3,2], 3)

    def test_object_gravity_keeps_shape_and_stacks_on_obstacles(self):
        grid = np.array([[0,2,2,0], [0,2,0,0], [0,0,0,0], [0,3,3,0], [0,3,3,0]])
        wanted = np.array([[0,0,0,0], [0,2,2,0], [0,2,0,0], [0,3,3,0], [0,3,3,0]])
        rules = self.rules_for([{'input': grid.tolist(), 'output': wanted.tolist()}])
        np.testing.assert_array_equal(
            rules['objects:zero:object_gravity:down:mono1'].fn(grid), wanted)
        np.testing.assert_array_equal(grid[0], [0,2,2,0])

    def test_recolor_by_relative_size_transfers_to_unseen_sizes_and_colors(self):
        a = [[0,1,0,1,1,0], [0,0,0,0,0,0]]
        b = [[0,7,0,7,7,0], [0,0,0,0,0,0]]
        out = [[0,3,0,2,2,0], [0,0,0,0,0,0]]
        rules = self.rules_for([{'input':a, 'output':out}, {'input':b, 'output':out}])
        rule = rules['objects:zero:4:recolor:area_rank']
        unseen = np.array([[0,4,4,0,6,6,6,0],[0,0,0,0,0,0,0,0]])
        expected = [[0,3,3,0,2,2,2,0],[0,0,0,0,0,0,0,0]]
        np.testing.assert_array_equal(rule.fn(unseen), expected)

    def test_conflicting_recolor_mapping_is_rejected(self):
        x = [[0,1,0,1,0], [0,0,0,0,0]]
        y = [[0,2,0,3,0], [0,0,0,0,0]]
        rules = self.rules_for([{'input': x, 'output': y}])
        self.assertNotIn('objects:zero:4:recolor:area', rules)
        self.assertNotIn('objects:zero:4:recolor:color', rules)

    def test_template_is_copied_using_its_unique_anchor_color(self):
        grid = np.zeros((5,8), dtype=int)
        grid[1,1] = 3; grid[1,2] = 2; grid[2,1] = 2
        grid[1,5] = 3
        wanted = grid.copy(); wanted[1,6] = 2; wanted[2,5] = 2
        rules = self.rules_for([{'input': grid.tolist(), 'output': wanted.tolist()}])
        np.testing.assert_array_equal(rules['objects:zero:4:stamp_template'].fn(grid), wanted)

    def test_expired_budget_returns_without_learning(self):
        self.assertEqual(object_rules([{'input': [[1]], 'output': [[2]]}],
                                      deadline=time.monotonic()-1), [])

    def test_repeated_shape_selection_keeps_the_unique_repeated_group(self):
        grid = np.array([[0,2,2,0,3,3,0,4,0], [0,0,0,0,0,0,0,4,4]])
        rules = self.rules_for([{'input':grid.tolist(), 'output':[[2,2,0,3,3]]}])
        out = rules['objects:zero:4:mono1:crop:repeated_shape'].fn(grid)
        np.testing.assert_array_equal(out, [[2,2,0,3,3]])

    def test_fixed_and_inferred_background_hypotheses_both_survive(self):
        grid = [[0,0,0], [0,2,0], [0,0,0]]
        rules = self.rules_for([{'input':grid, 'output':[[2]]}])
        fixed = rules['objects:zero:4:mono1:crop:largest']
        inferred = rules['objects:mode:4:mono1:crop:largest']
        shifted_bg = np.array([[8,8,8], [8,2,8], [8,8,8]])
        self.assertNotEqual(fixed.fn(shifted_bg).tolist(), inferred.fn(shifted_bg).tolist())


if __name__ == '__main__':
    unittest.main()
