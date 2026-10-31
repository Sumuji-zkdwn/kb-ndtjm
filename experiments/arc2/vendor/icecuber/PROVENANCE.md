# Optional C++ DSL backend provenance

Author: Johan S. Wind (`top-quarks`), *DSL solution to the ARC challenge* (2020).

- Upstream: https://github.com/top-quarks/ARC-solution
- Pinned commit: `9407072659de1270358c2ba34c527785214dd68b`
- License: MIT; upstream copyright and permission notice are in `LICENSE`.
- `SOURCE_MANIFEST.json` records the SHA-256 of each original file before the
  modifications below. It is provenance information, not a claim that the
  modified files retain the original hashes.

Only generic C++ source and headers are included. No dataset, output answers,
model weights, compiled executable, precompiled header, or historical Python
runner is included. In particular, upstream `src/tasks.cpp`, `src/evals.cpp`,
and their headers, which contain historical task-index-specific examples, are
excluded. Their evaluation entry points are not reachable or linked.

## Changes from the pinned source

1. Replaced `src/runner.cpp` with a compact inference-only adaptation of the
   upstream generic pipeline: normalize demonstration colors, infer sizes,
   enumerate pieces, compose pieces, deduce outer products, rank candidates.
   It reads only the test input. It removes evaluation/verdict routines, hidden
   output comparisons, visualization plumbing, and historical alternative
   entry points. Search depths 1, 2, and 3 preserve upstream cost thresholds
   10, 20, and 30. The three best distinct candidates are emitted per depth.
2. The inference runner additionally exports an explicit demonstration-match
   count for each candidate, by reconstructing that candidate's predictions on
   the original demonstration inputs and comparing their original outputs.
   This is empirical fit, not a generalization guarantee. The upstream raw
   score is also retained.
3. Restricted `src/read.cpp` to `./dataset/` within the wrapper's isolated
   temporary working directory. Removed its implicit legacy Kaggle path and
   sorted filenames. Capped a positive file-count limit safely.
4. The Python adapter supplies one generated `00000000.json`, retaining only
   demonstration input/output pairs and test inputs. No caller task ID or test
   output is passed. Upstream's reader already supports absent test outputs;
   its internal invalid-image placeholder is never passed into the search.
5. Removed the unused `cheatSize` helper and `evalNormalizeRigid` debug
   entry point and their declarations. Removed stale commented entry points
   from `main.cpp`. These functions were unreachable from inference.
6. Omitted unused progress and evaluation-scoring translation units. Compiler
   flags are C++17 and `-O2`, with filesystem linkage, and compilation occurs
   in a temporary cache. No architecture-specific flags or external downloads
   are required at inference time.

The Python adapter runs increasing depths and preserves files from completed
depths when a later process times out. Subprocess wall-time and POSIX memory/CPU
limits are enforced. Its C++ subprocess remains in the caller's process group
so an outer worker can terminate the complete group. Compilation is a separate
preparation step; this backend reports unavailable if preparation was not done.

## Intended use and limits

This is an optional independent candidate generator for a two-attempt ensemble.
The upstream README's historical ARC results are not ARC-AGI-2 results. No
accuracy on the ARC-AGI-2 public evaluation or Kaggle private tasks is implied
by including this backend. Fixed source revisions, offline execution, and
demonstration fit establish reproducibility, not competitive performance.
