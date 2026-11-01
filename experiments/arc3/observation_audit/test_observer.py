"""Offline recorder contracts. Stub harness tests are not a GPU execution."""
from __future__ import annotations

import io
import json
from types import SimpleNamespace as NS
import unittest

from observer import ObservationTape, freeze_grid, install_gpu_session_observer


def raw(frames, *, level=0, reset=False, game="fixture", state="NOT_FINISHED"):
    return NS(frame=frames, levels_completed=level, full_reset=reset,
              game_id=game, state=NS(name=state))


def action(name="UP", identifier=1, data=None):
    return NS(id=NS(name=name, value=identifier), data=data or {})


UP = {"id": 1, "name": "UP", "data": {}}
ZERO = ((0, 0),)
ONE = ((1, 0),)


class TapeTests(unittest.TestCase):
    def test_order_multiplicity_and_source_mutation_are_preserved(self):
        frames = [[[0, 0]], [[1, 0]], [[1, 0]], [[0, 0]]]
        description = {"id": 6, "name": "MOUSE", "data": {"x": 2, "y": 3}}
        tape = ObservationTape()
        packet = tape.record(raw(frames), action=description, before=ZERO)
        frames[1][0][0] = 9
        description["data"]["x"] = 99
        self.assertEqual(packet.frames, (ZERO, ONE, ONE, ZERO))
        self.assertEqual(json.loads(packet.action_json)["data"]["x"], 2)
        self.assertEqual(packet.endpoint, ZERO)

    def test_jsonl_retains_evicted_packets_and_action_subframe_order(self):
        sink = io.StringIO()
        tape = ObservationTape(max_packets=1, sink=sink)
        tape.record(raw([ONE, ZERO]), action=UP, before=ZERO, action_index=1)
        tape.record(raw([ZERO]), action=UP, before=ZERO, action_index=2)
        rows = [json.loads(line) for line in sink.getvalue().splitlines()]
        self.assertEqual([r["action_index"] for r in rows], [1, 2])
        self.assertEqual(rows[0]["frames"], [[[1, 0]], [[0, 0]]])
        self.assertEqual(tape.evicted_packets, 1)
        self.assertEqual(tape.streamed_packets, 2)
        self.assertEqual(tape.packets[0].sequence, 2)

    def test_reset_and_level_boundaries_are_not_joined(self):
        tape = ObservationTape()
        first = tape.record(raw([ZERO]), action=UP, before=ZERO, action_index=1)
        reset = tape.record(raw([ZERO], reset=True), action={"id": 0, "name": "RESET"},
                            before=ZERO, action_index=2, automatic=True)
        level = tape.record(raw([ZERO], level=1), action=UP, before=ZERO, action_index=3)
        self.assertEqual((first.segment, reset.segment, level.segment), (1, 2, 3))
        self.assertIn("reset", reset.boundary_before)
        self.assertTrue(reset.automatic)
        self.assertIn("level_change", level.boundary_before)
        self.assertEqual(tape.current_segment(), (level,))

    def test_game_and_missing_action_gap_are_explicit(self):
        tape = ObservationTape()
        tape.record(raw([ZERO]), action=UP, before=ZERO, action_index=1)
        packet = tape.record(raw([ONE], game="another"), action=UP, before=ONE, action_index=3)
        self.assertEqual(set(packet.boundary_before), {"game_change", "observation_gap", "action_index_gap"})

    def test_empty_response_is_not_a_fabricated_sample(self):
        tape = ObservationTape()
        empty = tape.record(raw([]), action=UP, before=ZERO)
        self.assertEqual(empty.frames, ())
        self.assertIsNone(empty.endpoint)
        self.assertIn("empty_packet", empty.boundary_before)
        next_packet = tape.record(raw([ZERO]), action=UP, before=ZERO)
        self.assertIn("observation_gap", next_packet.boundary_before)

    def test_cell_bound_discards_complete_packets_with_visible_accounting(self):
        sink = io.StringIO()
        tape = ObservationTape(max_cells=3, sink=sink)
        packet = tape.record(raw([ONE, ZERO]), action=UP, before=ZERO)
        self.assertEqual(packet.cells, 6)
        self.assertEqual(tape.packets, ())
        self.assertEqual((tape.retained_cells, tape.evicted_packets, tape.streamed_packets), (0, 1, 1))
        self.assertEqual(len(json.loads(sink.getvalue())["frames"]), 2)
        self.assertIsNone(tape._last[2])
        next_packet = tape.record(raw([ZERO]), action=UP, before=None)
        self.assertIn("observation_gap", next_packet.boundary_before)

    def test_bad_grids_fail_without_lossy_type_conversion(self):
        for grid in ([[1.9]], [[True]], [[16]], [[-1]], [[0], [0, 1]], []):
            with self.subTest(grid=grid), self.assertRaises(ValueError):
                freeze_grid(grid)

    def test_invalid_limits_are_rejected(self):
        for options in ({"max_packets": 0}, {"max_cells": 0}, {"max_packets": True}):
            with self.subTest(options=options), self.assertRaises(ValueError):
                ObservationTape(**options)

    def test_separate_captures_do_not_share_the_same_action_identity(self):
        tapes = [ObservationTape(), ObservationTape()]
        packets = [tape.record(raw([ZERO]), action=UP, before=ZERO,
                               action_index=1, received_monotonic_seconds=5.0)
                   for tape in tapes]
        self.assertEqual(packets[0].sequence, packets[1].sequence)
        self.assertNotEqual(packets[0].capture_session_id, packets[1].capture_session_id)
        self.assertEqual(packets[0].received_monotonic_seconds, 5.0)

    def test_sink_failure_does_not_erase_in_memory_evidence(self):
        class BrokenSink:
            def write(self, text):
                raise OSError("fixture disk full")
        tape = ObservationTape(sink=BrokenSink())
        packet = tape.record(raw([ONE]), action=UP, before=ZERO)
        self.assertEqual(tape.packets, (packet,))
        self.assertEqual(tape.sink_failures, 1)
        self.assertIn("disk full", tape.last_error)


class HookTests(unittest.TestCase):
    def make_session_type(self):
        class Session:
            def __init__(self, responses):
                self.responses = iter(responses)
                self.game = NS(current_state=NS(raw=raw([ZERO])))
                self.action_count = 0
                self.calls = []
                self.payloads = []

            def _execute_action(self, chosen, *, batch_index, batch_size,
                                automatic=False, generated_tokens=None, flush_viewer_payload=True):
                self.calls.append((chosen, batch_index, batch_size, automatic, generated_tokens, flush_viewer_payload))
                response = next(self.responses)
                if isinstance(response, Exception):
                    raise response
                self.action_count += 1
                self.game.current_state = NS(raw=response)
                payload = {"action_num": self.action_count, "automatic": automatic,
                           "batch_index": batch_index, "state": response.state.name}
                self.payloads.append(payload)
                return payload
        return Session

    def test_two_actions_and_auto_reset_capture_exactly_once_and_preserve_results(self):
        Session = self.make_session_type()
        original = Session._execute_action
        uninstall = install_gpu_session_observer(Session)
        try:
            session = Session([raw([ONE, ZERO]), raw([ONE]), raw([ZERO], reset=True)])
            a, b, reset = action(), action("MOUSE", 6, {"x": 1, "y": 0}), action("RESET", 0)
            for i, choice in enumerate((a, b, reset), 1):
                result = session._execute_action(choice, batch_index=i, batch_size=3,
                                                 automatic=(i == 3), generated_tokens=7)
                self.assertIs(result, session.payloads[-1])
            self.assertEqual(len(session.calls), 3)
            tape = session.observation_tape
            self.assertEqual(tape.received_packets, 3)
            self.assertEqual(tape.packets[0].frames, (ONE, ZERO))
            self.assertEqual([p.action_index for p in tape.packets], [1, 2, 3])
            self.assertEqual([p.batch_index for p in tape.packets], [1, 2, 3])
            self.assertTrue(tape.packets[-1].automatic)
            self.assertIn("reset", tape.packets[-1].boundary_before)
            self.assertTrue(all(p.elapsed_seconds >= 0 for p in tape.packets))
            received = [p.received_monotonic_seconds for p in tape.packets]
            self.assertEqual(received, sorted(received))
        finally:
            uninstall()
        self.assertIs(Session._execute_action, original)

    def test_original_exception_is_not_retried_or_replaced(self):
        Session = self.make_session_type()
        error = RuntimeError("fixture game error")
        uninstall = install_gpu_session_observer(Session)
        try:
            session = Session([error, raw([ZERO])])
            with self.assertRaises(RuntimeError) as caught:
                session._execute_action(action(), batch_index=1, batch_size=1)
            self.assertIs(caught.exception, error)
            self.assertEqual(len(session.calls), 1)
            self.assertEqual(session.observation_tape.received_packets, 0)
            session._execute_action(action(), batch_index=1, batch_size=1)
            self.assertIn("capture_gap", session.observation_tape.packets[-1].boundary_before)
            self.assertEqual(session.observation_tape.action_errors, 1)
        finally:
            uninstall()

    def test_capture_error_preserves_policy_payload_and_marks_next_gap(self):
        Session = self.make_session_type()
        uninstall = install_gpu_session_observer(Session)
        try:
            session = Session([raw([[[99, 0]]]), raw([ZERO])])
            result = session._execute_action(action(), batch_index=1, batch_size=1)
            self.assertIs(result, session.payloads[0])
            self.assertEqual(len(session.calls), 1)
            self.assertEqual(session.observation_tape.capture_failures, 1)
            session._execute_action(action(), batch_index=1, batch_size=1)
            self.assertEqual(len(session.calls), 2)
            self.assertIn("capture_gap", session.observation_tape.packets[-1].boundary_before)
        finally:
            uninstall()

    def test_factory_error_still_executes_once(self):
        Session = self.make_session_type()
        def broken_factory():
            raise OSError("fixture recorder unavailable")
        uninstall = install_gpu_session_observer(Session, tape_factory=broken_factory)
        try:
            session = Session([raw([ZERO])])
            result = session._execute_action(action(), batch_index=1, batch_size=1)
            self.assertIs(result, session.payloads[0])
            self.assertEqual(len(session.calls), 1)
            self.assertIn("recorder unavailable", session.observation_capture_error)
        finally:
            uninstall()

    def test_double_installation_is_rejected(self):
        Session = self.make_session_type()
        uninstall = install_gpu_session_observer(Session)
        try:
            with self.assertRaises(ValueError):
                install_gpu_session_observer(Session)
        finally:
            uninstall()

    def test_equal_summary_order_collision_survives_a_later_action_on_the_tape(self):
        from pinned_sources import load_gpu_observation_functions
        gpu = load_gpu_observation_functions()
        left_first = [[[1, 0]], [[1, 1]], [[0, 0]]]
        right_first = [[[0, 1]], [[1, 1]], [[0, 0]]]
        chains = [gpu["_animation_chain"](ZERO, NS(raw=raw(packet)))
                  for packet in (left_first, right_first)]
        self.assertEqual(gpu["summarize_animation"](chains[0]),
                         gpu["summarize_animation"](chains[1]))
        Session = self.make_session_type()
        uninstall = install_gpu_session_observer(Session)
        try:
            sessions = [Session([raw(packet), raw([ZERO])])
                        for packet in (left_first, right_first)]
            for session in sessions:
                session._execute_action(action(), batch_index=1, batch_size=2)
                session._execute_action(action(), batch_index=2, batch_size=2)
            self.assertEqual(sessions[0].payloads, sessions[1].payloads)
            self.assertEqual(sessions[0].observation_tape.packets[-1].frames,
                             sessions[1].observation_tape.packets[-1].frames)
            self.assertNotEqual(sessions[0].observation_tape.packets[0].frames,
                                sessions[1].observation_tape.packets[0].frames)
            self.assertEqual([len(s.calls) for s in sessions], [2, 2])
        finally:
            uninstall()


if __name__ == "__main__":
    unittest.main()
