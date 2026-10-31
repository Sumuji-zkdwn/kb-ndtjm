"""Offline ARC runner: isolated inference, atomic checkpoints, honest exact scoring.

The evaluator is deliberately outside the solver.  ``test[*].output`` never
crosses the worker boundary.  The initial submission already covers every test
input; a killed, failed, or budget-skipped worker leaves a valid fallback behind.
"""
from __future__ import annotations

import argparse
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
import math
import multiprocessing as mp
import os
from pathlib import Path
import signal
import tempfile
import time
import traceback
from typing import Any, Callable


ATTEMPT_FIELDS = ("attempt_1", "attempt_2")


def validate_grid(grid: Any) -> bool:
    """Validate the serialized competition grid, rejecting bools and floats."""
    return (
        isinstance(grid, list)
        and 1 <= len(grid) <= 30
        and isinstance(grid[0], list)
        and 1 <= len(grid[0]) <= 30
        and all(
            isinstance(row, list)
            and len(row) == len(grid[0])
            and all(type(cell) is int and 0 <= cell <= 9 for cell in row)
            for row in grid
        )
    )


def challenge_for_solver(task: dict[str, Any]) -> dict[str, Any]:
    """Copy only authorized inference fields; ignore all test-answer fields."""
    if not isinstance(task, dict) or not isinstance(task.get("train"), list):
        raise ValueError("Task must contain a train list")
    if not task["train"]:
        raise ValueError("Task must contain at least one training example")
    if not isinstance(task.get("test"), list) or not task["test"]:
        raise ValueError("Task must contain at least one test input")
    result: dict[str, Any] = {"train": [], "test": []}
    for pair in task["train"]:
        if not isinstance(pair, dict) or not all(validate_grid(pair.get(k)) for k in ("input", "output")):
            raise ValueError("Invalid training grid")
        result["train"].append({"input": deepcopy(pair["input"]), "output": deepcopy(pair["output"])})
    for pair in task["test"]:
        if not isinstance(pair, dict) or not validate_grid(pair.get("input")):
            raise ValueError("Invalid test input grid")
        result["test"].append({"input": deepcopy(pair["input"])})
    return result


def fallback_attempts(task: dict[str, Any]) -> list[dict[str, Any]]:
    return [{key: deepcopy(pair["input"]) for key in ATTEMPT_FIELDS} for pair in task["test"]]


def validate_attempts(attempts: Any, expected_count: int) -> bool:
    return (
        isinstance(attempts, list)
        and len(attempts) == expected_count
        and all(
            isinstance(item, dict)
            and set(item) == set(ATTEMPT_FIELDS)
            and all(validate_grid(item[k]) for k in ATTEMPT_FIELDS)
            for item in attempts
        )
    )


def validate_submission(submission: Any, challenges: dict[str, Any]) -> bool:
    return (
        isinstance(submission, dict)
        and set(submission) == set(challenges)
        and all(validate_attempts(submission[k], len(challenges[k]["test"])) for k in challenges)
    )


def atomic_json(path: str | Path, value: Any) -> None:
    """Replace only a complete, flushed JSON document on the same filesystem."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix=path.name + ".", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(value, stream, ensure_ascii=False, separators=(",", ":"), allow_nan=False)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp_name, path)
    finally:
        try:
            os.unlink(temp_name)
        except FileNotFoundError:
            pass


def sha256_file(path: str | Path) -> str:
    h = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for part in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(part)
    return h.hexdigest()


def code_manifest() -> dict[str, str]:
    root = Path(__file__).resolve().parents[1]
    paths = list((root / "arc2").rglob("*.py"))
    if (root / "LICENSE").is_file():
        paths.append(root / "LICENSE")
    vendor = root / "vendor" / "icecuber"
    if vendor.is_dir():
        paths.extend(p for p in vendor.rglob("*") if p.is_file() and (
            p.suffix in {".cpp", ".hpp", ".h", ".cc"}
            or p.name in {"LICENSE", "PROVENANCE.md", "SOURCE_MANIFEST.json"}
        ))
    return {str(p.relative_to(root)): sha256_file(p) for p in sorted(paths)}


def prepare_requested_backend(backend: str, compile_seconds: float = 180.0) -> dict[str, Any]:
    """Prepare the optional compiler once, outside all per-task time budgets."""
    if backend == "python":
        return {"requested": "python", "effective": "python", "status": "disabled"}
    if backend != "hybrid":
        raise ValueError("backend must be python or hybrid")
    try:
        from .cpp_backend import prepare_cpp_backend
        result = prepare_cpp_backend(compile_seconds=compile_seconds)
        if not isinstance(result, dict):
            raise ValueError("Invalid C++ preparation result")
    except Exception as exc:
        result = {"status": "error", "error_type": type(exc).__name__, "error": str(exc)}
    return {**result, "requested": "hybrid", "effective": "hybrid" if result.get("status") == "ready" else "python"}


def _solve_worker(task: dict[str, Any], config: dict[str, Any], result_path: str) -> None:
    # Imported here so runner validation and score computation need no solver.
    try:
        from .solver import SolverConfig, solve_task
        result = solve_task(task, config=SolverConfig(**config))
        atomic_json(result_path, {"ok": True, "result": result})
    except BaseException as exc:
        atomic_json(result_path, {
            "ok": False,
            "error_type": type(exc).__name__,
            "error": str(exc),
            "traceback": traceback.format_exc(limit=8),
        })


def _worker_entry(
    worker_fn: Callable[..., None], task: dict[str, Any], config: dict[str, Any],
    result_path: str, session_path: str,
) -> None:
    """Isolate a POSIX worker and every compiler/solver child in one session."""
    if os.name == "posix":
        try:
            os.setsid()
            identity = {"pid": os.getpid(), "pgid": os.getpgrp(), "sid": os.getsid(0)}
            if not identity["pid"] == identity["pgid"] == identity["sid"]:
                raise RuntimeError("Worker did not become its own process-group leader")
            atomic_json(session_path, identity)
        except Exception as exc:
            # Do not launch external programs without an isolated process group.
            atomic_json(result_path, {"ok": False, "error_type": "SessionIsolationError", "error": str(exc)})
            return
    worker_fn(task, config, result_path)


def _verified_worker_group(process: Any, session_path: Path) -> int | None:
    """Return only a group established by our wrapper with pgid == worker pid.

    The wrapper records the verified identity before invoking solver code.  The
    record also permits cleanup after the leader exits but a descendant remains.
    A currently living PID must still have that same group and session identity.
    """
    if os.name != "posix" or process.pid is None or not session_path.is_file():
        return None
    try:
        identity = json.loads(session_path.read_text(encoding="utf-8"))
        pid = process.pid
        if not identity.get("pid") == identity.get("pgid") == identity.get("sid") == pid:
            return None
        if pid <= 1 or pid == os.getpgrp() or pid == os.getpid():
            return None
        try:
            if os.getpgid(pid) != pid or os.getsid(pid) != pid:
                return None
        except ProcessLookupError:
            # A process group outlives its leader while any child remains in it.
            pass
        return pid
    except (OSError, ValueError, TypeError):
        return None


def _terminate_worker_tree(process: Any, session_path: Path) -> None:
    """Terminate a verified worker group, including SIGTERM-resistant children."""
    group = _verified_worker_group(process, session_path)
    if group is not None:
        try:
            os.killpg(group, signal.SIGTERM)
        except ProcessLookupError:
            return
        process.join(timeout=0.25)
        # The leader may have exited while a compiler/solver child ignored TERM.
        # Always send KILL to this already verified group, not only if the leader
        # is alive. A missing group simply means all descendants already exited.
        try:
            os.killpg(group, signal.SIGKILL)
        except ProcessLookupError:
            pass
        process.join(timeout=0.5)
        return
    if process.is_alive():
        process.terminate()
        process.join(timeout=0.25)
        if process.is_alive():
            process.kill()
            process.join(timeout=0.5)


def run_task_isolated(
    task: dict[str, Any],
    config: dict[str, Any],
    hard_timeout: float,
    *,
    worker_fn: Callable[..., None] | None = None,
) -> dict[str, Any]:
    """Run one task in a spawn worker with a hard wall-clock cap.

    A file rather than a multiprocessing Queue avoids pipe-buffer deadlocks for
    large diagnostics. ``worker_fn`` is an injection point for boundary tests.
    """
    clean_task = challenge_for_solver(task)
    fallback = {"attempts": fallback_attempts(clean_task), "diagnostics": {}}
    if hard_timeout <= 0:
        fallback["diagnostics"] = {"runner_status": "budget_skipped", "wall_seconds": 0.0}
        return fallback
    started = time.monotonic()
    context = mp.get_context("spawn")
    process = None
    tree_cleaned = False
    with tempfile.TemporaryDirectory(prefix="arc2-worker-") as folder:
        result_path = Path(folder) / "result.json"
        session_path = Path(folder) / "worker-session.json"
        try:
            process = context.Process(target=_worker_entry, args=(worker_fn or _solve_worker, clean_task, dict(config), str(result_path), str(session_path)))
            process.start()
            process.join(timeout=max(0.0, hard_timeout - (time.monotonic() - started)))
            if process.is_alive():
                _terminate_worker_tree(process, session_path)
                tree_cleaned = True
                fallback["diagnostics"] = {"runner_status": "hard_timeout"}
                return fallback
            if process.exitcode != 0 or not result_path.is_file():
                fallback["diagnostics"] = {"runner_status": "worker_failed", "exit_code": process.exitcode}
                return fallback
            packet = json.loads(result_path.read_text(encoding="utf-8"))
            if not packet.get("ok"):
                fallback["diagnostics"] = {
                    "runner_status": "solver_error",
                    "error_type": packet.get("error_type"),
                    "error": packet.get("error"),
                }
                return fallback
            result = packet.get("result", {})
            if not isinstance(result, dict) or not validate_attempts(result.get("attempts"), len(clean_task["test"])):
                fallback["diagnostics"] = {"runner_status": "invalid_prediction"}
                return fallback
            diagnostic = result.get("diagnostics", {})
            if not isinstance(diagnostic, dict):
                diagnostic = {}
            result["diagnostics"] = {**diagnostic, "runner_status": "ok", "wall_seconds": time.monotonic() - started}
            return result
        except Exception as exc:
            fallback["diagnostics"] = {"runner_status": "runner_error", "error_type": type(exc).__name__, "error": str(exc)}
            return fallback
        finally:
            if process is not None and process.pid is not None and not tree_cleaned:
                _terminate_worker_tree(process, session_path)
            fallback["diagnostics"]["wall_seconds"] = time.monotonic() - started


def score_submission(submission: dict[str, Any], solutions: dict[str, list[Any]]) -> dict[str, Any]:
    """Official-style per-test-output exact pass@2 plus stricter task metric."""
    if set(submission) != set(solutions):
        raise ValueError("Prediction and solution task IDs differ")
    task_results: dict[str, Any] = {}
    correct_outputs = 0
    total_outputs = 0
    solved_tasks = 0
    for task_id, answers in solutions.items():
        guesses = submission[task_id]
        if not answers or not all(validate_grid(answer) for answer in answers):
            raise ValueError(f"Invalid or missing solution for {task_id}")
        if not validate_attempts(guesses, len(answers)):
            raise ValueError(f"Invalid prediction for {task_id}")
        hits = [any(item[field] == answer for field in ATTEMPT_FIELDS) for item, answer in zip(guesses, answers)]
        first_hits = [item["attempt_1"] == answer for item, answer in zip(guesses, answers)]
        correct_outputs += sum(hits)
        total_outputs += len(hits)
        solved_tasks += int(all(hits))
        task_results[task_id] = {
            "correct_outputs": sum(hits), "total_outputs": len(hits),
            "pass_at_2_by_output": hits, "pass_at_1_by_output": first_hits,
            "all_outputs_solved": all(hits),
        }
    return {
        "correct_outputs": correct_outputs,
        "total_outputs": total_outputs,
        "output_pass_at_2": correct_outputs / total_outputs if total_outputs else 0.0,
        "correct_outputs_attempt_1": sum(sum(t["pass_at_1_by_output"]) for t in task_results.values()),
        "solved_tasks": solved_tasks,
        "total_tasks": len(solutions),
        "task_pass_at_2": solved_tasks / len(solutions) if solutions else 0.0,
        "tasks": task_results,
    }


def run_challenges(
    challenges: dict[str, Any],
    output_path: str | Path,
    *,
    seconds_per_task: float = 5.0,
    total_seconds: float = 39600.0,
    diagnostics_path: str | Path | None = None,
    solver_config: dict[str, Any] | None = None,
    backend_info: dict[str, Any] | None = None,
    hard_timeout_slack: float = 2.0,
    task_runner: Callable[..., dict[str, Any]] = run_task_isolated,
    progress: bool = True,
) -> tuple[dict[str, Any], dict[str, Any]]:
    if not isinstance(challenges, dict) or not challenges or not all(isinstance(k, str) for k in challenges):
        raise ValueError("Challenges must be a nonempty task-ID dictionary")
    if not math.isfinite(seconds_per_task) or seconds_per_task <= 0:
        raise ValueError("seconds_per_task must be positive and finite")
    if not math.isfinite(total_seconds) or total_seconds < 0:
        raise ValueError("total_seconds must be nonnegative and finite")
    if not math.isfinite(hard_timeout_slack) or hard_timeout_slack < 0:
        raise ValueError("hard_timeout_slack must be nonnegative and finite")
    clean = {task_id: challenge_for_solver(task) for task_id, task in challenges.items()}
    submission = {task_id: fallback_attempts(task) for task_id, task in clean.items()}
    config = {"time_limit": seconds_per_task, **(solver_config or {})}
    # The explicit CLI/task budget wins over an accidental config override.
    config["time_limit"] = seconds_per_task
    diagnostic: dict[str, Any] = {
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "solver_config": config,
        "backend": backend_info or {"requested": "python-api", "effective": "unverified" if config.get("use_cpp") else "python", "status": "not_prepared_by_runner" if config.get("use_cpp") else "disabled"},
        "total_seconds_budget": total_seconds,
        "hard_timeout_slack": hard_timeout_slack,
        "code_sha256": code_manifest(),
        "answer_visibility": "test outputs stripped before solver worker",
        "fallback": "identity input copied to both attempts",
        "tasks": {},
    }
    atomic_json(output_path, submission)
    if diagnostics_path is not None:
        atomic_json(diagnostics_path, diagnostic)
    started = time.monotonic()
    deadline = started + total_seconds
    task_ids = sorted(clean)
    for index, task_id in enumerate(task_ids):
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            result = {"attempts": submission[task_id], "diagnostics": {"runner_status": "budget_skipped", "wall_seconds": 0.0}}
        else:
            hard_cap = min(seconds_per_task + hard_timeout_slack, remaining)
            task_config = dict(config)
            task_config["time_limit"] = min(seconds_per_task, max(0.01, hard_cap - min(hard_timeout_slack, hard_cap * 0.25)))
            try:
                result = task_runner(clean[task_id], task_config, hard_cap)
                if not validate_attempts(result.get("attempts"), len(clean[task_id]["test"])):
                    result = {"attempts": submission[task_id], "diagnostics": {"runner_status": "invalid_prediction"}}
            except Exception as exc:
                result = {"attempts": submission[task_id], "diagnostics": {"runner_status": "runner_error", "error": str(exc)}}
        submission[task_id] = result["attempts"]
        diagnostic["tasks"][task_id] = result.get("diagnostics", {})
        diagnostic["completed_tasks"] = index + 1
        diagnostic["wall_seconds"] = time.monotonic() - started
        atomic_json(output_path, submission)
        if diagnostics_path is not None:
            atomic_json(diagnostics_path, diagnostic)
        if progress:
            state = diagnostic["tasks"][task_id].get("runner_status", "unknown")
            print(f"[{index + 1}/{len(task_ids)}] {task_id}: {state}", flush=True)
    if not validate_submission(submission, clean):
        raise RuntimeError("Internal submission schema invariant failed")
    diagnostic["submission_sha256"] = sha256_file(output_path)
    diagnostic["wall_seconds"] = time.monotonic() - started
    if diagnostics_path is not None:
        atomic_json(diagnostics_path, diagnostic)
    return submission, diagnostic


def evaluate_directory(
    tasks_directory: str | Path,
    report_path: str | Path,
    *,
    limit: int | None = None,
    offset: int = 0,
    seconds_per_task: float = 5.0,
    total_seconds: float = 39600.0,
    solver_config: dict[str, Any] | None = None,
    backend_info: dict[str, Any] | None = None,
    progress: bool = True,
) -> dict[str, Any]:
    if offset < 0 or (limit is not None and limit <= 0):
        raise ValueError("offset must be nonnegative; limit must be positive")
    root = Path(tasks_directory)
    paths = sorted(root.glob("*.json"))[offset:]
    if limit is not None:
        paths = paths[:limit]
    if not paths:
        raise ValueError("No task JSON files selected")
    challenges: dict[str, Any] = {}
    solutions: dict[str, list[Any]] = {}
    data_manifest: dict[str, str] = {}
    for path in paths:
        task = json.loads(path.read_text(encoding="utf-8"))
        challenges[path.stem] = challenge_for_solver(task)
        answers = [pair.get("output") for pair in task["test"]]
        if not all(validate_grid(answer) for answer in answers):
            raise ValueError(f"Missing or invalid test answer in {path.name}")
        solutions[path.stem] = answers
        data_manifest[path.name] = sha256_file(path)
    report_path = Path(report_path)
    submission_path = report_path.with_name(report_path.stem + ".submission.json")
    diagnostics_path = report_path.with_name(report_path.stem + ".diagnostics.json")
    submission, diagnostics = run_challenges(
        challenges, submission_path, seconds_per_task=seconds_per_task,
        total_seconds=total_seconds, diagnostics_path=diagnostics_path,
        solver_config=solver_config, backend_info=backend_info, progress=progress,
    )
    report = {
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "dataset_directory": str(root.resolve()),
        "selection": {"ordering": "lexicographic task filename", "offset": offset, "limit": limit},
        "dataset_sha256": data_manifest,
        "solver_config": diagnostics["solver_config"],
        "backend": diagnostics["backend"],
        "code_sha256": diagnostics["code_sha256"],
        "answer_visibility": diagnostics["answer_visibility"],
        "submission_file": submission_path.name,
        "submission_sha256": diagnostics["submission_sha256"],
        "diagnostics_file": diagnostics_path.name,
        "wall_seconds": diagnostics["wall_seconds"],
        "metrics": score_submission(submission, solutions),
    }
    atomic_json(report_path, report)
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Offline ARC-AGI-2 symbolic candidate")
    commands = parser.add_subparsers(dest="command", required=True)
    for name in ("solve", "evaluate"):
        command = commands.add_parser(name)
        command.add_argument("--output", required=True, type=Path)
        command.add_argument("--seconds-per-task", type=float, default=8.0)
        command.add_argument("--total-seconds", type=float, default=39600.0)
        command.add_argument("--max-states", type=int, default=4000)
        command.add_argument("--beam-width", type=int, default=32)
        command.add_argument("--max-depth", type=int, default=3)
        command.add_argument("--backend", choices=("hybrid", "python"), default="hybrid")
        command.add_argument("--cpp-fraction", type=float, default=0.6)
        command.add_argument("--cpp-memory-mb", type=int, default=768)
        command.add_argument("--compile-seconds", type=float, default=180.0)
        command.add_argument("--quiet", action="store_true")
        if name == "solve":
            command.add_argument("--challenges", required=True, type=Path)
            command.add_argument("--diagnostics", type=Path)
        else:
            command.add_argument("--tasks", required=True, type=Path)
            command.add_argument("--limit", type=int)
            command.add_argument("--offset", type=int, default=0)
    args = parser.parse_args(argv)
    if args.max_states <= 0 or args.beam_width <= 0 or args.max_depth < 0:
        parser.error("max-states and beam-width must be positive; max-depth must be nonnegative")
    if not 0 < args.cpp_fraction < 1 or args.cpp_memory_mb < 128 or not math.isfinite(args.compile_seconds) or args.compile_seconds <= 0:
        parser.error("cpp-fraction must be in (0,1), cpp-memory-mb >=128, and compile-seconds positive and finite")
    challenges = None
    if args.command == "solve":
        challenges = json.loads(args.challenges.read_text(encoding="utf-8"))
        if not isinstance(challenges, dict) or not challenges or not all(isinstance(k, str) for k in challenges):
            parser.error("Challenges must be a nonempty task-ID dictionary")
        clean = {task_id: challenge_for_solver(task) for task_id, task in challenges.items()}
        # Preserve a full valid submission even if the job is stopped in compile.
        atomic_json(args.output, {task_id: fallback_attempts(task) for task_id, task in clean.items()})
    backend_info = prepare_requested_backend(args.backend, args.compile_seconds)
    if not args.quiet or backend_info["effective"] != args.backend:
        print("Backend: " + json.dumps(backend_info, ensure_ascii=False), flush=True)
    config = {
        "max_states": args.max_states, "beam_width": args.beam_width, "max_depth": args.max_depth,
        "use_cpp": backend_info["effective"] == "hybrid",
        "cpp_fraction": args.cpp_fraction, "cpp_memory_mb": args.cpp_memory_mb,
    }
    if args.command == "solve":
        run_challenges(
            challenges, args.output, seconds_per_task=args.seconds_per_task,
            total_seconds=args.total_seconds, diagnostics_path=args.diagnostics,
            solver_config=config, backend_info=backend_info, progress=not args.quiet,
        )
    else:
        report = evaluate_directory(
            args.tasks, args.output, limit=args.limit, offset=args.offset,
            seconds_per_task=args.seconds_per_task, total_seconds=args.total_seconds,
            solver_config=config, backend_info=backend_info, progress=not args.quiet,
        )
        metrics = {key: value for key, value in report["metrics"].items() if key != "tasks"}
        print(json.dumps(metrics, ensure_ascii=False, indent=2))
    return 0

