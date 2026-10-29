"""Offline control tests; synthetic outcomes are not gameplay evidence."""
import copy
import gzip
import json
import os
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import evaluate
import loop
import proposal
from evaluate import cycle


class Proposals(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.base = cycle.read(cycle.HERE / "notebooks/cpu-c8b.ipynb")
        cls.params = proposal.parameters(cls.base)

    def test_mutation_changes_only_expected_module_and_retains_adapter(self):
        original = copy.deepcopy(self.base)
        params = {**self.params, "stagnation": 64}
        derived = proposal.derive(self.base, params)
        old, new = proposal.unpack(self.base)[3], proposal.unpack(derived)[3]
        self.assertEqual([n for n in old if old[n] != new[n]], ["experiment_coverage_c8.py"])
        self.assertEqual(new["submission_adapter.py"], old["submission_adapter.py"])
        self.assertEqual(proposal.parameters(derived), params)
        self.assertEqual(self.base, original)
        cycle.validate_notebook(cycle.clean_notebook(derived))

    def test_unknown_or_unsafe_parameter_is_rejected(self):
        for change in ({"stagnation": 0}, {"failure_penalty": True}, {"budget": 99999}):
            with self.subTest(change=change), self.assertRaises(ValueError):
                proposal.derive(self.base, {**self.params, **change})

    def test_feedback_changes_the_first_proposal(self):
        tried = [proposal.signature(self.params)]
        self.assertEqual(proposal.propose(self.params, tried, {"failure_rate": 0})["changed"], "stagnation")
        cautious = proposal.propose(self.params, tried, {"failure_rate": 0.1})
        self.assertEqual(cautious["changed"], "failure_penalty")
        self.assertGreater(cautious["after"], cautious["before"])

    def test_no_repeated_proposal_and_finite_exhaustion(self):
        tried = [proposal.signature(self.params)]
        for _ in range(20):
            choice = proposal.propose(self.params, tried, {})
            if choice is None:
                break
            sig = proposal.signature(choice["parameters"])
            self.assertNotIn(sig, tried)
            tried.append(sig)
        self.assertIsNone(proposal.propose(self.params, tried, {}))


class Boundaries(unittest.TestCase):
    def setUp(self):
        self.config = cycle.read(loop.HERE / "config.json")
        self.row = {"candidate_id": "c", "protocol_id": "p", "game": "a", "seed": 0,
                    "score": 0.0, "levels_completed": 0, "calls": 1200, "failures": 2,
                    "official_loop_unchanged": True, "level_reset_only": True, "win": False}

    def test_zero_is_valid_but_missing_or_duplicate_cases_are_not(self):
        result = evaluate.summarize([self.row], ["a"], [0], "c", "p", 1200)
        self.assertEqual(result["mean_public_rhae"], 0)
        for rows, games in (([], ["a"]), ([self.row], ["a", "b"]), ([self.row, self.row], ["a"])):
            with self.assertRaises(ValueError):
                evaluate.summarize(rows, games, [0], "c", "p", 1200)

    def test_invalid_scores_id_budget_or_reset_are_rejected(self):
        for change in ({"score": float("nan")}, {"score": 101}, {"calls": 1201},
                       {"candidate_id": "other"}, {"protocol_id": "other"},
                       {"level_reset_only": False}, {"official_loop_unchanged": False}):
            with self.subTest(change=change), self.assertRaises(ValueError):
                evaluate.summarize([{**self.row, **change}], ["a"], [0], "c", "p", 1200)

    def test_no_automatic_submission_or_unbounded_budget_config(self):
        for change in ({"official_submission": "auto"}, {"profile": "gpu-baseline"},
                       {"max_candidates": 0}, {"max_candidates": 999999}, {"actions_per_game": 2400},
                       {"seeds": [0, 0]}, {"min_score_gain": float("nan")}):
            with self.subTest(change=change), self.assertRaises(ValueError):
                loop.validate_config({**self.config, **change})

    def test_ties_and_level_regression_are_not_adopted(self):
        base = {"mean_public_rhae": 1.0, "mean_levels_completed": 2}
        self.assertFalse(loop.accepted(base, base, self.config))
        self.assertFalse(loop.accepted({"mean_public_rhae": 2, "mean_levels_completed": 1}, base, self.config))
        self.assertTrue(loop.accepted({"mean_public_rhae": 2, "mean_levels_completed": 2}, base, self.config))

    def test_game_selection_uses_a_fixed_denominator(self):
        available = ["a-123", "b-456"]
        self.assertEqual(evaluate.select_games("all", available), available)
        self.assertEqual(evaluate.select_games(["a"], available), ["a-123"])
        for request in (["unknown"], ["a", "a-123"], []):
            with self.assertRaises(ValueError):
                evaluate.select_games(request, available)

    def test_process_lock_excludes_another_writer(self):
        with tempfile.TemporaryDirectory() as tmp, loop.exclusive_run(Path(tmp)):
            with self.assertRaises(RuntimeError), loop.exclusive_run(Path(tmp)):
                pass

    def test_initial_reset_registers_scoring_then_restores_level_only_mode(self):
        observed = []
        def make(*args, **kwargs):
            observed.append(os.environ["ONLY_RESET_LEVELS"])
            return SimpleNamespace(observation_space=SimpleNamespace(full_reset=True))
        with patch.dict(os.environ, {"ONLY_RESET_LEVELS": "true"}):
            evaluate.make_scored_environment(SimpleNamespace(make=make), "a", 0, "card")
            self.assertEqual(observed, ["false"])
            self.assertEqual(os.environ["ONLY_RESET_LEVELS"], "true")


class CompleteLoop(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / "experiment"
        self.config = {**cycle.read(loop.HERE / "config.json"), "games": "all", "max_candidates": 3, "patience": 3}
        self.inventory = {"games": ["a-123", "b-456"], "files": {}, "provenance": {"scope": "synthetic test"}}
        self.prepare = patch.object(evaluate, "prepare_runtime", return_value=self.inventory)
        self.prepare.start()
        self.addCleanup(self.prepare.stop)
        self.calls = []

    def evaluator(self, scores, fail_at=None, interrupt_at=None):
        def fake(bundle, root, protocol, deadline):
            index = int(bundle.name.rsplit("-", 1)[1])
            self.calls.append(index)
            if index == interrupt_at:
                raise KeyboardInterrupt()
            if index == fail_at:
                raise RuntimeError("Synthetic evaluator failure")
            cid = cycle.verify(bundle)["candidate_id"]
            rows = []
            for game in protocol["games"]:
                case = bundle / "evaluation" / (game + "-s0")
                case.mkdir(parents=True, exist_ok=True)
                with gzip.open(case / "trace.jsonl.gz", "wt") as stream:
                    stream.write('{"synthetic_test_only":true}\n')
                row = {"candidate_id": cid, "protocol_id": protocol["protocol_id"], "game": game, "seed": 0,
                       "score": scores[index], "levels_completed": 1, "calls": 100, "failures": 0,
                       "official_loop_unchanged": True, "level_reset_only": True, "win": False,
                       "trace_sha256": cycle.cycle_file_digest(case / "trace.jsonl.gz")}
                cycle.save(case / "result.json", row)
                cycle.save(case / "scorecard.json", {"scope": "synthetic test only"})
                cycle.save(case / "receipt.json", {"result_sha256": cycle.cycle_file_digest(case / "result.json"),
                           "scorecard_sha256": cycle.cycle_file_digest(case / "scorecard.json")})
                rows.append(row)
            return evaluate.summarize(rows, protocol["games"], protocol["seeds"], cid, protocol["protocol_id"], 1200)
        return fake

    def test_full_loop_adopts_better_rejects_worse_and_exports_best(self):
        state = loop.run(self.config, "unused", self.root, evaluator=self.evaluator([1, 2, 0, 3]))
        self.assertEqual(state["incumbent"], 3)
        self.assertEqual([a["accepted"] for a in state["attempts"]], [True, True, False, True])
        self.assertEqual(state["stop_reason"], "candidate_budget")
        self.assertEqual(cycle.read(self.root / "selected/selection.json")["official_submission"], "manual_only")
        frozen = [cycle.code_hash(cycle.read(self.root / "candidates" / a["label"] / "submission.ipynb")) for a in state["attempts"]]
        self.assertEqual(len(set(frozen)), 4)
        self.calls.clear()
        restored = loop.run(self.config, "unused", self.root, evaluator=self.evaluator([999] * 4))
        self.assertEqual(restored, state)
        self.assertEqual(self.calls, [])

    def test_baseline_failure_stops_without_exporting_unmeasured_candidate(self):
        state = loop.run(self.config, "unused", self.root, evaluator=self.evaluator([0] * 4, fail_at=0))
        self.assertEqual(state["stop_reason"], "baseline_failed")
        self.assertFalse((self.root / "selected").exists())
        self.assertEqual(len(state["attempts"]), 1)

    def test_failed_candidate_keeps_previous_best(self):
        config = {**self.config, "max_candidates": 1}
        state = loop.run(config, "unused", self.root, evaluator=self.evaluator([1, 100], fail_at=1))
        self.assertEqual(state["incumbent"], 0)
        self.assertEqual(state["attempts"][1]["status"], "failed")
        self.assertTrue(cycle.read(self.root / "selected/selection.json")["baseline_retained"])

    def test_plateau_stops_at_patience(self):
        state = loop.run({**self.config, "patience": 1}, "unused", self.root, evaluator=self.evaluator([1] * 4))
        self.assertEqual(state["stop_reason"], "no_improvement")
        self.assertEqual(len(state["attempts"]), 2)

    def test_interruption_resumes_pending_candidate_instead_of_creating_duplicate(self):
        with self.assertRaises(KeyboardInterrupt):
            loop.run(self.config, "unused", self.root, evaluator=self.evaluator([1, 2, 3, 4], interrupt_at=1))
        state = loop.run(self.config, "unused", self.root, evaluator=self.evaluator([1, 2, 3, 4]))
        self.assertEqual(len(state["attempts"]), 4)
        self.assertEqual(self.calls.count(0), 1)
        self.assertEqual(state["incumbent"], 3)

    def test_changed_protocol_refuses_to_reuse_results(self):
        loop.run(self.config, "unused", self.root, evaluator=self.evaluator([1] * 4))
        with self.assertRaisesRegex(ValueError, "changed"):
            loop.run({**self.config, "seeds": [1]}, "unused", self.root)

    def test_modified_result_is_detected_on_resume(self):
        loop.run(self.config, "unused", self.root, evaluator=self.evaluator([1] * 4))
        p = self.root / "candidates/auto-000/evaluation/a-123-s0/result.json"
        cycle.save(p, {**cycle.read(p), "score": 99})
        with self.assertRaisesRegex(ValueError, "bytes changed"):
            loop.run(self.config, "unused", self.root)

    def test_stop_file_prevents_any_candidate(self):
        self.root.mkdir()
        (self.root / "STOP").touch()
        state = loop.run(self.config, "unused", self.root, evaluator=self.evaluator([1] * 4))
        self.assertEqual(state["stop_reason"], "stop_requested")
        self.assertEqual(self.calls, [])


if __name__ == "__main__":
    unittest.main()
