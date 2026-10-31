"""Exercise notebook adapters against the downloaded official ARC runtime.

The gateway below serves public demos under synthetic IDs. It checks the HTTP
contract, never hidden-game performance. No model weights or model API is used.
"""
from __future__ import annotations

import argparse
import ast
from contextlib import redirect_stdout
import importlib.util
import io
import json
import logging
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import threading
import warnings
from types import ModuleType
from unittest.mock import patch
from urllib.parse import urlsplit, urlunsplit
import zipfile

import cycle
from cpu_smoke import official_runtime


def extract(archive, target, prefix=""):
    with zipfile.ZipFile(archive) as source:
        for name in source.namelist():
            if name.endswith("/") or not name.startswith(prefix):
                continue
            path = target / name
            if not path.resolve().is_relative_to(target.resolve()):
                raise ValueError("Unexpected archive path")
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(source.read(name))


def sources(profile):
    return cycle.code_sources(cycle.read(cycle.HERE / cycle.profiles()[profile]["notebook"]))


def patched_source(source_zip, profile, target):
    extract(source_zip, target)
    # A Kaggle bundle is outside a Git checkout. Reproduce that behaviour even
    # when this audit's build directory lives inside the Actions checkout.
    git_environment = {**os.environ, "GIT_CEILING_DIRECTORIES": str(target.resolve())}
    for index, cell in enumerate(sources(profile)):
        if cell.startswith("%%writefile /kaggle/") and ".patch\n" in cell.splitlines()[0] + "\n":
            name = cell.splitlines()[0].split("/kaggle/", 1)[1]
            patch_file = target / name
            # IPython's %%writefile supplies the final newline that a notebook
            # cell source may omit. git apply requires it on the final hunk.
            patch_file.write_bytes((cell.split("\n", 1)[1].rstrip("\n") + "\n").encode("utf-8"))
            before = {p.relative_to(target).as_posix(): cycle.cycle_file_digest(p)
                      for p in (target / "src/ARC3-Inference").rglob("*.py")}
            checked = subprocess.run(["git", "apply", "--check", "--include=ARC3-Inference/*", str(patch_file.resolve())],
                                     cwd=target / "src", env=git_environment, capture_output=True, text=True)
            if checked.returncode:
                raise ValueError(name + ": " + checked.stderr[:2000])
            subprocess.run(["git", "apply", "--include=ARC3-Inference/*", str(patch_file.resolve())],
                           cwd=target / "src", env=git_environment, check=True, capture_output=True)
            after = {p.relative_to(target).as_posix(): cycle.cycle_file_digest(p)
                     for p in (target / "src/ARC3-Inference").rglob("*.py")}
            if before == after:
                raise ValueError("Notebook patch was skipped: " + name)
    return target


def load_cpu(framework, target, profile):
    cell = next(s for s in sources(profile) if s.startswith("%%writefile /tmp/my_agent.py\n"))
    entry = target / "my_agent.py"
    entry.write_text(cell.split("\n", 1)[1], encoding="utf-8")
    spec = importlib.util.spec_from_file_location("connection_cpu", entry)
    module = importlib.util.module_from_spec(spec)
    with patch("tempfile.gettempdir", return_value=str(target)):
        spec.loader.exec_module(module)
    from agents.agent import Agent
    if module.MyAgent.main is not Agent.main:
        raise ValueError("CPU replaced the official Agent.main loop")
    return module.MyAgent


def functions(profile):
    cell = next(s for s in sources(profile) if "def _competition_games():" in s)
    tree = ast.parse(cell)
    selected = [n for n in tree.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]
    namespace = {"os": os, "Path": Path, "demo_excluded_games": []}
    exec(compile(ast.Module(body=selected, type_ignores=[]), profile + "_game_factories", "exec"), namespace)
    return namespace


def frame_check(raw):
    import numpy as np
    assert raw is not None and raw.frame
    for pixels in raw.frame:
        array = np.asarray(pixels)
        assert array.ndim == 2 and 0 < array.shape[0] <= 64 and 0 < array.shape[1] <= 64
        assert np.all((array >= 0) & (array <= 15))
    assert raw.win_levels > 0


def gpu_steps(game, session):
    import arcengine
    game.start_game(session)
    frame_check(game.current_state.raw)
    options = [a for a in game.current_state.available_actions if a != 0]
    action_id = next((a for a in options if a != 6), 6)
    data = {"x": 32, "y": 32} if action_id == 6 else {}
    result = game.execute_action(arcengine.ActionInput(id=arcengine.GameAction.from_id(action_id), data=data))
    frame_check(result.raw)
    return {"game_id": game.env_name, "action_id": action_id, "levels": game.number_of_levels}


def gateway(arc, callback):
    """Real loopback HTTP, including SDK URL/cookie/redirect behaviour."""
    import requests
    from arc_agi.server import create_app
    from werkzeug.serving import make_server, WSGIRequestHandler
    app, _ = create_app(arc, competition_mode=True)
    class QuietHandler(WSGIRequestHandler):
        def log(self, *args, **kwargs):
            pass
    server = make_server("127.0.0.1", 0, app, threaded=True, request_handler=QuietHandler)
    worker = threading.Thread(target=server.serve_forever, daemon=True)
    worker.start()
    original_request = requests.sessions.Session.request
    calls = []

    def request(session, method, url, **kwargs):
        parsed = urlsplit(url)
        if parsed.hostname == "arc3-connection-test":
            actual = urlunsplit(("http", f"127.0.0.1:{server.server_port}", parsed.path, parsed.query, parsed.fragment))
        elif parsed.hostname == "127.0.0.1" and parsed.port == server.server_port:
            actual = url
        else:
            raise RuntimeError("External network is disabled in connection checks")
        response = original_request(session, method, actual, **kwargs)
        calls.append({"method": method.upper(), "path": parsed.path, "status": response.status_code})
        return response

    try:
        with patch.dict(os.environ, {"ARC_API_KEY": "connection-test-placeholder", "ARC_BASE_URL": "http://arc3-connection-test/",
                                     "OPERATION_MODE": "competition", "ENVIRONMENTS_DIR": ""}), \
             patch.object(requests.sessions.Session, "request", request):
            value = callback()
    finally:
        server.shutdown()
        server.server_close()
        worker.join(timeout=5)
    assert calls and all(r["status"] < 400 for r in calls), calls
    return {"result": value, "requests": calls}


def run(args, report):
    import importlib.metadata
    runtime = args.out / "runtime"
    runtime.mkdir(parents=True)
    framework, provenance = official_runtime(args.competition_zip, runtime)
    with zipfile.ZipFile(args.competition_zip) as source:
        for name in ("agents/swarm.py", "main.py"):
            target = framework / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(source.read("ARC-AGI-3-Agents/" + name))
    sys.path.insert(0, str(framework))
    logging.disable(logging.CRITICAL)
    env_root = runtime / "competition"
    extract(args.competition_zip, env_root, "environment_files/")
    env_dir = env_root / "environment_files"
    os.environ["MPLBACKEND"] = "Agg"
    os.environ["RECORDINGS_DIR"] = str(runtime / "recordings")
    os.environ.pop("OPERATION_MODE", None)
    from arc_agi import Arcade, OperationMode
    cpu = load_cpu(framework, runtime, args.cpu_profile)
    report["runtime_source"] = provenance
    report["versions"] = {p: importlib.metadata.version(p) for p in ("arc-agi", "arcengine", "numpy")}
    official = Arcade(operation_mode=OperationMode.OFFLINE, environments_dir=str(env_dir))
    ids = sorted(e.game_id for e in official.get_environments())
    assert len(ids) == 25

    # Keep the candidate source intact. A two-decision test cap limits only this
    # interface check; the separate cpu_smoke run preserves its 1200-call budget.
    cpu.MAX_ACTIONS = 2
    cpu_rows = []
    for game_id in ids:
        card = official.create_scorecard()
        env = official.make(game_id, scorecard_id=card)
        frame_check(env.observation_space)
        agent = cpu(card_id=card, game_id=game_id, agent_name="myagent", ROOT_URL="unused",
                    record=False, arc_env=env)
        agent.main()
        assert agent.action_counter == 2 and agent.pending is None
        cpu_rows.append({"game_id": game_id, "decisions": agent.action_counter})
        official.close_scorecard(card)
    report["checks"].append({"name": "CPU official Agent loop and legal actions on every public demo",
                             "passed": True, "test_decision_cap": 2, "games": cpu_rows})

    baseline = patched_source(args.source_zip, "gpu-baseline", runtime / "gpu-baseline")
    memory = patched_source(args.source_zip, "gpu-memory", runtime / "gpu-memory")
    for profile, tree in (("gpu-baseline", baseline), ("gpu-memory", memory)):
        for source in (tree / "src/ARC3-Inference").rglob("*.py"):
            ast.parse(source.read_text(encoding="utf-8"), filename=str(source))
        report["checks"].append({"name": profile + " notebook patches apply to its actual Kaggle source input",
                                 "passed": True, "patched_python_parses": True})
    api_path = baseline / "src/tufa-arc-agi-framework/src/taaf"
    namespace = ModuleType("taaf")
    namespace.__path__ = [str(api_path)]
    sys.modules["taaf"] = namespace
    from taaf.game import RunSession
    from taaf.game_api import GameAPI
    baseline_functions = functions("gpu-baseline")
    memory_functions = functions("gpu-memory")
    factories_equal = next(s for s in sources("gpu-memory") if "def _competition_games():" in s) == next(
        s for s in sources("gpu-baseline") if "def _competition_games():" in s)
    assert factories_equal
    games = baseline_functions["_offline_games"](str(env_dir))
    assert sorted(g.env_name for g in games) == ids
    assert sorted(g.env_name for g in memory_functions["_offline_games"](str(env_dir))) == ids
    session = RunSession()
    gpu_rows = []
    with redirect_stdout(io.StringIO()):
        for game in games:
            gpu_rows.append(gpu_steps(game, session))
            game.finish_game()
    session.close()
    report["checks"].append({"name": "GPU GameAPI and both notebook factories on every official public demo",
                             "passed": True, "games": gpu_rows, "game_api_sha256": cycle.cycle_file_digest(api_path / "game_api.py"),
                             "baseline_memory_game_factories_identical": True})

    # Exercise the added memory's real public-frame conversion and record/query
    # interface without importing the model-serving stack or replaying actions.
    memory_file = memory / "src/ARC3-Inference/inference/agent/evidence_memory.py"
    spec = importlib.util.spec_from_file_location("connection_evidence_memory", memory_file)
    memory_module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(memory_module)
    solver_source = (memory / "src/ARC3-Inference/inference/framework/solver.py").read_text(encoding="utf-8")
    helper_nodes = [ast.ImportFrom(module="__future__", names=[ast.alias(name="annotations")], level=0)]
    helper_nodes.extend(n for n in ast.parse(solver_source).body if isinstance(n, ast.FunctionDef)
                        and n.name in ("_grid_from_state", "_level_number"))
    helpers = {}
    exec(compile(ast.fix_missing_locations(ast.Module(body=helper_nodes, type_ignores=[])), "memory_frame_helpers", "exec"), helpers)
    game = baseline_functions["_offline_games"](str(env_dir))[0]
    session = RunSession()
    game.start_game(session)
    before = helpers["_grid_from_state"](game.current_state)
    before_level = helpers["_level_number"](game)
    import arcengine
    action = arcengine.ActionInput(id=arcengine.GameAction.RESET)
    result = game.execute_action(action)
    after = helpers["_grid_from_state"](result)
    evidence = memory_module.EvidenceMemory("connection-check", run_id="synthetic-public-demo")
    event_id = evidence.record_executed_event(before_grid=before, after_grid=after,
        action={"name": action.id.name, "data": dict(action.data)}, public_result={"executed": True, "state": result.raw.state.name},
        before_level=before_level, after_level=helpers["_level_number"](game), before_step=0, after_step=1)
    assert event_id is not None and len(evidence.export()["events"]) == 1
    count_before = len(game.game_run.history)
    reread = evidence.query({"op": "reread", "event_ids": [event_id], "include_frames": True},
                            current_grid=after, current_level=helpers["_level_number"](game))
    assert reread["executed"] is False and len(game.game_run.history) == count_before
    with redirect_stdout(io.StringIO()):
        game.finish_game()
    session.close()
    report["checks"].append({"name": "GPU memory records real SDK observations; reread performs no game action",
                             "passed": True, "events": 1, "query_executed": False,
                             "memory_source_sha256": cycle.cycle_file_digest(memory_file)})

    def server_arc():
        arc = Arcade(operation_mode=OperationMode.OFFLINE, environments_dir=str(env_dir))
        original = arc.get_environments()
        selected = [next(e for e in original if e.game_id.startswith(prefix)) for prefix in ("ls20-", "vc33-")]
        # Clone only the metadata ID. Keep the original class/file location so
        # the gateway serves real demos with names absent from policy development.
        arc.available_environments = [e.model_copy(update={"game_id": f"u00{i+1}-abcdef01"}) for i, e in enumerate(selected)]
        return arc

    def cpu_gateway():
        import requests
        import agents
        agents.AVAILABLE_AGENTS = {"myagent": cpu}
        from agents.swarm import Swarm
        game_ids = [entry["game_id"] for entry in requests.get("http://arc3-connection-test/api/games", timeout=10).json()]
        assert game_ids == ["u001-abcdef01", "u002-abcdef01"]
        swarm = Swarm("myagent", "http://arc3-connection-test", game_ids)
        with redirect_stdout(io.StringIO()):
            swarm.main()
        assert len(swarm.agents) == 2
        assert all(a.action_counter == 2 and a.pending is None for a in swarm.agents)
        return {"game_ids": [a.game_id for a in swarm.agents], "decisions_each": 2}

    report["checks"].append({"name": "CPU official Swarm and HTTP gateway on synthetic unseen IDs", "passed": True,
                             **gateway(server_arc(), cpu_gateway)})

    def gpu_gateway():
        games = baseline_functions["_competition_games"]()
        assert [g.env_name for g in games] == ["u001-abcdef01", "u002-abcdef01"]
        session = RunSession()
        rows = [gpu_steps(g, session) for g in games]
        assert games[0]._scorecard_id == games[1]._scorecard_id
        assert all(g.base_actions_per_level is None for g in games)
        for game in games:
            game.finish_game()
        session.close()
        return {"games": rows, "shared_scorecard": True, "hidden_baselines_handled": True}

    with warnings.catch_warnings():
        warnings.filterwarnings("ignore", message="arcengine returned no baseline_actions.*")
        report["checks"].append({"name": "GPU competition factory, HTTP actions and shared scorecard", "passed": True,
                                 **gateway(server_arc(), gpu_gateway)})
    report["checks"].append({"name": "Both notebooks enumerate the gateway catalog; demo IDs are not the rerun game list",
                             "passed": True, "synthetic_ids": ["u001-abcdef01", "u002-abcdef01"]})


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--competition-zip", type=Path, required=True)
    parser.add_argument("--source-zip", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--cpu-profile", default="cpu-c8b")
    args = parser.parse_args()
    args.out = args.out.resolve()
    args.out.mkdir(parents=True, exist_ok=False)
    report = {"observed_utc": cycle.now(), "checks": [], "passed": False,
              "competition_zip_sha256": cycle.cycle_file_digest(args.competition_zip),
              "gpu_source_zip_sha256": cycle.cycle_file_digest(args.source_zip),
              "cpu_profile_tested": args.cpu_profile,
              "notebook_code_sha256": {p: cycle.code_hash(cycle.read(cycle.HERE / config["notebook"]))
                                       for p, config in cycle.profiles().items() if p in (args.cpu_profile, "gpu-baseline", "gpu-memory")},
              "scope": "Public-demo and simulated-gateway integration; no model inference, hidden games, competition submission or official score"}
    try:
        run(args, report)
        report["passed"] = True
    except Exception as exc:
        report["error"] = type(exc).__name__ + ": " + str(exc)[:2000]
        raise
    finally:
        cycle.save(args.out / "report.json", report)
        print(json.dumps({k: v for k, v in report.items() if k != "checks"}, indent=2), flush=True)


if __name__ == "__main__":
    main()
