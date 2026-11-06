# WFS operator loop: offline evidence and GitHub runner blocker

Date: 2026-11-07 JST. Scope: private PR #16 (`chatgpt/operator-loop-reentry-20261107`).

## Independently reproduced outside GitHub Actions

A local Python 3.13.5 run of the **previously extracted** operator-loop
package passed 11 unit tests and recomputed all three WFS local phase-kernel
candidates through three feedback cycles, including a fresh audit of the
hash-linked ledger. Exact Boolean ANF, register restoration and 120 seeded
sample checks passed for each candidate.

| Variant | Polynomial | Scale | Total ops | Conditional CX | CCZ | Other |
| --- | --- | --- | ---: | ---: | ---: | --- |
| google | 0x1053 | 1 | 432 | 288 | 12 | 132 CX |
| public | 0x10eb | 1 | 520 | 288 | 12 | 220 CX |
| scaled52 | 0x1053 | 0x52 | 522 | 288 | 12 | 210 CX + 12 SWAP |

Audit: three recorded cycles and then exhausted; recomputed domain checks
passed. The local extracted code's own SHA-256 was recorded. **This is not
an execution of the exact PR #16 source**: the extracted WFS adapter was
reconstructed from the original private algorithm. Therefore do not use
this observation as a passing GitHub CI check.

## Current PR verifier, runnable without GitHub-hosted minutes

`python tools/verify_wfs_loop_local.py --output verification/wfs-loop-local.json`

The new script is designed to execute the **actual private source**
`quantum/wfs_mobile_ci.py` and the **actual private adapter**
`loopcore/adapters/wfs.py` together. It compares the generated instructions
byte-for-byte after the KMx header, invokes the original ANF verifier and
fixed-seed sample test, checks 3 re-entry cycles, verifies history, and records
the source hashes. No third-party packages, internet, credentials or Kaggle
submission are required.

The script was syntax-checked and smoke-tested with a local compatibility
facade, **not** with an actual PR #16 checkout. Its exact-head result remains
unconfirmed until this script runs from the private repository checkout.

## GitHub Actions: blocked before executing steps

The original push runs:
- [42246647140](https://github.com/Sumuji-zkdwn/kb-ndtjm/actions/runs/42246647140)
- [42246825031](https://github.com/Sumuji-zkdwn/kb-ndtjm/actions/runs/42246825031)

Both failed before executing any steps. A retry of #42246825031 also failed
before running code. The runner image was changed from ubuntu-24.04 to
ubuntu-latest; [42248939126](https://github.com/Sumuji-zkdwn/kb-ndtjm/actions/runs/42248939126)
still failed before its first step. This is consistent with an Actions runner
allocation / account setting / quota or billing issue, but no specific cause
has been verified because the connection does not expose GitHub's billing and
runners administrative pages.

Do **not** merge PR #16 or report WFS CI success solely on the external
extracted-package checks. When the runner can execute jobs, inspect its
exact-head result and original Kickmix parser stage separately. Local
WFS correctness is not full DQI correctness or official competition scoring.
