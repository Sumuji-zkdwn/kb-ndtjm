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

The script was first syntax-checked and smoke-tested with a local compatibility
facade only. It has since run from an actual private checkout, both in GitHub
Actions and in a separate cloud container (see the update below).

## GitHub Actions: runner blocker resolved (update 2026-11-07 JST)

### Earlier failures (before any step executed)

- [42246647140](https://github.com/Sumuji-zkdwn/kb-ndtjm/actions/runs/42246647140)
- [42246825031](https://github.com/Sumuji-zkdwn/kb-ndtjm/actions/runs/42246825031) (attempts 1–2)
- [42248939126](https://github.com/Sumuji-zkdwn/kb-ndtjm/actions/runs/42248939126) (after switching ubuntu-24.04 → ubuntu-latest)

These failed with `runner_id=0` and zero steps. The cause was not identified
from the repository side.

### Successful run

[42249545669](https://github.com/Sumuji-zkdwn/kb-ndtjm/actions/runs/42249545669)
(run #22, attempt 3, 2026-11-06 17:02 UTC), commit `5b6550b`, workflow
`wfs-local.yml`. Both jobs passed:

- **Build and prove local kernel**: extracted WFS loop (unit tests, three
  cycles, `audit --recheck`), `tools/verify_wfs_loop_local.py` original-source
  parity, KMx generation with exact ANF phase/restoration check, baseline v1.0
  archive comparison, artifact upload.
- **Parse KMx with Kickmix**: pinned upstream Kickmix install and parsing of
  all three local KMx kernels.

The PR head `0457f69` differs from `5b6550b` only in this document and in
`.github/workflows/operator-loop-growth.yml`. Neither is executed by
`wfs-local.yml`, so the result above covers the head's verification code.

### Independent re-execution of the exact head

At `0457f69`, in a separate cloud container (Python 3.13):

- `python -m unittest discover -s tests -p 'test_loop*.py'`: 5 tests OK
- `python -m loopcore run --domain wfs` ×4: cycles 1–3 verified (432, 520,
  522 ops), 4th returned `exhausted`; `audit --recheck` passed
- `python tools/verify_wfs_loop_local.py`: `PASS`, totals `[432, 520, 522]`
- `python quantum/wfs_mobile_ci.py`: completed successfully

### Still not verified

- `.github/workflows/operator-loop-growth.yml` runs only on push to `main`,
  on its schedule, or by manual dispatch. It has never executed. The target
  branch `autonomy/verified-wfs-operator-loop` exists at `c5e5865`.
- Local WFS correctness is not full DQI correctness, the official DQI
  verifier, or official competition scoring. No Kaggle submission was made.
