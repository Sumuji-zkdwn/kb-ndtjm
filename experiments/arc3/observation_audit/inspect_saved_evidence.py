"""Inspect the historical ARC3 artifact locally; no APIs, execution, or submissions.

Usage: python inspect_saved_evidence.py ARTIFACT_ZIP_OR_DIRECTORY
       [--out NEW_REPORT_JSON] [--fixture-out NEW_FIXTURE_JSON]

ZIP input must match the published archive hash. Directory input has no archive
hash guarantee; the exact sc25 log and manifest-pinned notebook are checked.
"""
from __future__ import annotations

import argparse
import ast
from collections import Counter
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import zipfile


ARTIFACT_SHA256 = "13614fe9725bae81c244e0d89b370ab6cb3fbce85f20fb8b305a3af07273b785"
SC25_LOG_SHA256 = "7546033b08b703b16fa2bdc33911b24121831acfd424e96dcdb5ce8cccd9debb"
BASELINE = "gpu-baseline/ready-v2"
MEMORY = "gpu-memory/ready-v2-memory"
SC25_LOG = BASELINE + "/evidence/notebook-output/prompts/sc25-635fd71a_p0.log"
ARTIFACT_URL = (
    "https://github.com/Sumuji-zkdwn/kb-ndtjm/actions/runs/40846700062"
    "/artifacts/12885411756"
)


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _read_source(source: Path) -> tuple[dict[str, bytes], dict]:
    """Read without extracting archives or writing into the input directory."""
    if source.is_dir():
        files = {
            p.relative_to(source).as_posix(): p.read_bytes()
            for p in sorted(source.rglob("*")) if p.is_file()
        }
        provenance = {"input_kind": "extracted_directory", "archive_hash_verified": False}
    else:
        archive = source.read_bytes()
        if _sha(archive) != ARTIFACT_SHA256:
            raise ValueError("Artifact ZIP SHA256 differs from the pinned historical archive")
        with zipfile.ZipFile(source) as zf:
            names = [n for n in zf.namelist() if not n.endswith("/")]
            if len(names) != len(set(names)):
                raise ValueError("Duplicate ZIP members")
            for name in names:
                p = PurePosixPath(name)
                if p.is_absolute() or ".." in p.parts or "\\" in name:
                    raise ValueError("Unsafe archive member path")
            files = {name: zf.read(name) for name in names}
        provenance = {"input_kind": "zip", "archive_hash_verified": True,
                      "sha256": _sha(archive), "bytes": len(archive)}
    if _sha(files[SC25_LOG]) != SC25_LOG_SHA256:
        raise ValueError("sc25 prompt log differs from the pinned observed source")
    return files, provenance


def _sc25_fixture(log: bytes) -> dict:
    """Derive the four-block projection from the printed coordinate changes."""
    text = log.decode("utf-8")
    lines = text.splitlines()
    start = next(i for i, line in enumerate(lines) if re.fullmatch(r"UP \d+", line))
    frame_count = int(lines[start].split()[1])
    timeline = lines[start + 1:start + 1 + frame_count]
    patches: list[tuple[set[tuple[int, int]], list[int]]] = []
    states: list[dict[tuple[int, int], str]] = []
    current: dict[tuple[int, int], str] = {}
    for number, line in enumerate(timeline, 1):
        match = re.fullmatch(r"(\d+) rows (\d+)-(\d+), cols (\d+)-(\d+) (.+)", line)
        if not match or int(match[1]) != number:
            raise ValueError("Unexpected sc25 timeline ordering or format")
        bbox = [int(match[2]), int(match[4]), int(match[3]), int(match[5])]
        changes = ast.literal_eval(match[6])
        if isinstance(changes, list):
            if len(changes) != 1 or not changes[0].startswith("W>N @ "):
                raise ValueError("Unexpected sc25 explicit color transition")
            positions = changes[0].removeprefix("W>N @ ")
            if not re.fullmatch(r"\(\d+,\d+\)(?: \(\d+,\d+\))*", positions):
                raise ValueError("Unparsed coordinate data in sc25 timeline")
            cells = {tuple(map(int, x)) for x in re.findall(r"\((\d+),(\d+)\)", positions)}
            rectangle = {(r, c) for r in range(bbox[0], bbox[2] + 1)
                         for c in range(bbox[1], bbox[3] + 1)}
            if cells != rectangle or any(p in current for p in cells):
                raise ValueError("Unexpected overlap or incomplete sc25 region")
            patches.append((cells, bbox))
            current.update({p: "N" for p in cells})
        elif isinstance(changes, dict):
            if number != frame_count or changes != {"N>W": len(current)}:
                raise ValueError("Final counted reset does not match the explicit cells")
            if any(color != "N" for color in current.values()):
                raise ValueError("Final reset has incompatible previous colors")
            current = {p: "W" for p in current}
        else:
            raise ValueError("Unexpected sc25 timeline payload")
        states.append(dict(current))
    if len(patches) != 4 or any(len(cells) != 9 for cells, _ in patches):
        raise ValueError("The observed projection requires four complete 3x3 patches")
    all_cells = set().union(*(p[0] for p in patches))
    if current != {p: "W" for p in all_cells}:
        raise ValueError("The recorded timeline does not return to its initial colors")
    projected = []
    for state in states:
        projected.append([int(all(state.get(p, "W") == "N" for p in cells))
                          for cells, _ in patches])
    results = []
    for line in text.split("[TURN TRANSCRIPT SO FAR]", 1)[0].splitlines():
        if line.startswith("{'executed':"):
            value = ast.literal_eval(line)
            if value.get("action_display") == "UP" and value.get("action_num") == 1:
                results.append(value)
    if len(results) != 1:
        raise ValueError("Expected one logged first UP result")
    result = results[0]
    animation = result["animation"]
    if animation["frames"] != frame_count or animation["transient_pixels"] != len(all_cells):
        raise ValueError("Timeline and animation summary disagree")
    centres = [((b[0] + b[2]) / 2, (b[1] + b[3]) / 2) for _, b in patches]
    top = min(range(4), key=lambda i: centres[i][0])
    bottom = max(range(4), key=lambda i: centres[i][0])
    left = min(range(4), key=lambda i: centres[i][1])
    right = max(range(4), key=lambda i: centres[i][1])
    labels = {top: "top", bottom: "bottom", left: "left", right: "right"}
    if len(labels) != 4:
        raise ValueError("Cannot assign the four observed spatial labels")
    return {
        "schema": "arc3-observed-projection-v1",
        "scope": "historical normal Save Version connectivity; not an official evaluation episode",
        "game_id": "sc25-635fd71a", "action": "UP", "action_num": result["action_num"],
        "source": {"repository": "Sumuji-zkdwn/kb-ndtjm", "run_id": 40846700062,
                   "artifact_id": 12885411756, "artifact_sha256": ARTIFACT_SHA256,
                   "artifact_url": ARTIFACT_URL, "log_path": SC25_LOG,
                   "log_sha256": _sha(log), "timeline_start_line": start + 1,
                   "timeline_excerpt": "\n".join(lines[start:start + 1 + frame_count]) + "\n"},
        "projection": {"meaning": "1: all cells of the block are N (light green); 0: W (white). Derived from logged coordinates, not full-frame replay.",
                       "ordered_regions": [{"name": labels[i], "bbox": b, "cells": len(cells)}
                                           for i, (cells, b) in enumerate(patches)]},
        "before": [0] * len(patches),
        "returned_frames_after_consecutive_duplicate_collapse": projected,
        "observed_endpoint_metrics": {k: result[k] for k in ("board_changed", "gameplay_changed", "no_op")},
        "observed_animation_summary": animation,
        "limitations": [
            "Raw engine frame dwell counts were already collapsed and cannot be recovered from this log.",
            "One action returned five distinct animation frames; this is not an observed four-action periodic orbit.",
            "The projection contains four regions, not the full numeric game frame.",
            "Endpoint information loss does not establish a WFS state map or improved gameplay.",
        ],
    }


def inspect_saved_evidence(source: Path) -> tuple[dict, dict]:
    files, input_verification = _read_source(source)
    def read_json(name: str):
        return json.loads(files[name])
    manifest = read_json(BASELINE + "/manifest.json")
    notebook_hash = _sha(files[BASELINE + "/submission.ipynb"])
    if notebook_hash != manifest["files"]["submission.ipynb"]:
        raise ValueError("Frozen notebook disagrees with its manifest")
    score = read_json(BASELINE + "/evidence/official-score.json")
    if score["candidate_id"] != manifest["candidate_id"]:
        raise ValueError("Official receipt belongs to another candidate")
    per_game, events = [], []
    prefix = MEMORY + "/evidence/notebook-output/artifacts/"
    for name in sorted(n for n in files if n.startswith(prefix) and n.endswith(".evidence.json")):
        data = read_json(name)
        events.extend(data["events"])
        per_game.append({"game_id": PurePosixPath(name).name.split("_p0")[0],
                         "events": len(data["events"]), "sha256": _sha(files[name]),
                         "endpoint_equal_events": [e["sequence"] for e in data["events"]
                                                   if e["before_grid"] == e["after_grid"]],
                         "witness_pairs": len(data.get("witness_pairs", []))})
    prompts = {}
    for series in (BASELINE, MEMORY):
        prefix = series + "/evidence/notebook-output/prompts/"
        names = sorted(n for n in files if n.startswith(prefix) and n.endswith("_p0.log"))
        annotations = {}
        for name in names:
            found = []
            text = files[name].decode("utf-8").split("[TURN TRANSCRIPT SO FAR]", 1)[0]
            for line in text.splitlines():
                m = re.search(r"The last executed action \(`(.+?)`\) animated over (\d+) frames", line)
                if m:
                    count = re.search(r"(\d+) cells changed and changed back", line)
                    found.append({"action": m[1], "frames_after_collapse": int(m[2]),
                                  "transient_pixels": int(count[1]) if count else None,
                                  "endpoint_gameplay_unchanged": "left the board area unchanged" in line})
            if found:
                annotations[PurePosixPath(name).name] = found
        prompts[series] = {"game_prompt_files": len(names),
                           "game_prompt_bytes": sum(len(files[n]) for n in names),
                           "explicit_animation_annotation_games": len(annotations),
                           "count_scope": "explicit annotations in saved latest prompts; not a total of all animations",
                           "annotations": annotations}
    fixture = _sc25_fixture(files[SC25_LOG])
    call_seconds = [e["observed_cost"]["engine_wall_seconds"] for e in events
                    if "engine_wall_seconds" in e.get("observed_cost", {})]
    call_counts = sorted({e["observed_cost"]["executed_engine_calls"] for e in events
                          if "executed_engine_calls" in e.get("observed_cost", {})})
    metadata_paths = set()
    def collect_metadata_paths(value, prefix=""):
        if isinstance(value, dict):
            for key, child in value.items():
                path = prefix + "." + key if prefix else key
                metadata_paths.add(path)
                if key not in ("before_grid", "after_grid"):
                    collect_metadata_paths(child, path)
    for event in events:
        collect_metadata_paths(event)
    timestamp_fields = sorted(p for p in metadata_paths if re.search(
        r"timestamp|datetime|(?:^|\.)(?:time|utc|action_time|wall_time)$|_at$", p))
    frame_timing_fields = sorted(p for p in metadata_paths if re.search(
        r"frame.*(?:duration|interval|spacing|timestamp|time)|(?:duration|interval).*frame", p))
    report = {
        "schema": "arc3-saved-evidence-audit-v1",
        "artifact": {"id": 12885411756, "run_id": 40846700062,
                     "published_sha256": ARTIFACT_SHA256, "url": ARTIFACT_URL,
                     "files": len(files), "input_verification": input_verification},
        "baseline_manifest": manifest, "frozen_notebook_sha256_verified": notebook_hash,
        "official_score": score,
        "baseline_normal_diagnostics": read_json(BASELINE + "/evidence/notebook-output/model-diagnostics.json"),
        "memory_normal_diagnostics": read_json(MEMORY + "/evidence/notebook-output/model-diagnostics.json"),
        "memory_snapshots": {
            "files": len(per_game), "events": len(events),
            "max_events_per_game": max((r["events"] for r in per_game), default=0),
            "actions": dict(Counter(e["action"]["name"] for e in events)),
            "continuity": dict(Counter(e["continuity"] for e in events)),
            "events_with_animation_metadata": sum("animation" in e["public_result"] for e in events),
            "endpoint_equal_events": sum(e["before_grid"] == e["after_grid"] for e in events),
            "witness_pairs": sum(r["witness_pairs"] for r in per_game),
            "witness_interpretation": "No stored witness is not proof that no indistinguishable states exist.",
            "timing": {
                "engine_wall_seconds": {"count": len(call_seconds),
                                        "min": min(call_seconds, default=None),
                                        "max": max(call_seconds, default=None)},
                "executed_engine_calls_distinct": call_counts,
                "meaning": "Duration of the engine call, NOT the inter-action interval or animation frame spacing.",
                "absolute_per_action_timestamps_recorded": bool(timestamp_fields),
                "absolute_action_timestamp_fields": timestamp_fields,
                "raw_frame_durations_recorded": bool(frame_timing_fields),
                "raw_frame_timing_fields": frame_timing_fields,
                "field_scope": "Metadata keys in all saved memory event records; no claim about other runtime logs.",
                "event_metadata_paths": sorted(metadata_paths),
            },
            "per_game": per_game,
        },
        "prompts": prompts,
        "sc25_fixture_log_sha256": fixture["source"]["log_sha256"],
        "evidence_limits": [
            "The 26.20 official receipt and normal Save Version traces describe different executions.",
            "Prompt snapshots are not complete raw episode recordings.",
            "Memory snapshots contain endpoint grids, at most two events per game, and no raw animation stack.",
            "Neither WFS state correspondence nor gameplay improvement is established.",
        ],
    }
    return report, fixture


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("--out", type=Path)
    parser.add_argument("--fixture-out", type=Path)
    args = parser.parse_args()
    destinations = [p for p in (args.out, args.fixture_out) if p is not None]
    if len({p.resolve() for p in destinations}) != len(destinations):
        parser.error("Output paths must be distinct")
    if any(p.exists() for p in destinations):
        parser.error("Output already exists; choose a new path to preserve earlier evidence")
    report, fixture = inspect_saved_evidence(args.source)
    for destination, value in ((args.out, report), (args.fixture_out, fixture)):
        if destination is not None:
            destination.parent.mkdir(parents=True, exist_ok=True)
            with destination.open("x", encoding="utf-8") as stream:
                json.dump(value, stream, ensure_ascii=False, indent=2)
                stream.write("\n")
    if args.out is None:
        print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
