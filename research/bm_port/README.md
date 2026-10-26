# Conservative BM with variable-mask WFS/Forney

This complete `dqi.kmb` replaces the EEA decoder with a conservative adaptation
of the Apache-2.0 Berlekamp–Massey implementation from
[`andigu/uncompute`](https://github.com/andigu/uncompute/tree/64b5a13aa249f1360846657392e6c66817b26d0f/tasks/dqi-reed-solomon/circuits/discovered).
It is an attributed adaptation, not a claim to have discovered BM or the public
implementation. `provenance.json` pins the unchanged vendor files and support
modules; `check_provenance.py` checks their SHA-256 digests. Original license and
documentation are retained. Our adapter and integration are outside `vendor/`.

## Exact interface and phase mapping

| Interface | Circuit mapping |
| --- | --- |
| `S0` … `S69` | Quantum wires `12*i + bit`, little-endian 12-bit words |
| `E0` … `E4094` | Read-only classical bits `12*j + bit` |
| Private measurements | Bits 49140 (BM/root cleanup), 49141 (inverse66 cleanup) |
| Syndrome field | Google polynomial `0x1053`, primitive element 2 |
| BM internal field | Public polynomial `0x10eb`, embedded by root 52 in the Google field |
| Output | All S words restored, scratch clean, phase `(-1)^(sum_j E_j dot e_j)` |

The embedding is checked on all 4096 field values and all 144 basis-product
pairs. This is a field isomorphism; it does not relabel the error positions.
After BM, normalized locator coefficients and omega are converted back to the
Google basis. For position `j`, `z = 2^(-j)` and the sweep evaluates
`D = z*sigma'(z)`, `N = z*omega(z)`. At a locator root, `N/D = e_j`.
The existing WFS kernel represents `root * E_j dot (U * V^2)`; setting `U=N`
and `V=sqrt(D^-1)` gives the required phase. The square-root/square adapters
are exhaustive-checked linear inverses; the WFS kernel and inverse66 have
their existing exact local checks. The 4095 constant advances return all
coefficient registers to their starting state before uncomputation.

The public source's fixed phase mask, measured coefficient clipping, one-slot
reversal stack, and approximate Psi/Bezout sweep are **not used**. All reachable
coefficient slots and the full 35-slot reversal stack are retained. The new
Forney sweep uses every runtime E mask, including zero and arbitrary bit masks.
The allocator never resets scratch on allocation or release, so a dirty
workspace cannot be hidden by recycling. Private HMR tokens reject stale reuse.

## Validation and limits

`build_dqi.py --out build/bm-conservative` emits a complete binary circuit,
generation counts, hash, and local inverse certificates. The existing
`run_wfs_gates.py` runs **candidate → smoke → full-package**. For BM CI, full
runs use 1024 shots per batch while retaining all 102400 shots and confidence
`log2_delta=-128`; v1.0 is freshly checked with the same batch size and seed.
No cached comparison measurement is used. Missing published verifier files
produce explicit `NOT_RUN` stages. Nothing submits to Kaggle.

`bm_edge_verify.py` additionally checks 55 explicit error patterns, including a
weight-35 cyclic subgroup with 34 initial zero syndromes, cancellation pairs,
and zero/all/single/random masks. These targeted regressions are separate from
the official distributional measurement. Local identities do not constitute a
formal proof of the complete BM implementation; full verification remains
empirical and uses a public, non-secret seed, not Kaggle's held-out evaluation.

Release v1.0 and the preceding multiply42 candidate remain intact. Packaging
replaces only `dqi.kmb` and verifies that all other 12 ZIP members are bytewise
identical to v1.0. A checkpoint and Actions artifact identify each measured
candidate. The preserved vendor README describes upstream experiments and
must not be mistaken for measurements of this candidate.
