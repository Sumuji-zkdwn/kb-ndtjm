"""Regression checks on exact production observation code, not a new game score."""
from __future__ import annotations

import json
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest

from pinned_sources import (
    PINNED, load_cpu_observation, load_gpu_observation_functions, source_report,
)


def token(value: int) -> list[list[int]]:
    return [[int(index == value + 1) for index in range(3)]]


def spin_packet(x: int, u: int) -> list[list[list[int]]]:
    return [token(value) for value in (x, -u, -x, u)]


class PinnedSourceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.Observation = load_cpu_observation()
        cls.gpu = load_gpu_observation_functions()

    def test_exact_notebook_fingerprints(self):
        report = source_report()
        for kind in PINNED:
            self.assertEqual(report["notebooks"][kind]["sha256"], PINNED[kind][1])
        self.assertEqual(report["full_gpu_runtime_test"], "NOT_RUN")

    def test_modified_notebook_is_rejected_before_extraction(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / "altered.ipynb"
            path.write_text('{"cells": []}')
            with self.assertRaisesRegex(ValueError, "SHA-256 differs"):
                load_gpu_observation_functions(path)

    def test_cpu_final_frame_projection_merges_distinct_synthetic_spin_packets(self):
        # Synthetic H states (1,0) and (-1,0), encoded by token position,
        # have different ordered packets but equal final observations.
        packets = [spin_packet(1, 0), spin_packet(-1, 0)]
        observations = [self.Observation.from_frame(SimpleNamespace(
            frame=packet, available_actions=[1], state="NOT_FINISHED", levels_completed=0,
        )) for packet in packets]
        self.assertNotEqual(packets[0], packets[1])
        self.assertEqual(observations[0].key(), observations[1].key())
        self.assertNotEqual(token(1), token(-1))  # next H observation differs

    def test_gpu_summary_merges_order_but_immediate_animation_chain_does_not(self):
        before = ((0, 0),)
        packets = [
            [[[1, 0]], [[1, 1]], [[0, 0]]],
            [[[0, 1]], [[1, 1]], [[0, 0]]],
        ]
        chains = [self.gpu["_animation_chain"](
            before, SimpleNamespace(raw=SimpleNamespace(frame=packet)),
        ) for packet in packets]
        self.assertNotEqual(chains[0], chains[1])
        self.assertEqual(chains[0][-1], chains[1][-1])
        summaries = [self.gpu["summarize_animation"](chain) for chain in chains]
        self.assertEqual(summaries[0], summaries[1])
        self.assertEqual(summaries[0], {"frames": 3, "transient_pixels": 2,
                                       "transient_bbox": [0, 0, 0, 1]})

    def test_gpu_consecutive_collapse_loses_repeated_frame_multiplicity(self):
        before, changed = ((0,),), ((1,),)
        short = [before, changed, before]
        longer_dwell = [before, before, changed, before]
        self.assertNotEqual(short, longer_dwell)
        self.assertEqual(self.gpu["collapse_frames"](before, short),
                         self.gpu["collapse_frames"](before, longer_dwell))

    def test_gpu_nonadjacent_repeated_frame_remains_an_ordered_transition(self):
        before, changed = ((0,),), ((1,),)
        self.assertEqual(self.gpu["collapse_frames"](before, [changed, before]),
                         [before, changed, before])

    def test_saved_sc25_projection_retains_five_changes_despite_equal_endpoints(self):
        # This is a projection reconstructed from an actual saved timeline,
        # already after the upstream consecutive duplicate collapse. It is
        # not a new game run, a full-frame replay, or a four-phase H orbit.
        fixture = json.loads((Path(__file__).parent / "fixtures"
                              / "sc25_observed_projection.json").read_text())
        before = (tuple(fixture["before"]),)
        frames = [[row] for row in fixture["returned_frames_after_consecutive_duplicate_collapse"]]
        chain = self.gpu["_animation_chain"](
            before, SimpleNamespace(raw=SimpleNamespace(frame=frames)),
        )
        self.assertEqual(chain[0], chain[-1])
        self.assertEqual(sum(left != right for left, right in zip(chain, chain[1:])), 5)
        self.assertEqual(self.gpu["summarize_animation"](chain), {
            "frames": 5, "transient_pixels": 4, "transient_bbox": [0, 0, 0, 3],
        })
        self.assertEqual(fixture["observed_animation_summary"]["frames"], 5)
        self.assertEqual(fixture["observed_animation_summary"]["transient_pixels"], 36)
        self.assertFalse(fixture["observed_endpoint_metrics"]["board_changed"])


if __name__ == "__main__":
    unittest.main()
