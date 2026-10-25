# WFS → DQI: one-site integration checkpoint

2026-10-25 JST. This is a reproducible integration experiment, not a scored optimization.
Release v1.0, its tag and its submission.zip asset are never written by this implementation.

## Actual baseline evidence

- Baseline ZIP SHA-256: `04cf2fc7518e9cc2f9207f61b9421448a0b02368756c6b342fb4cea8c47b0f43`
- Extracted dqi.kmb SHA-256: `959471d05a26373b4f14ca0cae2d8639ea25f18170d9f6532139aa51ccc04995`
- KMB version 2; 886,118,180 bytes; 86,051,014 operations; 1,893 qubits; 49,154 classical bits.
- 70 S registers and 4,095 E registers, each 12 entries, in original order.
- Register convention: S[i][j] = q(12i+j), E[i][j] = b(12i+j), least significant coefficient first.
  S covers q0..839; E covers b0..49139. Internal quantum workspace is not an S register.
- Selected operation: the FIRST `@enter:gf_phase_by_product` / `@exit:gf_phase_by_product` pair.
  Only operation indices `[51505, 51763)` (zero based, excluding INFO_TAG boundaries) are replaced.

| Role | Baseline wiring | Evidence |
|---|---|---|
| U | q1740..1751 | decoded CZ_IF operands and exact product ANF |
| V | q1833..1844 | decoded CZ_IF operands and exact product ANF |
| c | b49140..49151 | preceding HMR q1821+i → b49140+i, i=0..11 |
| clean quantum scratch | q1821 | immediately preceding HMR resets it to zero |
| classical parity scratch | b49152 | no earlier write in the circuit; initially zero; restored zero |
| root r | constant 1 | selected baseline phase has no quantum root control |
| reduction polynomial | 0x1053 = x^12+x^6+x^4+x+1 | independently matched to decoded baseline ANF |

The mask comes from temporary measurement outcomes, **not E registers**. No claim is made that arbitrary E registers can substitute for these bits. No semantic assignment of all 62,306 phase blocks was performed; only the selected site was resolved and patched.

## Adapter and proof

The baseline implements `(-1)^parity(c & (U*V))`. Its original 258 instructions are
144 CZ_IF, 104 BIT_INVERT_IF and 10 BIT_STORE0. Temporary classical parity is clean at exit.

The existing WFS compiler implements `(-1)^(r*parity(c & (U*V^2)))`.
An unadapted insertion is incorrect. For this site:

1. Apply inverse Frobenius `V -> V^(2^11)` using a synthesized invertible linear circuit.
2. Use existing `compile_ops(0x1053, 1)`, specialized to `r=1`: CCZ(root,scratch,V[j]) becomes CZ(scratch,V[j]).
3. Apply the inverse linear adapter, restoring V.
4. Restore the baseline classical parity scratch to zero.

Since `(V^(2^11))^2=V` in GF(2^12), the phase becomes the required product phase.
The 36-variable GF(2) ANF evaluator checks the actual baseline, adapted replacement and
re-decoded replacement from the completed binary against the same 363-monomial phase.
It also checks quantum restoration, zero quantum scratch, unchanged mask and zero classical scratch.
The original 37-variable root-controlled WFS proof is run separately without weakening it.
The local proof assumes q1821=0 and b49152=0; the pinned baseline context supplies both.
No conditions are active at this boundary. Measurement operations and outcomes are retained.

The KMB has structure-of-arrays packets: opcodes, three/two/one-qubit operands,
classical targets, condition bits, angles and info tags. The generator adjusts only the relevant
array spans and header counters, then independently re-opens the candidate and byte-compares
every packet prefix/suffix. Register packets, all INFO_TAG data, all three-qubit operands,
all one-qubit operands, all angles, and every operation outside this one site remain unchanged.
It aborts on a different baseline hash, layout, phase or scratch lifetime.

## Candidate and cost limits

- Complete candidate: 886,121,285 bytes.
- Candidate SHA-256: `6079f1aeca6cf87a4ffbfa22110104c6fd5e588198c5d0e86f62409d757162ca`
- Replaced block: 535 operations = 230 CX + 4 SWAP + 288 CX_IF + 12 CZ + 1 BIT_STORE0.
- Whole circuit: 86,051,291 operations (+277); two-qubit operations +390; three-qubit operations unchanged.
- No added qubits, bits or registers. The other 12 submission ZIP members are untouched.
- **No improvement is claimed.** The Frobenius adapter and conditional parity construction add gates.
  Q and Toffoli-like counts are unchanged, so this checkpoint should not be expected to pass a strict cost-reduction requirement.
  The existing full-package gate refuses to package a candidate without measured cost reduction.

## Reproduce without submitting

```bash
python -m pip install numpy
python -m unittest discover -s quantum -p test_wfs_dqi_single_site.py -v
python quantum/wfs_dqi_single_site.py --baseline submission.zip --output build/integration
python quantum/wfs_dqi_single_site.py --output build/integration --parse
python quantum/run_wfs_gates.py --baseline submission.zip --candidate build/integration/dqi.kmb --stage full-package --data-root build/kaggle --out build/report
```

`--parse` requires upstream Kickmix pinned at Qualtran commit
`638777fac4379bc62e2a1e4a52cf1a1753895d48`, also installed by Actions.
Four regression tests include wrong mask endianness, absent adapter and omitted uncomputation.

The existing dqi-gated.yml workflow now builds this full candidate when candidate_release is empty.
It runs candidate → smoke → full-package with the existing dqi_gate.py, in order.
Its optional `--fetch-official` path only downloads published competition assets using the existing
KAGGLE_API_TOKEN secret. It has no submission command and no release-write permission.
If the token/files are unavailable, smoke and full-package reports explicitly say NOT_RUN;
`stages.json` then has `all_requested_gates_passed=false`, even if the CI run is green.
If smoke fails, full-package is NOT_RUN. Other validation failures are not silently skipped.

Actions artifacts (30-day retention):

- `dqi-wfs-one-site-unscored`: complete dqi.kmb for inspection, without claiming scoring eligibility.
- `dqi-checkpoint-full-package`: exact mapping/proof, original/replacement KMx and separate gate reports.
- `dqi-candidate-for-human-review`: only produced if existing full-package and improvement checks pass.

Official dependencies still required: published `verifiers/dqi/verify_submission_dqi.py`,
its companion imports/data and compatible Kickmix runtime. The platform's secret salt is unavailable.
Local ANF proof, full binary parsing and candidate contract checks do not replace official DQI verification.
The local gate uses a public non-secret salt; Kaggle scoring remains separate and is never automatic.

Format and instruction semantics were read from the same pinned upstream commit:
[KMB format](https://github.com/quantumlib/Qualtran/blob/638777fac4379bc62e2a1e4a52cf1a1753895d48/docs/kickmix/kickmix_binary_format.md),
[HMR and conditions](https://github.com/quantumlib/Qualtran/blob/638777fac4379bc62e2a1e4a52cf1a1753895d48/docs/kickmix/kickmix_instructions.md),
[GF product-phase generator](https://github.com/quantumlib/Qualtran/blob/638777fac4379bc62e2a1e4a52cf1a1753895d48/kickmix/src/kickmix/gen/gf_arithmetic/gen_gf_mul.cc).
