"""Opt-in observation capture; no policy, game action, FFT, or submission code.

An API subframe index is an order label, not a physical time measurement.
Importing this module does not install the hook. The bounded in-memory tape
keeps complete packets; an optional JSONL sink can retain them after eviction.
"""
from __future__ import annotations

from collections import deque
from dataclasses import asdict, dataclass
from functools import wraps
import json
from numbers import Integral
import time
from typing import Any, TextIO
from uuid import uuid4


Grid = tuple[tuple[int, ...], ...]


def freeze_grid(grid: Any) -> Grid:
    """Copy a public ARC grid without palette arithmetic or deduplication."""
    if hasattr(grid, "tolist"):
        grid = grid.tolist()
    if not isinstance(grid, (list, tuple)) or not 0 < len(grid) <= 64:
        raise ValueError("Expected a nonempty grid of at most 64 rows")
    rows = []
    width = None
    for row in grid:
        if not isinstance(row, (list, tuple)) or not 0 < len(row) <= 64:
            raise ValueError("Expected a nonempty row of at most 64 cells")
        if width is None:
            width = len(row)
        if len(row) != width:
            raise ValueError("Ragged grid")
        if any(isinstance(v, bool) or not isinstance(v, Integral) or not 0 <= v <= 15 for v in row):
            raise ValueError("Expected integer ARC palette labels 0..15")
        rows.append(tuple(int(v) for v in row))
    return tuple(rows)


def freeze_frames(frames: Any) -> tuple[Grid, ...]:
    if frames is None:
        return ()
    if hasattr(frames, "tolist"):
        frames = frames.tolist()
    if not isinstance(frames, (tuple, list)):
        raise ValueError("Expected an ordered API frame packet")
    return tuple(freeze_grid(grid) for grid in frames)


def raw_endpoint(raw: Any) -> Grid | None:
    frames = getattr(raw, "frame", None)
    if frames is None or len(frames) == 0:
        return None
    return freeze_grid(frames[-1])


def action_description(action: Any, data: Any = None) -> dict[str, Any]:
    identifier = getattr(action, "id", action)
    name = getattr(identifier, "name", str(identifier))
    value = getattr(identifier, "value", identifier)
    if not isinstance(value, (str, int)):
        value = str(value)
    if data is None:
        data = getattr(action, "data", None)
    return {"id": value, "name": name, "data": dict(data or {})}


@dataclass(frozen=True)
class Packet:
    capture_session_id: str
    sequence: int
    segment: int
    boundary_before: tuple[str, ...]
    game_id: str
    action_json: str
    action_index: int | None
    batch_index: int | None
    batch_size: int | None
    automatic: bool
    levels_completed: int
    state: str
    full_reset: bool
    before: Grid | None
    frames: tuple[Grid, ...]
    elapsed_seconds: float | None
    received_monotonic_seconds: float | None
    source_kind: str

    @property
    def endpoint(self) -> Grid | None:
        return self.frames[-1] if self.frames else None

    @property
    def cells(self) -> int:
        return sum(len(row) for grid in self.frames for row in grid) + sum(len(row) for row in self.before or ())

    def as_json(self) -> dict[str, Any]:
        result = asdict(self)
        result["action"] = json.loads(result.pop("action_json"))
        result["schema"] = "arc3-observation-packet-v1"
        result["time_basis"] = "API response order; subframe tick durations unknown"
        return result


class ObservationTape:
    """Bounded raw-packet history with explicit eviction and capture failures.

    The default eight-packet window is a resource choice, not a WFS theorem.
    No finite tape is claimed to be a sufficient Markov state for an ARC game.
    """

    def __init__(self, *, max_packets: int = 8, max_cells: int = 262144,
                 sink: TextIO | None = None, source_kind: str = "raw_api_packet"):
        if type(max_packets) is not int or max_packets < 1 or type(max_cells) is not int or max_cells < 1:
            raise ValueError("Positive integer tape bounds are required")
        self.max_packets, self.max_cells = max_packets, max_cells
        self.sink, self.source_kind = sink, source_kind
        self.capture_session_id = uuid4().hex
        self._packets: deque[Packet] = deque()
        self._last: tuple[str, int, Grid | None, int | None] | None = None
        self._segment = 0
        self.received_packets = self.evicted_packets = self.retained_cells = 0
        self.streamed_packets = self.capture_failures = self.sink_failures = self.action_errors = 0
        self.last_error: str | None = None
        self._gap_pending = False

    @property
    def packets(self) -> tuple[Packet, ...]:
        return tuple(self._packets)

    def capture_failed(self, error: Exception) -> None:
        self.capture_failures += 1
        self.last_error = type(error).__name__ + ": " + str(error)
        self._gap_pending = True

    def record(self, raw: Any, *, action: dict[str, Any], before: Grid | None,
               action_index: int | None = None, batch_index: int | None = None,
               batch_size: int | None = None, automatic: bool = False,
               elapsed_seconds: float | None = None,
               received_monotonic_seconds: float | None = None) -> Packet:
        if raw is None:
            raise ValueError("No response to record")
        frames = freeze_frames(getattr(raw, "frame", None))
        before = None if before is None else freeze_grid(before)
        game = str(getattr(raw, "game_id", ""))
        levels = int(getattr(raw, "levels_completed", 0))
        state = getattr(raw, "state", "")
        state = str(getattr(state, "name", state))
        full_reset = bool(getattr(raw, "full_reset", False))
        action_json = json.dumps(action, sort_keys=True, separators=(",", ":"), allow_nan=False)
        boundary = []
        if self._last is None:
            boundary.append("initial")
        else:
            last_game, last_levels, last_endpoint, last_index = self._last
            if game != last_game:
                boundary.append("game_change")
            if levels != last_levels:
                boundary.append("level_change")
            if before is None or last_endpoint is None or before != last_endpoint:
                boundary.append("observation_gap")
            if action_index is not None and last_index is not None and action_index != last_index + 1:
                boundary.append("action_index_gap")
        if action.get("name") == "RESET" or action.get("id") == 0 or full_reset:
            boundary.append("reset")
        if self._gap_pending:
            boundary.append("capture_gap")
        if not frames:
            boundary.append("empty_packet")
        if boundary:
            self._segment += 1
        packet = Packet(self.capture_session_id, self.received_packets + 1, self._segment, tuple(boundary), game,
                        action_json, action_index, batch_index, batch_size, bool(automatic),
                        levels, state, full_reset, before, frames, elapsed_seconds,
                        received_monotonic_seconds, self.source_kind)
        self.received_packets += 1
        self._gap_pending = False
        self._last = (game, levels, packet.endpoint, action_index)
        self._packets.append(packet)
        self.retained_cells += packet.cells
        while len(self._packets) > self.max_packets or self.retained_cells > self.max_cells:
            self.retained_cells -= self._packets.popleft().cells
            self.evicted_packets += 1
        if not self._packets:
            # Do not retain an unaccounted endpoint after a too-large packet.
            # The next record explicitly starts with an observation gap.
            self._last = (game, levels, None, action_index)
        if self.sink is not None:
            try:
                self.sink.write(json.dumps(packet.as_json(), separators=(",", ":"), allow_nan=False) + "\n")
                self.sink.flush()
                self.streamed_packets += 1
            except Exception as error:
                # A recorder failure must not repeat an already executed action.
                self.sink_failures += 1
                self.last_error = type(error).__name__ + ": " + str(error)
        return packet

    def current_segment(self) -> tuple[Packet, ...]:
        return tuple(p for p in self._packets if p.segment == self._segment)

    def status(self) -> dict[str, Any]:
        return {"received_packets": self.received_packets, "retained_packets": len(self._packets),
                "retained_cells": self.retained_cells, "evicted_packets": self.evicted_packets,
                "streamed_packets": self.streamed_packets, "capture_failures": self.capture_failures,
                "sink_failures": self.sink_failures, "action_errors": self.action_errors,
                "last_error": self.last_error,
                "max_packets": self.max_packets, "max_cells": self.max_cells}


def install_gpu_session_observer(session_type: type, *, tape_factory=ObservationTape):
    """Opt in on a separately loaded GPU harness, never on import.

    Capture each completed _execute_action, including automatic RESET, before
    the next batch action. The original return object and action exceptions are
    preserved. Recorder errors are counted instead of retrying the game action.
    The tape is an instrumentation side channel; policy globals are unchanged.
    Returns an uninstall function. Full GPU/Kaggle validation is still required.
    """
    original = session_type._execute_action
    if getattr(original, "_observation_tape_hook", False):
        raise ValueError("Observation hook is already installed")

    @wraps(original)
    def observed(session, action, *args, **kwargs):
        tape = getattr(session, "observation_tape", None)
        before = None
        if tape is None:
            try:
                tape = tape_factory()
                session.observation_tape = tape
            except Exception as error:
                session.observation_capture_error = type(error).__name__ + ": " + str(error)
        if tape is not None:
            try:
                before = raw_endpoint(session.game.current_state.raw)
            except Exception as error:
                tape.capture_failed(error)
        started = time.monotonic()
        try:
            result = original(session, action, *args, **kwargs)
        except Exception:
            if tape is not None:
                tape.action_errors += 1
                tape._gap_pending = True
            raise  # Preserve the same exception; never retry an action.
        received = time.monotonic()
        elapsed = received - started
        if tape is not None:
            try:
                tape.record(session.game.current_state.raw, action=action_description(action),
                            before=before, action_index=session.action_count,
                            batch_index=kwargs.get("batch_index"), batch_size=kwargs.get("batch_size"),
                            automatic=kwargs.get("automatic", False), elapsed_seconds=elapsed,
                            received_monotonic_seconds=received)
            except Exception as error:
                tape.capture_failed(error)
        return result

    observed._observation_tape_hook = True
    session_type._execute_action = observed

    def uninstall():
        if session_type._execute_action is not observed:
            raise RuntimeError("Another wrapper replaced this observer; do not overwrite it")
        session_type._execute_action = original

    return uninstall
