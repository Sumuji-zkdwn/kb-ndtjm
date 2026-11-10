# Scalar5 Forney workspace compaction — independent experiment (2026-11-11)

**Status:** experimental, opt-in; no completed full-DQI verifier or Kaggle score.

## Frozen comparison

- Base: PR #8 head `5a925d337d2354048412fb1cc8525ce580918f02`, in branch `wfs/dqi-bm-blindcoop-20261027`.
- Prior *successfully measured* candidate: 2,482 qubits, 715,786 static Toffoli-like gates; complete public DQI verifier success at fixed local salt, 102,400 shots, zero value/phase errors. This is **not** a measurement of the experiment.
- Saved source: `checkpoints/bm-blindcoop-allocations-20261027.json.gz`, SHA-256 `b3e1da07973a999798a4558f4fdbc386a9f0a34fcbd14591dfe02361b5768d97`.
- Independently decoded/replayed: 6,257 events; peak 2,482 at event 5,211 / operation 13,971,812, immediately upon Forney's 78-qubit allocation. Replaying the owner claims at event 5,212 gives:

| Owner | At peak |
| --- | ---: |
| syn input | 840 |
| stk reversal stack | 665 |
| bb BM bank | 444 |
| sig BM coefficients | 432 |
| held (includes three clean Em pivots) | 23 |
| new Forney workspace | 78 |
| **Total** | **2,482** |

This **does not** prove that other live wires are clean or borrowable. The three clean held pivots are already reused in the validated reference.

## Specific hypothesis

The scalar5 emitter does not use all the physical slots inherited from the old inverse66 workspace. Enumerate the *actual scalar5 emitted* forward/middle/erase operands and remove only canonical emitter wires 12..44 that are never read or written. In the physical 81-slot work array these correspond to `work[36 + canonical_index - 12]`. The old `work[80]` scratch is also not used in scalar5 (the surrounding root test uses `work[69:80]`).

Current expected unused positions: **58, 64, 65, 80**. The lightweight regression asserts those positions exactly; if the emitter changes, it fails closed.

The opt-in compiler flags are `--trace-phase5 --compact-scalar5-workspace`. The default remains unchanged. A logical 81-slot array is preserved, but unused entries become `None`. Remaining physical wires are allocated injectively; the **same three** proven-clean held Em pivots are borrowed. Only gates whose original operands are present in the emitted program are allowed to reference the new mapping.

Predicted peak (assuming no new peak elsewhere): **2,478 qubits**, four fewer than the measured reference. At unchanged error bound and Toffoli count, the Q² factor implies `1 - (2478/2482)² ≈ 0.3221%` lower DQI cost. This is a *projection*, not a verified performance improvement.

## Minimum independent checks

The lightweight workflow runs:

```sh
python experiments/audit_forney_allocation_trace.py
python -m unittest discover -s experiments -p 'test_forney_scalar5_compaction.py' -v
```

These verify the pinned ledger, lifetime/owner bookkeeping, omitted-slot operand exclusion, injectivity, borrowed-owner preservation, exact old allocation under default flags, and the existing local scalar5 Boolean-phase certificate.

The opt-in **full-circuit** build is *not* invoked automatically:

```sh
python research/bm_port/build_dqi.py --out build/bm-scalar5-compact --trace-phase5 --compact-scalar5-workspace --trace-allocations
python research/bm_port/build_dqi.py --out build/bm-scalar5-compact --parse
```

A complete DQI comparator, native Kickmix parser, unchanged published full verifier, replayed allocation audit *adapted for the new register mapping*, unchanged non-DQI ZIP members, and then held-out Kaggle validation remain necessary before calling the experiment successful. In particular, the existing PR #8 equality test and its hard-coded Q=2482 checkpoint must **not** be reused as if they certified the compact candidate. No secrets or Kaggle submission commands are present in this experimental workflow.
