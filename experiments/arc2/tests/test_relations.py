import time
import unittest

import numpy as np

from arc2.relations import relation_rules


class RelationRulesTests(unittest.TestCase):
    def test_infers_new_interior_color_without_recoloring_boundary(self):
        x = [[0,0,0,0,0],[0,3,3,3,0],[0,3,0,3,0],[0,3,3,3,0],[0,0,0,0,0]]
        y = np.array(x); y[2,2] = 4
        rules = relation_rules([{'input':x,'output':y.tolist()}])
        rule = next(r for r in rules if r.name == 'relation:enclosed:zero:4:all:to4')
        unseen = np.zeros((6,7),dtype=int)
        unseen[1:5,1:6] = 3; unseen[2:4,2:5] = 0
        wanted = unseen.copy(); wanted[2:4,2:5] = 4
        np.testing.assert_array_equal(rule.fn(unseen),wanted)
        self.assertTrue(np.all(rule.fn(unseen)[unseen==3] == 3))

    def test_diagonal_opening_distinguishes_connectivity(self):
        x = [[0,3,3],[3,0,3],[3,3,3]]
        y = [[0,3,3],[3,4,3],[3,3,3]]
        rules = relation_rules([{'input':x,'output':y}])
        self.assertTrue(any(':enclosed:zero:4:' in r.name for r in rules))
        self.assertFalse(any(':enclosed:zero:8:' in r.name for r in rules))

    def test_unenclosed_background_is_preserved(self):
        x = [[0,0,0,0,0],[0,2,2,2,0],[0,2,0,2,0],[0,2,2,2,0],[0,0,0,0,0]]
        y = np.array(x); y[2,2] = 5
        rule = next(r for r in relation_rules([{'input':x,'output':y}])
                    if r.name == 'relation:enclosed:zero:4:all:to5')
        open_grid = np.array(x); open_grid[1,2] = 0
        self.assertIsNone(rule.fn(open_grid))

    def test_relative_motion_generalizes_to_a_different_anchor_position(self):
        pairs = []
        for height,width,anchor_col,object_row,anchor_row in [(7,9,6,1,3),(8,10,7,2,5)]:
            x = np.zeros((height,width),dtype=int)
            x[object_row:object_row+2,1] = 2
            x[anchor_row:anchor_row+2,anchor_col] = 8
            # An unrelated third-color marker must remain untouched.
            x[0,0] = 5
            y = x.copy(); y[y==2] = 0
            y[anchor_row:anchor_row+2,anchor_col-1] = 2
            pairs.append({'input':x,'output':y})
        rules = relation_rules(pairs)
        candidates = [r for r in rules if ':translate:zero:2:anchor8:' in r.name]
        self.assertTrue(candidates)
        unseen = np.zeros((9,11),dtype=int)
        unseen[1:3,1] = 2; unseen[6:8,9] = 8; unseen[0,0] = 5
        wanted = unseen.copy(); wanted[wanted==2] = 0; wanted[6:8,8] = 2
        self.assertTrue(any(np.array_equal(r.fn(unseen),wanted) for r in candidates))
        self.assertTrue(all(r.fn(unseen) is None or r.fn(unseen)[0,0] == 5 for r in candidates))

    def test_conflicting_examples_do_not_create_a_hole_fill_rule(self):
        x = [[3,3,3],[3,0,3],[3,3,3]]
        a = [[3,3,3],[3,4,3],[3,3,3]]
        b = [[3,3,3],[3,5,3],[3,3,3]]
        rules = relation_rules([{'input':x,'output':a},{'input':x,'output':b}])
        self.assertEqual(rules,[])

    def test_expired_deadline_returns_empty(self):
        self.assertEqual(relation_rules([{'input':[[0]],'output':[[1]]}],
                                       deadline=time.monotonic()-1),[])


if __name__ == '__main__':
    unittest.main()
