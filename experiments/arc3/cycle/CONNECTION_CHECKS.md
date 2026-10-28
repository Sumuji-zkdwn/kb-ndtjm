# Official ZIP and notebook connection checks

The reference is the Kaggle competition archive downloaded on 2026-10-29 JST:
`arc-prize-2026-arc-agi-3.zip`, SHA-256
`c72400a32db5e48da9014baf893b48016b300e9a6a77bd5d505de2b1ec61d645`.
It contains 25 public demo Python implementations and 25 metadata files.
The SDK wheels are `arc-agi 0.9.8` and `arcengine 0.9.3`.

The configured GPU source input is
`dfranzen/taaf-kaggle-source-bundle-copy`, archive SHA-256
`cd687f4bc10b2128ea9895024cd2e990b24a1070607a071901cccd1638606187`.
This is read from Kaggle itself; the current upstream GitHub checkout is not
substituted for the notebook's input dataset. Model weights are not downloaded by
the connection workflow.

## What is tested

- CPU uses the exact packaged notebook payload and the ZIP's original Agent
  implementation. An empty package initializer isolates optional LLM imports;
  the Agent methods are copied byte-for-byte.
- All 25 public demos can provide observations and accept actions through the CPU
  adapter. These checks use two decisions per game, explicitly separate from the
  full 1200-call regression runs.
- The baseline and memory notebook patches apply to their actual input source.
  Every resulting Python file parses. The patches are applied outside an enclosing
  Git checkout, reproducing the Kaggle bundle layout; skipped patches fail.
- GPU uses the input dataset's actual `taaf.game.Game` and `GameAPI` modules.
  Both notebook factories enumerate all 25 demos and execute an action on each.
  The optional TAAF package initializer is isolated, not its game implementation.
- The memory extension accepts real SDK frames using its original conversion
  helpers, records an executed action and rereads it without executing an action.
- A real loopback HTTP server runs the ZIP's original REST implementation in
  competition mode. Public games receive synthetic IDs. CPU's official Swarm and
  GPU's competition factory both use those IDs, execute actions, and close the
  scorecard. GPU games share one scorecard and tolerate missing human baselines.
- The exact CPU notebook policy also runs on ls20, ft09 and vc33 with its original
  1200-call cap, including the initialization RESET. This is a regression check.

The previous pinned local framework differs from this ZIP in the reasoning
transport method and optional registrations. Its Agent.main loop agrees, and the
CPU adapter overrides the differing transport method, but prior runs were not
described as byte-identical ZIP runs. The new `--official-zip` route resolves that
evidence gap without modifying historical notebooks or reports.

## Using the evidence

The `ARC3 official bundle connection checks` workflow runs CPU baseline and
`cpu-c8b-probe64` in separate jobs. Each job also checks both GPU notebook
interfaces. It records archive hashes, exact notebook code hashes, package
versions, checks and full-budget CPU regression results.

Set `connection_run_id` on a cycle request to import the matching artifact. A new
start or submission fails unless that report passed for the exact code and
official archive. A completed CPU regression can be reused only when notebook
bytes and declared execution settings match; the measured candidate ID and time
remain in the receipt. Changing a hypothesis/label never converts an old run into
a newly measured run. GPU baseline and memory still share the frozen V3 image and
input references; comparisons also require matching observed images and input
archive hashes.

The original notebooks remain in `notebooks/`. GPU profiles now use separate
`gpu-baseline-connected.ipynb` and `gpu-memory-connected.ipynb` copies. The
original factories used `environments_dir=""`; SDK 0.9.8 interprets that as the
current directory and merges discovered local games with the gateway catalog.
The derived factories use a fresh empty directory, which keeps gateway discovery
independent of current-directory contents. Both GPU copies share this fix.
Normal Save Version runs use a short connectivity budget (one pass, concurrency
four, at most two actions and 90 seconds per game, five-minute benchmark budget
after model startup). The
real competition branch retains the original full solver settings and budgets.

`cpu-c8b-probe64` is a separate
derived notebook with one policy parameter changed (96 to 64 stagnant decisions),
and an isolated temporary module directory. `DERIVED_CANDIDATES.json` records its
baseline and code hashes. It is a candidate, not an adopted improvement.

## Evidence boundary

This workflow does not run the GPU model server, perform a full GPU benchmark,
access hidden games, submit to the competition, or produce an official score.
Passing it demonstrates the tested observation/action and scorecard contracts.
The real GPU Notebook, official rerun and official score remain separate cycle
stages. Public demo success is not a generalization measurement.
