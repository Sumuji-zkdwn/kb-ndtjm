"""Boundary tests independent of the search implementation."""
from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest

from arc2.runner import (
    atomic_json, challenge_for_solver, fallback_attempts, run_challenges,
    run_task_isolated, score_submission, validate_attempts, validate_grid,
    validate_submission,
)


def _task():
    return {
        "train": [{"input": [[1, 0], [0, 0]], "output": [[2, 0], [0, 0]]}],
        "test": [{"input": [[1]], "output": [[9]], "untrusted_answer_hint": "must never cross boundary"}],
        "test_solution": [[8]],
    }


def _boundary_worker(task, config, result_path):
    assert set(task) == {"train", "test"}
    assert all(set(pair) == {"input"} for pair in task["test"])
    atomic_json(result_path, {
        "ok": True,
        "result": {
            "attempts": [{"attempt_1": [[3]], "attempt_2": [[4]]} for _ in task["test"]],
            "diagnostics": {"boundary_checked": True},
        },
    })


def _slow_worker(task, config, result_path):
    # A readiness marker proves the child entered the noncooperative loop; the
    # assertion below therefore tests termination, not merely slow spawn startup.
    Path(config["test_ready_path"]).write_text("worker entered infinite loop")
    while True:
        time.sleep(0.1)


def _invalid_worker(task, config, result_path):
    atomic_json(result_path, {"ok": True, "result": {"attempts": [{"attempt_1": [[99]], "attempt_2": [[0]]}]}})


def _descendant_worker(task, config, result_path):
    child_ready = Path(config["test_child_ready_path"])
    child_code = (
        "import pathlib,signal,sys,time; "
        "signal.signal(signal.SIGTERM,signal.SIG_IGN); "
        "pathlib.Path(sys.argv[1]).write_text('ready'); "
        "time.sleep(30)"
    )
    child = subprocess.Popen([sys.executable, "-c", child_code, str(child_ready)])
    deadline = time.monotonic() + 2
    while not child_ready.is_file() and time.monotonic() < deadline:
        time.sleep(0.01)
    atomic_json(config["test_pid_path"], {
        "worker_pid": os.getpid(), "worker_pgid": os.getpgrp(),
        "child_pid": child.pid, "child_pgid": os.getpgid(child.pid),
    })
    if config.get("test_exit_with_descendant"):
        return  # Simulate a broken solver that abandons its external child.
    while True:
        time.sleep(0.1)


def _pid_is_live(pid):
    """Linux zombies have exited; container PID 1 may reap them later."""
    status = Path(f"/proc/{pid}/stat")
    try:
        return status.read_text().split(")", 1)[1].strip().split()[0] not in ("Z", "X")
    except FileNotFoundError:
        return False


def _native_proc_ids():
    # Some executors virtualize syscall PIDs while exposing a host /proc tree.
    # Such a tree cannot establish whether our own descendant is alive.
    try:
        return os.name == "posix" and int(Path("/proc/self/stat").read_text().split()[0]) == os.getpid()
    except (OSError, ValueError):
        return False


class RunnerContractTests(unittest.TestCase):
    def test_serialized_grid_validation(self):
        self.assertTrue(validate_grid([[0, 9], [1, 3]]))
        for bad in ([], [[]], [[0], [0, 1]], [[True]], [[1.0]], [[-1]], [[10]], [[0] * 31], [[0]] * 31, "grid"):
            with self.subTest(bad=bad):
                self.assertFalse(validate_grid(bad))

    def test_answer_fields_never_copied(self):
        task = _task()
        clean = challenge_for_solver(task)
        self.assertEqual(set(clean), {"train", "test"})
        self.assertEqual(clean["test"], [{"input": [[1]]}])
        clean["train"][0]["input"][0][0] = 7
        self.assertEqual(task["train"][0]["input"][0][0], 1)

    def test_every_test_input_has_two_attempt_fields(self):
        task = _task()
        task["test"].append({"input": [[2, 3]]})
        attempts = fallback_attempts(task)
        self.assertTrue(validate_attempts(attempts, 2))
        self.assertEqual(attempts[1]["attempt_2"], [[2, 3]])
        self.assertFalse(validate_attempts(attempts[:1], 2))
        attempts[0]["attempt_3"] = [[0]]
        self.assertFalse(validate_attempts(attempts, 2))

    def test_strict_task_id_coverage(self):
        challenges = {"x": _task()}
        submission = {"x": fallback_attempts(challenges["x"])}
        self.assertTrue(validate_submission(submission, challenges))
        self.assertFalse(validate_submission({}, challenges))
        self.assertFalse(validate_submission({**submission, "extra": submission["x"]}, challenges))

    def test_output_metric_differs_from_whole_task_metric(self):
        submission = {"two": [
            {"attempt_1": [[0]], "attempt_2": [[2]]},
            {"attempt_1": [[0]], "attempt_2": [[0]]},
        ]}
        metrics = score_submission(submission, {"two": [[[2]], [[3]]]})
        self.assertEqual(metrics["correct_outputs"], 1)
        self.assertEqual(metrics["total_outputs"], 2)
        self.assertEqual(metrics["output_pass_at_2"], 0.5)
        self.assertEqual(metrics["correct_outputs_attempt_1"], 0)
        self.assertEqual(metrics["task_pass_at_2"], 0.0)

    def test_zero_budget_still_writes_complete_submission(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "submission.json"
            challenges = {"b": _task(), "a": _task()}
            prediction, diagnostics = run_challenges(challenges, path, total_seconds=0, progress=False)
            self.assertTrue(validate_submission(prediction, challenges))
            self.assertEqual(json.loads(path.read_text()), prediction)
            self.assertTrue(all(x["runner_status"] == "budget_skipped" for x in diagnostics["tasks"].values()))

    def test_checkpoint_exists_before_first_solver_and_survives_failure(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "submission.json"
            challenges = {"a": _task(), "b": _task()}
            calls = []

            def worker(task, config, hard_timeout):
                self.assertTrue(validate_submission(json.loads(path.read_text()), challenges))
                self.assertNotIn("output", task["test"][0])
                calls.append(True)
                if len(calls) == 2:
                    raise RuntimeError("injected worker failure")
                return {"attempts": [{"attempt_1": [[5]], "attempt_2": [[6]]}], "diagnostics": {"runner_status": "ok"}}

            prediction, diagnostics = run_challenges(challenges, path, task_runner=worker, progress=False)
            self.assertEqual(prediction["a"][0]["attempt_1"], [[5]])
            self.assertEqual(prediction["b"][0]["attempt_1"], [[1]])
            self.assertEqual(diagnostics["tasks"]["b"]["runner_status"], "runner_error")
            self.assertTrue(validate_submission(json.loads(path.read_text()), challenges))

    def test_spawn_worker_receives_only_inputs_and_training_pairs(self):
        result = run_task_isolated(_task(), {"time_limit": 0.1}, 5.0, worker_fn=_boundary_worker)
        self.assertEqual(result["diagnostics"]["runner_status"], "ok")
        self.assertTrue(result["diagnostics"]["boundary_checked"])
        self.assertEqual(result["attempts"][0]["attempt_2"], [[4]])

    def test_hard_timeout_preserves_valid_fallback(self):
        with tempfile.TemporaryDirectory() as tmp:
            ready_path = Path(tmp) / "ready.txt"
            start = time.monotonic()
            result = run_task_isolated(_task(), {"time_limit": 0.05, "test_ready_path": str(ready_path)}, 0.75, worker_fn=_slow_worker)
            self.assertLess(time.monotonic() - start, 3.5)
            self.assertTrue(ready_path.is_file(), "Child must reach its infinite loop before termination")
            self.assertEqual(result["diagnostics"]["runner_status"], "hard_timeout")
            self.assertTrue(validate_attempts(result["attempts"], 1))

    def test_invalid_worker_grid_becomes_valid_fallback(self):
        result = run_task_isolated(_task(), {"time_limit": 0.1}, 5.0, worker_fn=_invalid_worker)
        self.assertEqual(result["diagnostics"]["runner_status"], "invalid_prediction")
        self.assertEqual(result["attempts"][0]["attempt_1"], [[1]])

    @unittest.skipUnless(_native_proc_ids(), "Requires native Linux PID-to-/proc correspondence")
    def test_timeout_kills_sigterm_resistant_descendant(self):
        with tempfile.TemporaryDirectory() as tmp:
            pid_path = Path(tmp) / "pids.json"
            ready_path = Path(tmp) / "child-ready.txt"
            config = {"test_pid_path": str(pid_path), "test_child_ready_path": str(ready_path)}
            result = run_task_isolated(_task(), config, 1.0, worker_fn=_descendant_worker)
            self.assertEqual(result["diagnostics"]["runner_status"], "hard_timeout")
            self.assertTrue(ready_path.is_file(), "Child must install its SIGTERM handler")
            identity = json.loads(pid_path.read_text())
            self.assertEqual(identity["worker_pid"], identity["worker_pgid"])
            self.assertEqual(identity["child_pgid"], identity["worker_pid"])
            self.assertNotEqual(identity["worker_pgid"], os.getpgrp())
            deadline = time.monotonic() + 1
            while _pid_is_live(identity["child_pid"]) and time.monotonic() < deadline:
                time.sleep(0.01)
            self.assertFalse(_pid_is_live(identity["child_pid"]), "Timed-out descendant must not remain running")
            self.assertTrue(validate_attempts(result["attempts"], 1))

    @unittest.skipUnless(_native_proc_ids(), "Requires native Linux PID-to-/proc correspondence")
    def test_failed_worker_cleans_child_after_group_leader_exits(self):
        with tempfile.TemporaryDirectory() as tmp:
            pid_path = Path(tmp) / "pids.json"
            ready_path = Path(tmp) / "child-ready.txt"
            config = {"test_pid_path": str(pid_path), "test_child_ready_path": str(ready_path), "test_exit_with_descendant": True}
            result = run_task_isolated(_task(), config, 3.0, worker_fn=_descendant_worker)
            self.assertEqual(result["diagnostics"]["runner_status"], "worker_failed")
            self.assertTrue(ready_path.is_file())
            identity = json.loads(pid_path.read_text())
            deadline = time.monotonic() + 1
            while _pid_is_live(identity["child_pid"]) and time.monotonic() < deadline:
                time.sleep(0.01)
            self.assertFalse(_pid_is_live(identity["child_pid"]), "Abandoned descendant must be cleaned even after leader exit")


if __name__ == "__main__":
    unittest.main()
