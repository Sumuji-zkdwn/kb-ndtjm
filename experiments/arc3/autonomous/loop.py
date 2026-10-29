"""Autonomous, finite public-demo improvement loop; official submission is manual.

Generate -> freeze -> evaluate -> accept/reject -> propose again -> export.
Resume uses the same frozen experiment and retains every attempted candidate.
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager
import json
import math
import os
from pathlib import Path
import platform
import shutil
import subprocess
import sys
import time

import evaluate
from evaluate import cycle
import proposal

HERE = Path(__file__).resolve().parent


def validate_config(config):
    required = {"schema_version", "profile", "games", "seeds", "actions_per_game", "max_candidates", "patience",
                "max_wall_seconds", "seconds_per_game", "min_score_gain", "max_mean_level_regression", "official_submission"}
    if set(config) != required or config["schema_version"] != 1:
        raise ValueError("Unknown/missing configuration fields")
    if config["profile"] != "cpu-c8b" or config["official_submission"] != "manual_only":
        raise ValueError("This autonomous runner supports CPU public demos with manual official submission only")
    for key, lower, upper in (("actions_per_game", 1200, 1200), ("max_candidates", 1, 32), ("patience", 1, 32),
                              ("max_wall_seconds", 1, 10800), ("seconds_per_game", 1, 600)):
        if type(config[key]) is not int or not lower <= config[key] <= upper:
            raise ValueError("Invalid finite budget: " + key)
    seeds = config["seeds"]
    if not isinstance(seeds, list) or not 1 <= len(seeds) <= 8 or len(set(seeds)) != len(seeds) or any(type(s) is not int or not 0 <= s < 2**31 for s in seeds):
        raise ValueError("Invalid seeds")
    for key in ("min_score_gain", "max_mean_level_regression"):
        if isinstance(config[key], bool) or not isinstance(config[key], (int, float)) or not math.isfinite(config[key]) or config[key] < 0:
            raise ValueError("Invalid comparison threshold: " + key)
    return config


@contextmanager
def exclusive_run(root):
    """OS lock is released on process exit, including an unclean interruption."""
    root.mkdir(parents=True, exist_ok=True)
    stream = (root / "run.lock").open("a+b")
    stream.seek(0, 2)
    if stream.tell() == 0:
        stream.write(b"0")
        stream.flush()
    stream.seek(0)
    try:
        if os.name == "nt":
            import msvcrt
            msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        stream.close()
        raise RuntimeError("This experiment already has an active runner")
    try:
        yield
    finally:
        if os.name == "nt":
            stream.seek(0)
            msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            fcntl.flock(stream, fcntl.LOCK_UN)
        stream.close()


def engine_inventory():
    files = [HERE / name for name in ("proposal.py", "evaluate.py", "loop.py")]
    files += [cycle.HERE / name for name in ("cycle.py", "cpu_smoke.py", "profiles.json")]
    return {p.relative_to(HERE.parent).as_posix(): cycle.cycle_file_digest(p) for p in files}


def accepted(candidate, incumbent, config):
    return (candidate["mean_public_rhae"] > incumbent["mean_public_rhae"] + config["min_score_gain"]
            and candidate["mean_levels_completed"] + config["max_mean_level_regression"] >= incumbent["mean_levels_completed"])


def checked_result(case, candidate_id, protocol):
    receipt = cycle.read(case / "receipt.json")
    if any(cycle.cycle_file_digest(case / name) != receipt[key] for name, key in
           (("result.json", "result_sha256"), ("scorecard.json", "scorecard_sha256"))):
        raise ValueError("Recorded evaluation bytes changed")
    result = cycle.read(case / "result.json")
    if cycle.cycle_file_digest(case / "trace.jsonl.gz") != result["trace_sha256"]:
        raise ValueError("Recorded trace changed")
    if result["candidate_id"] != candidate_id or result["protocol_id"] != protocol["protocol_id"]:
        raise ValueError("Candidate or protocol identity mismatch")
    return result


def evaluate_candidate(bundle, root, protocol, deadline):
    candidate_id = cycle.verify(bundle)["candidate_id"]
    results = []
    for game in protocol["games"]:
        for seed in protocol["seeds"]:
            if (root / "STOP").exists():
                raise InterruptedError("STOP file requested termination")
            case = bundle / "evaluation" / f"{game}-s{seed}"
            if (case / "result.json").exists():
                results.append(checked_result(case, candidate_id, protocol))
                continue
            intent = case.with_suffix(".intent.json")
            if intent.exists() or case.exists():
                raise RuntimeError("Interrupted case retained; candidate rejected without automatic replay")
            remaining = deadline - time.time()
            if remaining <= 0:
                raise TimeoutError("Experiment wall-time budget exhausted")
            cycle.save(intent, {"candidate_id": candidate_id, "protocol_id": protocol["protocol_id"],
                                "game": game, "seed": seed, "started_utc": cycle.now()}, exclusive=True)
            command = [sys.executable, "-B", "-X", "utf8", str(HERE / "evaluate.py"),
                       "--bundle", str(bundle), "--runtime", str(root / "runtime"), "--game", game,
                       "--seed", str(seed), "--out", str(case), "--protocol", str(root / "protocol.json")]
            environment = {k: v for k, v in os.environ.items() if k not in
                           ("KAGGLE_API_TOKEN", "KAGGLE_KEY", "KAGGLE_USERNAME", "ARC_API_KEY", "OPENAI_API_KEY", "GH_TOKEN", "GITHUB_TOKEN")}
            environment["PYTHONDONTWRITEBYTECODE"] = "1"
            environment["PYTHONHASHSEED"] = "0"
            with case.with_suffix(".log").open("w", encoding="utf-8") as log:
                subprocess.run(command, stdout=log, stderr=subprocess.STDOUT, env=environment,
                               check=True, timeout=min(remaining, protocol["seconds_per_game"]))
            result = checked_result(case, candidate_id, protocol)
            results.append(result)
            print(json.dumps({"event": "game_complete", "candidate": bundle.name, "game": game,
                              "seed": seed, "score": result["score"], "levels": result["levels_completed"]}), flush=True)
    return evaluate.summarize(results, protocol["games"], protocol["seeds"], candidate_id,
                              protocol["protocol_id"], protocol["actions_per_game"])


def freeze_candidate(base, root, index, parameters, hypothesis):
    label = f"auto-{index:03d}"
    bundle = root / "candidates" / label
    notebook = base if index == 0 else proposal.derive(base, parameters)
    if (bundle / "manifest.json").exists():
        manifest = cycle.verify(bundle)
        if manifest["identity"]["code_sha256"] != cycle.code_hash(notebook):
            raise ValueError("Existing candidate differs from its proposal")
        return bundle, manifest
    source = root / "proposals" / (label + ".ipynb")
    cycle.save(source, notebook)
    manifest = cycle.prepare("cpu-c8b", bundle, label, hypothesis, notebook=source)
    return bundle, manifest


def export(root, state):
    if state.get("incumbent") is None:
        return
    attempt = state["attempts"][state["incumbent"]]
    bundle = root / "candidates" / attempt["label"]
    manifest = cycle.verify(bundle)
    selected = root / "selected"
    selected.mkdir(exist_ok=True)
    raw = (bundle / "submission.ipynb").read_bytes()
    temporary = selected / "submission.ipynb.tmp"
    temporary.write_bytes(raw)
    temporary.replace(selected / "submission.ipynb")
    cycle.save(selected / "selection.json", {"candidate_id": manifest["candidate_id"],
               "notebook_sha256": cycle.digest(raw), "protocol_id": state["protocol_id"],
               "parameters": attempt["parameters"], "summary": attempt["summary"],
               "baseline_retained": state["incumbent"] == 0, "official_submission": "manual_only",
               "scope": "Selected on this public demo set only; requires separate official evaluation"})


def run(config, archive, root, *, evaluator=evaluate_candidate):
    config = validate_config(config)
    root = Path(root).resolve()
    with exclusive_run(root):
        inventory = evaluate.prepare_runtime(archive, root / "runtime")
        base_path = cycle.HERE / "notebooks/cpu-c8b.ipynb"
        base = cycle.read(base_path)
        initial_parameters = proposal.parameters(base)
        description = {**config, "games": evaluate.select_games(config["games"], inventory["games"]),
                       "baseline_sha256": cycle.cycle_file_digest(base_path),
                       "runtime_inventory_sha256": cycle.digest(cycle.encoded(inventory)),
                       "engine": engine_inventory(), "python": platform.python_version(),
                       "packages": evaluate.runtime_versions(), "os": platform.system()}
        protocol = {**description, "protocol_id": cycle.digest(cycle.encoded(description))}
        state_path = root / "state.json"
        if state_path.exists():
            state = cycle.read(state_path)
            if state["protocol_id"] != protocol["protocol_id"] or cycle.read(root / "protocol.json") != protocol:
                raise ValueError("Experiment code, configuration, dependencies, or data changed; use a new run directory")
            if state["status"] == "stopped":
                # Verify every retained result before presenting the same conclusion.
                for attempt in state["attempts"]:
                    if attempt["status"] == "measured":
                        bundle = root / "candidates" / attempt["label"]
                        rows = [checked_result(bundle / "evaluation" / f"{g}-s{s}", attempt["candidate_id"], protocol)
                                for g in protocol["games"] for s in protocol["seeds"]]
                        summary = evaluate.summarize(rows, protocol["games"], protocol["seeds"], attempt["candidate_id"],
                                                     protocol["protocol_id"], protocol["actions_per_game"])
                        if summary != attempt["summary"]:
                            raise ValueError("Saved summary differs from retained measurements")
                export(root, state)
                return state
        else:
            cycle.save(root / "protocol.json", protocol, exclusive=True)
            state = {"schema_version": 1, "protocol_id": protocol["protocol_id"], "status": "running",
                     "created_epoch": time.time(), "created_utc": cycle.now(), "incumbent": None,
                     "stale_rounds": 0, "attempts": [], "official_submission": "manual_only"}
            cycle.save(state_path, state, exclusive=True)
        deadline = state["created_epoch"] + config["max_wall_seconds"]
        while True:
            if (root / "STOP").exists():
                reason = "stop_requested"
                break
            if time.time() >= deadline:
                reason = "wall_time_budget"
                break
            pending = next((a for a in state["attempts"] if a["status"] == "evaluating"), None)
            if pending is None:
                if not state["attempts"]:
                    choice = {"parameters": initial_parameters, "hypothesis": "Measure the unchanged c8b baseline."}
                else:
                    if state["incumbent"] is None:
                        reason = "baseline_failed"
                        break
                    if len(state["attempts"]) - 1 >= config["max_candidates"]:
                        reason = "candidate_budget"
                        break
                    if state["stale_rounds"] >= config["patience"]:
                        reason = "no_improvement"
                        break
                    best = state["attempts"][state["incumbent"]]
                    choice = proposal.propose(best["parameters"], [proposal.signature(a["parameters"]) for a in state["attempts"]], best["summary"])
                    if choice is None:
                        reason = "neighbourhood_exhausted"
                        break
                index = len(state["attempts"])
                bundle, manifest = freeze_candidate(base, root, index, choice["parameters"], choice["hypothesis"])
                pending = {"index": index, "label": bundle.name, "candidate_id": manifest["candidate_id"],
                           **choice, "status": "evaluating", "accepted": False}
                state["attempts"].append(pending)
                cycle.save(state_path, state)
            bundle = root / "candidates" / pending["label"]
            print(json.dumps({"event": "candidate_started", "candidate": pending["label"],
                              "parameters": pending["parameters"]}), flush=True)
            try:
                summary = evaluator(bundle, root, protocol, deadline)
                pending.update(status="measured", summary=summary)
                if state["incumbent"] is None or accepted(summary, state["attempts"][state["incumbent"]]["summary"], config):
                    state["incumbent"] = pending["index"]
                    state["stale_rounds"] = 0
                    pending["accepted"] = True
                else:
                    state["stale_rounds"] += 1
            except (Exception,) as exc:
                pending.update(status="failed", error={"type": type(exc).__name__, "message": str(exc)[:1000]})
                state["stale_rounds"] += 1
            cycle.save(state_path, state)
            cycle.save(root / "decisions" / (pending["label"] + ".json"), pending)
            export(root, state)
            print(json.dumps({"event": "candidate_finished", "candidate": pending["label"],
                              "status": pending["status"], "accepted": pending["accepted"]}), flush=True)
        state.update(status="stopped", stop_reason=reason, stopped_utc=cycle.now())
        cycle.save(state_path, state)
        export(root, state)
        cycle.save(root / "report.json", state)
        return state


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=HERE / "config.json")
    parser.add_argument("--official-zip", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    result = run(cycle.read(args.config), args.official_zip.resolve(), args.out)
    print(json.dumps({"status": result["status"], "stop_reason": result["stop_reason"],
                      "attempts": len(result["attempts"]), "incumbent": result["incumbent"],
                      "official_submission": "manual_only"}), flush=True)
    sys.exit(0 if result["incumbent"] is not None else 2)
