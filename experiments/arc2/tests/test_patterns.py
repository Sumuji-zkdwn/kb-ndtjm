import time
import unittest

import numpy as np

from arc2.patterns import pattern_rules


def pair(x, y):
    return {"input": np.asarray(x).tolist(), "output": np.asarray(y).tolist()}


class PatternRuleTests(unittest.TestCase):
    def assert_family_predicts(self, rules, family, x, expected):
        candidates = [r for r in rules if r.family == family]
        self.assertTrue(candidates, f"No {family} candidates: {[r.name for r in rules]}")
        self.assertTrue(
            any(np.array_equal(r.fn(np.asarray(x, dtype=np.int16)), expected) for r in candidates),
            f"No {family} rule generalized to the unseen example",
        )

    def test_symmetry_restoration_on_new_content(self):
        train = [
            pair([[1, 2, 9], [3, 4, 9]], [[1, 2, 1], [3, 4, 3]]),
            pair([[5, 0, 9], [6, 8, 9]], [[5, 0, 5], [6, 8, 6]]),
        ]
        rules = pattern_rules(train)
        self.assert_family_predicts(rules, "symmetry", [[7, 6, 9], [8, 2, 9]], [[7, 6, 7], [8, 2, 8]])

    def test_period_restoration_across_grid_sizes(self):
        def corrupt(h, w, tile, holes):
            y = np.tile(tile, (h // 2, w // 2))
            x = y.copy()
            for r, c in holes:
                x[r, c] = 9
            return x, y

        a, b = corrupt(4, 6, [[1, 2], [3, 4]], [(0, 0), (1, 3), (2, 2)])
        c, d = corrupt(6, 4, [[4, 5], [2, 6]], [(0, 1), (2, 1), (3, 2)])
        rules = pattern_rules([pair(a, b), pair(c, d)])
        x, y = corrupt(6, 8, [[6, 7], [3, 2]], [(0, 0), (3, 4), (4, 5)])
        self.assert_family_predicts(rules, "periodic", x, y)

    def test_boolean_panel_rule_with_separator(self):
        def task(a, b):
            a, b = np.asarray(a), np.asarray(b)
            x = np.concatenate([a, np.full((a.shape[0], 1), 8), b], axis=1)
            y = np.where((a != 0) ^ (b != 0), 3, 0)
            return x, y

        a, b = task([[1, 0], [1, 0]], [[0, 2], [2, 0]])
        c, d = task([[0, 1], [1, 0]], [[2, 0], [2, 0]])
        rules = pattern_rules([pair(a, b), pair(c, d)])
        x, y = task([[1, 1, 0], [0, 1, 1]], [[2, 0, 2], [0, 2, 0]])
        self.assert_family_predicts(rules, "panels", x, y)

    def test_local_neighbor_rule_generalizes(self):
        def target(x):
            x = np.asarray(x)
            y = x.copy()
            for r in range(x.shape[0]):
                for c in range(x.shape[1]):
                    n = sum(
                        0 <= r + dr < x.shape[0]
                        and 0 <= c + dc < x.shape[1]
                        and x[r + dr, c + dc] != 0
                        for dr, dc in ((-1, 0), (1, 0), (0, -1), (0, 1))
                    )
                    if x[r, c] == 1 and n == 2:
                        y[r, c] = 2
            return y

        a = [[0, 1, 0, 0], [1, 1, 1, 0], [0, 1, 1, 1], [0, 0, 0, 0]]
        b = [[1, 1, 0, 0], [1, 1, 0, 1], [0, 0, 0, 1], [0, 1, 1, 1]]
        c = [[0, 0, 0, 0, 0], [0, 1, 1, 1, 0], [0, 1, 0, 1, 0], [0, 1, 1, 1, 0]]
        rules = pattern_rules([pair(a, target(a)), pair(b, target(b))])
        self.assert_family_predicts(rules, "local", c, target(c))

    def test_line_connections_preserve_other_colors(self):
        train = [
            pair([[0, 1, 0, 1, 0], [2, 0, 0, 0, 0]], [[0, 1, 1, 1, 0], [2, 0, 0, 0, 0]]),
            pair([[3, 0, 0, 0, 0], [1, 0, 0, 0, 1]], [[3, 0, 0, 0, 0], [1, 1, 1, 1, 1]]),
        ]
        rules = pattern_rules(train)
        x = [[0, 1, 0, 4, 0, 1, 0], [2, 0, 0, 0, 0, 0, 0]]
        y = [[0, 1, 1, 4, 1, 1, 0], [2, 0, 0, 0, 0, 0, 0]]
        self.assert_family_predicts(rules, "lines", x, y)

    def test_all_candidates_fit_and_do_not_modify_training(self):
        train = [pair([[1, 0], [0, 1]], [[2, 0], [0, 2]]), pair([[0, 1]], [[0, 2]])]
        before = repr(train)
        rules = pattern_rules(train)
        self.assertTrue(rules)
        for rule in rules:
            for example in train:
                x = np.asarray(example["input"], dtype=np.int16)
                original = x.copy()
                self.assertTrue(np.array_equal(rule.fn(x), example["output"]))
                self.assertTrue(np.array_equal(x, original))
        self.assertEqual(repr(train), before)

    def test_expired_deadline_returns_without_work(self):
        train = [pair([[1]], [[2]])]
        started = time.monotonic()
        self.assertEqual(pattern_rules(train, deadline=started - 1), [])
        self.assertLess(time.monotonic() - started, 0.1)


if __name__ == "__main__":
    unittest.main()
