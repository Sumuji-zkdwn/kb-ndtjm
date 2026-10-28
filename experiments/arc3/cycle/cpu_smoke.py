"""Run the exact CPU notebook payload through the unchanged official Agent.main."""
import argparse
import gzip
import importlib.metadata
import importlib.util
import json
import logging
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import time
from unittest.mock import patch
import cycle


def child(bundle, environments, game, seed, out):
    manifest = cycle.verify(bundle, launch=True)
    out.mkdir(parents=True, exist_ok=False)
    runtime = out / "runtime"
    runtime.mkdir()
    tempfile.tempdir = str(runtime.resolve())
    framework = cycle.HERE / "framework"
    inventory = cycle.read(cycle.HERE / "framework-sha256.json")
    for name, expected in inventory.items():
        if cycle.digest((framework / name).read_bytes()) != expected:
            raise ValueError("Official framework changed: " + name)
    sys.path.insert(0, str(framework))
    notebook = cycle.read(bundle / "submission.ipynb")
    cells = [s for s in cycle.code_sources(notebook) if s.startswith("%%writefile /tmp/my_agent.py\n")]
    if len(cells) != 1:
        raise ValueError("CPU notebook must contain one supported packaged-agent cell")
    entry = runtime / "my_agent.py"
    entry.write_text(cells[0].split("\n", 1)[1], encoding="utf-8")
    spec = importlib.util.spec_from_file_location("cycle_cpu_candidate", entry)
    module = importlib.util.module_from_spec(spec)
    logging.disable(logging.CRITICAL)

    def blocked(*args, **kwargs):
        raise RuntimeError("Network disabled for local game evaluation")

    with patch.object(socket.socket, "connect", blocked), patch.object(socket.socket, "connect_ex", blocked), patch.object(socket, "getaddrinfo", blocked):
        spec.loader.exec_module(module)
        from agents.agent import Agent
        from arc_agi import Arcade, OperationMode
        if module.MyAgent.main is not Agent.main:
            raise ValueError("Candidate replaced the official agent loop")
        arc = Arcade(operation_mode=OperationMode.OFFLINE, environments_dir=str(environments), logger=logging.getLogger("cycle-smoke"))
        if arc.operation_mode != OperationMode.OFFLINE:
            raise ValueError("SDK mode override prevented offline evaluation")
        available = [env.game_id for env in arc.get_environments() if env.game_id.split("-", 1)[0] == game or env.game_id == game]
        if len(available) != 1:
            raise ValueError("Select exactly one installed public game version: " + game)
        exact = available[0]
        card = arc.create_scorecard(tags=["cycle-local-not-kaggle"])
        env = arc.make(exact, seed=seed, scorecard_id=card, save_recording=False)
        started = time.perf_counter()
        calls = 1

        def record(stream, action):
            frame = env.observation_space
            stream.write(json.dumps({"call": calls, "action": action, "state": frame.state.name,
                "levels_completed": int(frame.levels_completed),
                "available_actions": [int(a) for a in frame.available_actions],
                "frames": [a.tolist() if hasattr(a, "tolist") else a for a in frame.frame]}) + "\n")

        with gzip.open(out / "trace.jsonl.gz", "wt", encoding="utf-8") as stream:
            record(stream, {"id": 0})
            class Tracked:
                @property
                def observation_space(self):
                    return env.observation_space

                def step(self, action, data=None, reasoning=None):
                    nonlocal calls
                    result = env.step(action, data=data, reasoning=reasoning)
                    calls += 1
                    record(stream, {"id": action.value, **(data or {})})
                    return result

            try:
                agent = module.MyAgent(card_id=card, game_id=exact, agent_name="myagent",
                                       ROOT_URL="http://localhost", record=False, arc_env=Tracked())
                agent.main()
                frame = env.observation_space
                result = {"candidate_id": manifest["candidate_id"], "game": exact, "seed": seed,
                          "calls_including_initial_reset": calls, "levels_completed": int(frame.levels_completed),
                          "state": frame.state.name, "win": frame.state.name == "WIN",
                          "seconds": round(time.perf_counter()-started, 4), "official_loop_unchanged": True,
                          "versions": {p: importlib.metadata.version(p) for p in ("arc-agi", "arcengine", "numpy")}}
                cycle.save(out / "result.json", result, exclusive=True)
            finally:
                arc.close_scorecard(card)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bundle", type=Path, required=True)
    parser.add_argument("--environments", type=Path, required=True)
    parser.add_argument("--games", nargs="+", default=["ls20", "ft09", "vc33"])
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--seconds-per-game", type=int, default=360)
    parser.add_argument("--child", action="store_true")
    parser.add_argument("--out", type=Path)
    args = parser.parse_args()
    args.bundle, args.environments = args.bundle.resolve(), args.environments.resolve()
    manifest = cycle.verify(args.bundle, launch=True)
    if manifest["identity"]["line"] != "cpu":
        raise ValueError("This smoke runner is for the CPU line only")
    if args.child:
        child(args.bundle, args.environments, args.games[0], args.seed, args.out)
        return
    root = args.bundle / "evidence" / "public-smoke"
    root.mkdir(parents=True, exist_ok=False)
    rows, errors = [], []
    try:
        for game in args.games:
            out = root / game
            command = [sys.executable, str(Path(__file__).resolve()), "--child", "--bundle", str(args.bundle),
                       "--environments", str(args.environments), "--games", game, "--seed", str(args.seed), "--out", str(out)]
            with (root / (game + ".log")).open("w", encoding="utf-8") as stream:
                subprocess.run(command, stdout=stream, stderr=subprocess.STDOUT, check=True, timeout=args.seconds_per_game)
            rows.append(cycle.read(out / "result.json"))
    except Exception as exc:
        errors.append(type(exc).__name__ + ": inspect the per-game log")
        raise
    finally:
        files = {p.relative_to(args.environments).as_posix(): cycle.digest(p.read_bytes())
                 for p in sorted(args.environments.rglob("*")) if p.is_file() and "__pycache__" not in p.parts}
        cycle.event(args.bundle, "public-smoke.json", passed=not errors and len(rows) == len(args.games),
                    results=rows, errors=errors, environment_sha256=files,
                    scope="Fresh offline public game runs of the exact notebook payload; not Kaggle or hidden-set validation")


if __name__ == "__main__":
    main()
