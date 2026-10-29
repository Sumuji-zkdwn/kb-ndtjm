"""Pinned offline public-demo evaluator. This module has no submission API."""
from __future__ import annotations

import argparse
from collections import Counter
import gzip
import hashlib
import importlib.metadata
import importlib.util
import json
import logging
import math
import os
from pathlib import Path
import socket
import sys
import tempfile
import time
from unittest.mock import patch
import zipfile

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "cycle"))
import cycle
from cpu_smoke import official_runtime


def prepare_runtime(archive, root):
    archive, root = Path(archive), Path(root)
    if cycle.cycle_file_digest(archive) != cycle.OFFICIAL_ZIP_SHA256:
        raise ValueError("Official ZIP differs from the pinned competition bundle")
    if (root / "inventory.json").exists():
        inventory = cycle.read(root / "inventory.json")
        for name, expected in inventory["files"].items():
            if cycle.cycle_file_digest(root / name) != expected:
                raise ValueError("Runtime changed: " + name)
        return inventory
    root.mkdir(parents=True, exist_ok=True)
    _, provenance = official_runtime(archive, root)
    with zipfile.ZipFile(archive) as bundle:
        for name in bundle.namelist():
            if not name.startswith("environment_files/") or name.endswith("/"):
                continue
            target = root / name
            if not target.resolve().is_relative_to(root.resolve()):
                raise ValueError("Unsafe archive path")
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(bundle.read(name))
    metadata = [cycle.read(p) for p in sorted((root / "environment_files").rglob("metadata.json"))]
    # The exact ZIP is public/demo-only; do not discover tasks from arbitrary paths.
    games = sorted(m["game_id"] for m in metadata)
    if len(games) != 25 or len(set(games)) != len(games):
        raise ValueError("Expected the pinned set of 25 public demos")
    if any(not m.get("baseline_actions") or any(type(n) is not int or n <= 0 for n in m["baseline_actions"]) for m in metadata):
        raise ValueError("Public human action baselines are missing")
    inventory = {"provenance": provenance, "games": games,
                 "files": {p.relative_to(root).as_posix(): cycle.cycle_file_digest(p)
                           for p in sorted(root.rglob("*")) if p.is_file() and "__pycache__" not in p.parts}}
    cycle.save(root / "inventory.json", inventory, exclusive=True)
    return inventory


def select_games(request, available):
    if request == "all":
        return list(available)
    if not isinstance(request, list) or not request or not all(isinstance(g, str) for g in request):
        raise ValueError("games must be 'all' or a nonempty list")
    result = []
    for game in request:
        found = [g for g in available if g == game or g.split("-", 1)[0] == game]
        if len(found) != 1 or found[0] in result:
            raise ValueError("Unknown, ambiguous, or duplicate public game: " + game)
        result.append(found[0])
    return sorted(result)


def runtime_versions():
    return {name: importlib.metadata.version(name) for name in
            ("numpy", "pydantic", "matplotlib", "nbformat", "ipython", "python-dotenv", "requests", "flask")}


def make_scored_environment(arc, game, seed, card_id):
    # arc-agi 0.9.8 registers a new scoring run on the initialization full reset.
    # With ONLY_RESET_LEVELS=true before make(), gameplay runs but the card stays
    # empty. Allow exactly this initial reset, then restore level-only resets.
    with patch.dict(os.environ, {"ONLY_RESET_LEVELS": "false"}):
        env = arc.make(game, seed=seed, scorecard_id=card_id, save_recording=False)
    if env is None or not env.observation_space.full_reset:
        raise ValueError("Initial reset did not register a fresh game")
    return env


def worker(bundle, runtime, game, seed, out, protocol):
    """Run the unchanged official Agent.main; policy receives public fields only."""
    manifest = cycle.verify(bundle, launch=True)
    out.mkdir(parents=True, exist_ok=False)
    temporary = out / "temporary"
    temporary.mkdir()
    tempfile.tempdir = str(temporary.resolve())
    sys.dont_write_bytecode = True
    sys.path[:0] = [str(runtime / "official-sdk"), str(runtime / "official-framework")]
    os.environ.update({"OPERATION_MODE": "offline", "ONLY_RESET_LEVELS": "true", "ARC_API_KEY": "public-local",
                       "MPLBACKEND": "Agg", "RECORDINGS_DIR": str(temporary / "recordings"),
                       "ENVIRONMENTS_DIR": str(runtime / "environment_files")})
    logging.disable(logging.CRITICAL)
    payload = next(s.split("\n", 1)[1] for s in cycle.code_sources(cycle.read(bundle / "submission.ipynb"))
                   if s.startswith("%%writefile /tmp/my_agent.py\n"))
    entry = temporary / "my_agent.py"
    entry.write_text(payload, encoding="utf-8")
    spec = importlib.util.spec_from_file_location("autonomous_candidate", entry)
    module = importlib.util.module_from_spec(spec)

    def blocked(*args, **kwargs):
        raise RuntimeError("External network disabled during public evaluation")

    started = time.monotonic()
    with patch.object(socket.socket, "connect", blocked), patch.object(socket.socket, "connect_ex", blocked), patch.object(socket, "getaddrinfo", blocked):
        spec.loader.exec_module(module)
        from agents.agent import Agent
        from arc_agi import Arcade, OperationMode
        if module.MyAgent.main is not Agent.main or module.MyAgent.MAX_ACTIONS + 1 != protocol["actions_per_game"]:
            raise ValueError("Official loop or frozen action budget changed")
        arc = Arcade(operation_mode=OperationMode.OFFLINE,
                     environments_dir=str(runtime / "environment_files"), logger=logging.getLogger("autonomous-public"))
        if arc.operation_mode != OperationMode.OFFLINE:
            raise ValueError("Expected OFFLINE mode")
        card_id = arc.create_scorecard(tags=["autonomous-public-demo-not-kaggle"])
        env = make_scored_environment(arc, game, seed, card_id)
        calls, failures, repeated = 1, 0, 0
        last = None
        visits = Counter()
        with gzip.open(out / "trace.jsonl.gz", "wt", encoding="utf-8") as stream:
            def record(action):
                nonlocal last, failures, repeated
                frame = env.observation_space
                arrays = [a.tolist() if hasattr(a, "tolist") else a for a in frame.frame]
                visible = cycle.digest(cycle.encoded({"frames": arrays, "levels": int(frame.levels_completed)}))
                repeated += visible == last
                failures += frame.state.name == "GAME_OVER" and action["id"] != 0
                last = visible
                visits[visible] += 1
                stream.write(json.dumps({"call": calls, "action": action, "observation_sha256": visible,
                    "state": frame.state.name, "levels_completed": int(frame.levels_completed)}) + "\n")
            record({"id": 0})

            class Tracked:
                @property
                def observation_space(self):
                    return env.observation_space

                def step(self, action, data=None, reasoning=None):
                    nonlocal calls
                    if calls >= protocol["actions_per_game"]:
                        raise ValueError("Candidate exceeded fixed action budget")
                    result = env.step(action, data=data, reasoning=reasoning)
                    calls += 1
                    record({"id": int(action.value), **(data or {})})
                    return result

            agent = module.MyAgent(card_id=card_id, game_id="public-evaluation", agent_name="myagent",
                                   ROOT_URL="http://localhost", record=False, arc_env=Tracked())
            agent.main()
            # Gzip adds its checksum/footer on close. Hash the finalized bytes.
            stream.close()
            frame = env.observation_space
            card = arc.close_scorecard(card_id)
            if card is None:
                raise ValueError("No scorecard returned")
            data = json.loads(card.model_dump_json())
            cycle.save(out / "scorecard.json", data, exclusive=True)
            scores = [e for e in data["environments"] if e["id"] == game]
            if len(scores) != 1 or len(scores[0].get("runs", [])) != 1 or any(r.get("message") for r in scores[0]["runs"]):
                raise ValueError("Invalid public environment score; inspect scorecard.json")
            result = {"candidate_id": manifest["candidate_id"], "protocol_id": protocol["protocol_id"],
                      "game": game, "seed": seed, "score": scores[0]["score"],
                      "levels_completed": int(frame.levels_completed), "win": frame.state.name == "WIN",
                      "calls": calls, "failures": failures, "repeated_frames": repeated,
                      "unique_frames": len(visits), "seconds": time.monotonic() - started,
                      "official_loop_unchanged": True, "level_reset_only": True,
                      "trace_sha256": cycle.cycle_file_digest(out / "trace.jsonl.gz"),
                      "diagnostics": agent.core.diagnostics(),
                      "sdk_versions": {p: importlib.metadata.version(p) for p in ("arc-agi", "arcengine")}}
            cycle.save(out / "result.json", result, exclusive=True)
            cycle.save(out / "receipt.json", {"result_sha256": cycle.cycle_file_digest(out / "result.json"),
                       "scorecard_sha256": cycle.cycle_file_digest(out / "scorecard.json")}, exclusive=True)
    return result


def summarize(rows, games, seeds, candidate_id, protocol_id, action_cap):
    expected = {(g, s) for g in games for s in seeds}
    actual = [(r["game"], r["seed"]) for r in rows]
    if len(actual) != len(expected) or set(actual) != expected:
        raise ValueError("Incomplete or duplicate public evaluation; missing games are never omitted from the denominator")
    for r in rows:
        if r["candidate_id"] != candidate_id or r["protocol_id"] != protocol_id:
            raise ValueError("Results belong to a different candidate or protocol")
        if not r.get("official_loop_unchanged") or not r.get("level_reset_only"):
            raise ValueError("Invalid agent/reset semantics")
        if not isinstance(r["score"], (int, float)) or not math.isfinite(r["score"]) or not 0 <= r["score"] <= 100:
            raise ValueError("Invalid public score")
        if type(r["calls"]) is not int or not 1 <= r["calls"] <= action_cap:
            raise ValueError("Action budget exceeded")
        if type(r["levels_completed"]) is not int or r["levels_completed"] < 0:
            raise ValueError("Invalid level count")
    return {"mean_public_rhae": sum(r["score"] for r in rows) / len(rows),
            "mean_levels_completed": sum(r["levels_completed"] for r in rows) / len(rows),
            "wins": sum(bool(r["win"]) for r in rows), "cases": len(rows),
            "calls": sum(r["calls"] for r in rows),
            "failure_rate": sum(r["failures"] for r in rows) / sum(r["calls"] for r in rows),
            "scope": "Fixed public demos and seeds only; not official Kaggle or unseen-game performance"}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("bundle", "runtime", "out", "protocol"):
        parser.add_argument("--" + name, type=Path, required=True)
    parser.add_argument("--game", required=True)
    parser.add_argument("--seed", type=int, required=True)
    args = parser.parse_args()
    worker(args.bundle.resolve(), args.runtime.resolve(), args.game, args.seed, args.out.resolve(), cycle.read(args.protocol))
