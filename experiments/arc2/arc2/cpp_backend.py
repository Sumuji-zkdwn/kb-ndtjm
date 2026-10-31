"""Optional offline C++ candidate generator with isolated, bounded subprocesses.

Call ``prepare_cpp_backend`` once before task workers are launched.  ``solve_cpp``
never compiles or downloads anything, and never forwards IDs or test answers.
"""

from __future__ import annotations

from contextlib import contextmanager
import hashlib
import json
import math
import os
from pathlib import Path
import shutil
import signal
import subprocess
import tempfile
import time


VENDOR_DIR = Path(__file__).resolve().parents[1] / "vendor" / "icecuber"
VENDOR_COMMIT = "9407072659de1270358c2ba34c527785214dd68b"
SOURCE_NAMES = (
    "main.cpp", "read.cpp", "core_functions.cpp", "image_functions.cpp",
    "image_functions2.cpp", "visu.cpp", "normalize.cpp", "runner.cpp",
    "brute2.cpp", "deduce_op.cpp", "pieces.cpp", "compose2.cpp",
    "brute_size.cpp", "efficient.cpp",
)
BUILD_FLAGS = ("-std=c++17", "-O2")


def _build_identity() -> tuple[str, Path]:
    digest = hashlib.sha256(b"arc2-inference-cpp-v1\0")
    files = [VENDOR_DIR / "src" / name for name in SOURCE_NAMES]
    files += sorted((VENDOR_DIR / "headers").glob("*.hpp"))
    if not files or not (VENDOR_DIR / "LICENSE").is_file():
        raise FileNotFoundError("Optional vendor source or license is missing")
    for file in files:
        digest.update(str(file.relative_to(VENDOR_DIR)).encode())
        digest.update(b"\0")
        digest.update(file.read_bytes())
    digest.update(" ".join(BUILD_FLAGS).encode())
    value = digest.hexdigest()
    return value, Path(tempfile.gettempdir()) / "arc2_cpp_cache" / value[:24] / "run"


def _cache_ready(binary: Path, identity: str) -> bool:
    if not binary.is_file() or not os.access(binary, os.X_OK):
        return False
    try:
        meta = json.loads(binary.with_name("build.json").read_text())
        return meta.get("source_sha256") == identity and binary.stat().st_size > 0
    except (OSError, ValueError):
        return False


@contextmanager
def _build_lock(path: Path, deadline: float):
    import fcntl

    with path.open("a") as handle:
        while True:
            try:
                fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                if time.monotonic() >= deadline:
                    raise TimeoutError("Another process is compiling the optional backend")
                time.sleep(min(0.05, max(0.001, deadline - time.monotonic())))
        try:
            yield
        finally:
            fcntl.flock(handle, fcntl.LOCK_UN)


def prepare_cpp_backend(compile_seconds: float = 180.0) -> dict:
    """Compile vendored source once; return ready/unavailable/error diagnostics.

    A zero budget only checks the cache.  Successful preparation sets
    ``ARC2_CPP_BINARY`` for spawned workers.  No binary is written into the repo.
    """
    started = time.monotonic()
    base = {"vendor_commit": VENDOR_COMMIT}
    if os.name != "posix":
        return {**base, "status": "unavailable", "reason": "POSIX resource limits required"}
    try:
        identity, binary = _build_identity()
    except OSError as exc:
        return {**base, "status": "unavailable", "reason": str(exc)}
    base["source_sha256"] = identity
    if _cache_ready(binary, identity):
        os.environ["ARC2_CPP_BINARY"] = str(binary)
        return {**base, "status": "ready", "binary": str(binary), "cached": True}
    if compile_seconds <= 0:
        return {**base, "status": "not_prepared", "reason": "Call prepare_cpp_backend before task workers"}
    compiler = shutil.which("g++")
    if not compiler:
        return {**base, "status": "unavailable", "reason": "g++ is not installed"}
    deadline = started + compile_seconds
    binary.parent.mkdir(parents=True, exist_ok=True)
    temporary = binary.with_name(f"run.{os.getpid()}.building")
    try:
        with _build_lock(binary.with_name("build.lock"), deadline):
            if _cache_ready(binary, identity):
                os.environ["ARC2_CPP_BINARY"] = str(binary)
                return {**base, "status": "ready", "binary": str(binary), "cached": True}
            command = [compiler, *BUILD_FLAGS, "-I", str(VENDOR_DIR / "headers")]
            command += [str(VENDOR_DIR / "src" / name) for name in SOURCE_NAMES]
            command += ["-lstdc++fs", "-o", str(temporary)]
            log = binary.with_name("build.log")
            with log.open("wb") as output:
                proc = subprocess.Popen(command, stdout=output, stderr=subprocess.STDOUT, start_new_session=True)
                try:
                    code = proc.wait(timeout=max(0.01, deadline - time.monotonic()))
                except subprocess.TimeoutExpired:
                    os.killpg(proc.pid, signal.SIGKILL)
                    proc.wait()
                    raise TimeoutError("Optional C++ compilation exceeded its preparation budget")
            if code != 0 or not temporary.is_file() or temporary.stat().st_size == 0:
                message = log.read_text(errors="replace")[-5000:]
                return {**base, "status": "error", "reason": "Compilation failed", "log_tail": message}
            temporary.replace(binary)
            meta = {**base, "compiler": compiler, "flags": list(BUILD_FLAGS), "compile_seconds": time.monotonic() - started}
            binary.with_name("build.json").write_text(json.dumps(meta, indent=2) + "\n")
            os.environ["ARC2_CPP_BINARY"] = str(binary)
            return {**base, "status": "ready", "binary": str(binary), "cached": False, "compile_seconds": meta["compile_seconds"]}
    except (OSError, TimeoutError) as exc:
        return {**base, "status": "error", "reason": str(exc)}
    finally:
        temporary.unlink(missing_ok=True)


def _grid(value) -> list[list[int]]:
    if hasattr(value, "tolist"):
        value = value.tolist()
    if not isinstance(value, list) or not 1 <= len(value) <= 30:
        raise ValueError("Grid must contain 1..30 rows")
    width = len(value[0]) if isinstance(value[0], list) else 0
    if not 1 <= width <= 30:
        raise ValueError("Grid must contain 1..30 columns")
    result = []
    for row in value:
        if not isinstance(row, list) or len(row) != width:
            raise ValueError("Grid must be rectangular")
        if any(type(c) is not int or not 0 <= c <= 9 for c in row):
            raise ValueError("Grid colors must be integers in 0..9")
        result.append(row.copy())
    return result


def _sanitized_task(task: dict) -> dict:
    # This allowlist is the only route from the caller's task into the backend.
    # In particular, do not copy whole test dictionaries or inspect their output.
    train = [{"input": _grid(p["input"]), "output": _grid(p["output"])} for p in task["train"]]
    test = [{"input": _grid(p["input"])} for p in task["test"]]
    if not train or not test:
        raise ValueError("At least one demonstration and test input are required")
    return {"train": train, "test": test}


def _parse_candidates(path: Path, expected_index: int, training_count: int) -> list[tuple[list, float, int]]:
    if not path.is_file():
        return []
    lines = path.read_text(errors="replace").splitlines()
    if not lines or lines[0] != f"00000000_{expected_index}":
        return []
    result = []
    for line in lines[1:]:
        try:
            encoded, rawscore, match_count = line.split()
            if not encoded.startswith("|") or not encoded.endswith("|"):
                continue
            rows = encoded[1:-1].split("|")
            if any(not row or not row.isascii() or not row.isdigit() for row in rows):
                continue
            grid = _grid([[int(c) for c in row] for row in rows])
            score, matches = float(rawscore), int(match_count)
            if not math.isfinite(score) or not 0 <= matches <= training_count:
                continue
            result.append((grid, score, matches))
        except (ValueError, TypeError):
            continue
    return result


def _run_limited(binary: str, cwd: Path, index: int, depth: int, seconds: float, memory_mb: int) -> dict:
    import resource

    def limits():
        address = int(memory_mb * 1024 * 1024)
        resource.setrlimit(resource.RLIMIT_AS, (address, address))
        cpu = max(1, int(math.ceil(seconds)))
        resource.setrlimit(resource.RLIMIT_CPU, (cpu, cpu + 1))
        resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
        resource.setrlimit(resource.RLIMIT_FSIZE, (16 * 1024 * 1024, 16 * 1024 * 1024))

    started = time.monotonic()
    log = cwd / f"stderr_{index}_{depth}.log"
    event = {"test_index": index, "depth": depth, "budget_seconds": seconds}
    try:
        with log.open("wb") as err:
            # No new session: the outer task-worker process group owns this
            # process too. The C++ program itself does not spawn descendants.
            proc = subprocess.Popen([binary, str(index), str(depth)], cwd=cwd, stdout=subprocess.DEVNULL,
                                    stderr=err, preexec_fn=limits)
            try:
                code = proc.wait(timeout=max(0.001, seconds))
                event.update(status="complete" if code == 0 else "failed", returncode=code)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait()
                event.update(status="timeout", returncode=proc.returncode)
        if event["status"] == "failed":
            event["stderr_tail"] = log.read_text(errors="replace")[-1500:]
    except (OSError, subprocess.SubprocessError) as exc:
        event.update(status="failed", reason=str(exc))
    event["seconds"] = time.monotonic() - started
    return event


def solve_cpp(task: dict, seconds: float, max_memory_mb: int = 768) -> dict:
    """Generate ranked candidates without compiling, networking, or test labels.

    Returns parallel arrays ``predictions``, ``scores``, ``train_matches`` and
    ``training_exact``, each indexed by test input then candidate.  An empty
    candidate list requests fallback to the caller's symbolic solver.
    """
    started = time.monotonic()
    stop = started + max(0.0, float(seconds))
    ntests = len(task.get("test", [])) if isinstance(task, dict) else 0
    result = {"predictions": [[] for _ in range(ntests)], "scores": [[] for _ in range(ntests)],
              "train_matches": [[] for _ in range(ntests)], "training_exact": [[] for _ in range(ntests)],
              "diagnostics": {"vendor_commit": VENDOR_COMMIT, "runs": [], "memory_limit_mb": max_memory_mb}}
    diag = result["diagnostics"]
    if seconds <= 0:
        diag.update(status="budget_exhausted", seconds=0.0)
        return result
    if max_memory_mb <= 0:
        diag.update(status="invalid_limit", seconds=0.0)
        return result
    prepared = prepare_cpp_backend(compile_seconds=0)
    diag["source_sha256"] = prepared.get("source_sha256")
    if prepared["status"] != "ready":
        diag.update(status=prepared["status"], reason=prepared.get("reason"), seconds=time.monotonic() - started)
        return result
    try:
        safe_task = _sanitized_task(task)
    except (ValueError, TypeError, KeyError) as exc:
        diag.update(status="invalid_task", reason=str(exc), seconds=time.monotonic() - started)
        return result
    ntrain = len(safe_task["train"])
    pools: list[dict] = [{} for _ in range(ntests)]
    with tempfile.TemporaryDirectory(prefix="arc2_icecuber_") as temporary:
        folder = Path(temporary)
        (folder / "dataset" / "test").mkdir(parents=True)
        (folder / "output").mkdir()
        (folder / "dataset" / "test" / "00000000.json").write_text(json.dumps(safe_task, separators=(",", ":")))
        for depth in (1, 2, 3):
            for index in range(ntests):
                remaining = stop - time.monotonic()
                if remaining <= 0.02:
                    break
                cap = 1.5 if depth == 1 else 5.0 if depth == 2 else math.inf
                budget = min(cap, remaining / (ntests - index))
                event = _run_limited(prepared["binary"], folder, index, depth, budget, max_memory_mb)
                diag["runs"].append(event)
                # Salvage complete rows even if the process failed after writing
                # them; earlier completed depth files remain independent.
                for grid, score, matches in _parse_candidates(folder / "output" / f"answer_{index}_{depth}.csv", index, ntrain):
                    key = tuple(tuple(row) for row in grid)
                    current = pools[index].get(key)
                    if current is None or (matches, score) > (current[2], current[1]):
                        pools[index][key] = (grid, score, matches)
            if time.monotonic() >= stop:
                break
    for i, pool in enumerate(pools):
        candidates = sorted(pool.values(), key=lambda p: (-p[2], -p[1], p[0]))
        result["predictions"][i] = [p[0] for p in candidates]
        result["scores"][i] = [p[1] for p in candidates]
        result["train_matches"][i] = [p[2] for p in candidates]
        result["training_exact"][i] = [p[2] == ntrain for p in candidates]
    diag.update(status="complete" if all(result["predictions"]) else "partial",
                seconds=time.monotonic() - started, limits_enforced="RLIMIT_AS, RLIMIT_CPU, RLIMIT_FSIZE, wall-time",
                completed_depths=sum(e["status"] == "complete" for e in diag["runs"]))
    return result
