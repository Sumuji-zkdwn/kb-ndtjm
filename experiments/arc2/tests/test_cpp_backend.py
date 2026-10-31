import json
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch

from arc2.cpp_backend import (
    VENDOR_DIR, SOURCE_NAMES, _parse_candidates, _run_limited,
    _sanitized_task, prepare_cpp_backend, solve_cpp,
)


def example_task():
    return {
        "id": "DO_NOT_FORWARD",
        "train": [
            {"input": [[0, 1, 0], [0, 0, 2]], "output": [[0, 1, 0], [0, 0, 2]]},
            {"input": [[3, 0], [0, 4], [0, 0]], "output": [[3, 0], [0, 4], [0, 0]]},
        ],
        "test": [
            {"input": [[1, 0], [0, 3]], "output": [[9]]},
            {"input": [[0, 2, 0], [4, 0, 0]], "output": [[8]]},
        ],
    }


class CppBackendTests(unittest.TestCase):
    def test_sanitization_excludes_ids_and_test_labels(self):
        class PoisonTest(dict):
            def __getitem__(self, key):
                if key == "output":
                    raise AssertionError("The test label was accessed")
                return super().__getitem__(key)

        task = example_task()
        task["test"] = [PoisonTest(p) for p in task["test"]]
        safe = _sanitized_task(task)
        self.assertEqual(set(safe), {"train", "test"})
        self.assertTrue(all(set(p) == {"input"} for p in safe["test"]))
        self.assertEqual(len(safe["test"]), 2)

    def test_candidate_parser_validates_shape_index_and_fit_count(self):
        with tempfile.TemporaryDirectory() as temp:
            file = Path(temp) / "answer.csv"
            file.write_text("00000000_1\n|01|23| 1.95 2\n|0|12| 1.9 2\n|2| nan 2\n|2| 1.0 7\n")
            self.assertEqual(_parse_candidates(file, 1, 2), [([[0, 1], [2, 3]], 1.95, 2)])
            self.assertEqual(_parse_candidates(file, 0, 2), [])

    def test_backend_is_optional_and_never_compiles_inside_task(self):
        with patch("arc2.cpp_backend.prepare_cpp_backend", return_value={"status": "not_prepared"}) as prep:
            result = solve_cpp(example_task(), seconds=1)
        prep.assert_called_once_with(compile_seconds=0)
        self.assertEqual(result["predictions"], [[], []])
        self.assertEqual(result["diagnostics"]["status"], "not_prepared")

    def test_completed_depth_survives_later_timeouts(self):
        calls = []

        def run(binary, folder, index, depth, seconds, memory):
            payload = json.loads((folder / "dataset/test/00000000.json").read_text())
            self.assertNotIn("id", payload)
            self.assertTrue(all(set(p) == {"input"} for p in payload["test"]))
            calls.append((index, depth))
            if depth == 1:
                (folder / f"output/answer_{index}_{depth}.csv").write_text(f"00000000_{index}\n|1| 1.9 2\n")
            return {"test_index": index, "depth": depth, "status": "complete" if depth == 1 else "timeout"}

        with patch("arc2.cpp_backend.prepare_cpp_backend", return_value={"status": "ready", "binary": "/unused"}):
            with patch("arc2.cpp_backend._run_limited", side_effect=run):
                result = solve_cpp(example_task(), seconds=1)
        self.assertEqual(result["predictions"], [[[[1]]], [[[1]]]])
        self.assertEqual(result["training_exact"], [[True], [True]])
        self.assertEqual(result["train_matches"], [[2], [2]])
        self.assertIn((0, 3), calls)
        self.assertIn((1, 3), calls)

    def test_subprocess_wall_time_is_enforced(self):
        with tempfile.TemporaryDirectory() as temp:
            folder = Path(temp)
            executable = folder / "sleeper"
            executable.write_text("#!/usr/bin/env python3\nimport time\ntime.sleep(30)\n")
            executable.chmod(0o755)
            start = time.monotonic()
            result = _run_limited(str(executable), folder, 0, 1, 0.10, 256)
            self.assertEqual(result["status"], "timeout")
            self.assertLess(time.monotonic() - start, 1.5)

    def test_historical_task_specific_units_are_not_in_build(self):
        self.assertNotIn("tasks.cpp", SOURCE_NAMES)
        self.assertNotIn("evals.cpp", SOURCE_NAMES)
        self.assertFalse((VENDOR_DIR / "src/tasks.cpp").exists())
        self.assertFalse((VENDOR_DIR / "src/evals.cpp").exists())
        self.assertFalse((VENDOR_DIR / "dataset").exists())
        runner = (VENDOR_DIR / "src/runner.cpp").read_text()
        self.assertNotIn("s.test_out", runner)
        self.assertNotIn("cheatSize", runner)

    def test_prepared_binary_solves_identity_with_multiple_test_inputs(self):
        if prepare_cpp_backend(compile_seconds=0)["status"] != "ready":
            self.skipTest("Run prepare_cpp_backend once to enable the compiled integration test")
        task = example_task()
        result = solve_cpp(task, seconds=3.0)
        for i, pair in enumerate(task["test"]):
            self.assertIn(pair["input"], result["predictions"][i], result["diagnostics"])
            j = result["predictions"][i].index(pair["input"])
            self.assertTrue(result["training_exact"][i][j])
        self.assertNotIn([[9]], result["predictions"][0])


if __name__ == "__main__":
    unittest.main()
