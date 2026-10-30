# DQI PR7 blind-cooperation candidate: integration and official-verifier gates

The result under evaluation is the artifact improvement obtained through blind
cooperation with Gemini. A local algebraic check alone is not its completion
criterion. Record the outcome only after the implemented complete DQI passes
GitHub Actions and the unchanged published competition verifier.

## Frozen before/after comparison

- Before: PR #7, source `240ba77a94e01e4d35bc82d936833ae2fbae783f`,
  records head `13f74c4f1574ca234e91e3e08941494cf5af5386`.
- Before full-circuit SHA-256:
  `a5b128745d2a5bd76ab67faf1f141103de3c0e8c8d54535753bdc7716aaefc06`.
- Before measurement: successful [run 40414437653](https://github.com/Sumuji-zkdwn/kb-ndtjm/actions/runs/40414437653),
  pinned checkpoint `e957ea130c26d77887083088bf8ed1d7c7ee05e834cb2fd3ebab1c0f8b916b1d`.
- After local candidate: saved archive `dual_gemini_phase68_20261027.zip`,
  SHA-256 `239ebbe4d52b1e47201db5ad509e9b79c87b0f0e6a5601ef0e471e9c115ed458`.
  Native local KMx hash `114437811d7887bcce8a4a6664744dd06af2bd9462a09f9d0442e70b1743094d`.
- The comparison measurement is reused only after checking the actual reference
  circuit, verifier, configuration, confidence bound and cost. The new complete
  candidate must receive a fresh full run.

## Implemented change

`--trace-phase5` retains the first two norm stages, G/H construction, complete
BM history, variable E masks and the existing workspace. A five-product scalar
trace network replaces the final inverse/phase construction. Its terminal two
products are direct CCZ gates; three stored products are HMR-erased with explicit
conditional CZ corrections. The common XOR for the sibling products is built
and restored separately during computation and measurement cleanup.

The underlying Boolean network is NIST SLP f121049, attributed in
`research/bm_port/NIST_f121049.txt`; it is not claimed as a newly discovered
Boolean circuit. The implementation contains no deliberately altered discussion
sentence. Earlier candidates and flags remain available.

## Prespecified acceptance and measurements

1. Regression tests, source provenance, exact local ANF and native local parser.
2. Generate and natively parse the complete DQI, preserving registers and Q.
3. Compare every opcode, operand and classical condition outside Forney with PR7;
   compare allocation events except instruction offsets.
4. Candidate, smoke and full-package gates must all be PASS. NOT_RUN does not
   satisfy this workflow. The full run uses 102400 shots, seed 20261025,
   batch size 1024, max_workers 1, log2_delta -128, and the unchanged public
   verifier. Record both value and phase errors and the measured cost.
5. Run the existing 55-pattern/deep-history/variable-mask check and verify all
   13 ZIP members; the other 12 members must match v1.0 byte for byte.

Local results before Actions: 41 regression tests PASS, native local parse PASS,
local phase count 69 -> 68, CX 5221 -> 5216, HMR 87 -> 84, total 5648 -> 5629.
Complete-circuit prediction: 719881 -> 715786 Toffoli-like, Q remains 2482.
These were predictions before Actions. The fresh full-circuit results are recorded below.

The Windows checkout initially changed LF to CRLF and broke pinned checkpoint
hashes. Original Git blob bytes were restored; no checkpoint contents or verifier
acceptance conditions were relaxed. The PR7 checkpoint pin above is its exact
Git blob byte hash, not a Windows newline-converted copy.

## Cooperation evidence

- [Conversation A](https://gemini.google.com/app/779e52f9b50a8d07): clean-target
  lowering and shared XOR discussion, with implementation and computed results
  returned to Gemini.
- [Conversation B](https://gemini.google.com/app/3fedcaad74021583): terminal-product
  phase lowering and cleanup dependencies; a concrete phase counterexample and
  corrected restoration order were returned.
- Full prompts, replies, the private one-sentence alteration record, preserved
  candidates and local proof outputs are retained in the local experiment archive.

The present measurement is a before/after result for this research artifact.
Broader effectiveness of the procedure, or causal isolation of the deliberately
altered sentence from ordinary collaboration, is not established by one case.

## Full integration outcome

**PASS. The complete implemented candidate passed GitHub Actions and the
unchanged published official verifier. Its measured cost is 0.568844017275%
below PR7.** This is the result for the whole cooperation sequence starting from
PR7; the intermediate local 68-Toffoli candidate was not separately subjected
to a complete official-verifier run.

- Measured implementation: `b3f6373d10bfec8b4c7a102f774399d2563bfe8f`.
- [Complete DQI Actions run 40447516741](https://github.com/Sumuji-zkdwn/kb-ndtjm/actions/runs/40447516741): success.
- [Existing WFS Actions run 40447516739](https://github.com/Sumuji-zkdwn/kb-ndtjm/actions/runs/40447516739): success.
- [PR #8](https://github.com/Sumuji-zkdwn/kb-ndtjm/pull/8) contains the implementation.
  The later commit adds records and documentation only.
- [Machine-readable checkpoint](../checkpoints/bm-blindcoop-20261027.json)
  retains the generation, local proof, full parse, gates, edge checks, package
  audit, artifact digests and Actions step results.

| Measurement | PR7 before | Integrated candidate |
| --- | ---: | ---: |
| Q / peak live qubits | 2,482 | 2,482 |
| Full DQI Toffoli-like count | 719,881 | 715,786 |
| Forney Toffoli-like count | 327,600 | 323,505 |
| Full instruction count | 90,986,115 | 90,908,310 |
| Full verification shots | 102,400 | 102,400 |
| Value errors / phase errors | 0 / 0 | 0 / 0 |
| Upper error bound | 0.0008660587301657926 | 0.0008660587301657926 |
| Published verifier cost | 5,282,883,023,272.201 | 5,252,831,659,254.676 |

The candidate was freshly measured. The PR7 measurement was reused from its
successful run after verifying the checkpoint, actual reference circuit,
verifier hash, configuration, upper error bound and cost. Both use batch size
1024, seed 20261025, one worker and log2_delta -128. The cost is
`R(error_bound) * Q^2 * T`: with Q and the error bound unchanged, the reduction
matches the 4,095 saved Toffoli-like operations. Runtime is not an effectiveness
claim; the two hosted runs do not establish a controlled speed benchmark.

The 41 regression tests and 10 attributed source-file checks passed. The native
local KMx hash equals the sealed local candidate's hash. Every non-Forney packet
and the register contract agree with PR7; all 6,257 allocation events agree
except instruction offsets. All candidate, smoke and full-package gates are
PASS. The additional 55-pattern / 1,536-shot check, including deep BM history
and variable masks, found zero value or phase errors.

Complete DQI SHA-256:
`5bd75fdfc5f45babf4626622612591072c1b29004de9ea564c736290e1682fea`.
Official verifier SHA-256:
`f14274bc0943fb9769ddb01131be6063191a15009fe1caf1d4bdd9fd25194e65`.

The `dqi-bm-candidate-for-human-review` Actions artifact contains
`submission-candidate.zip`, 83,360,676 bytes, SHA-256
`147d53a469b87f40c6a7bdba1a75526bc136d6d8eea2096e49f5772a60297b01`.
All 13 members were streamed and checked in CI and again after download. The
DQI member matches the verified complete circuit; the other 12 members match
the preserved v1.0 files. The downloaded report artifact also matches its
published digest, `707f8a9742e65f1b7e56a2a20fa1a6ad25b487bf045b4401dfd6c1517e261e73`.

This completes this case's requested path from theory through implementation,
Actions, public official verification and measured artifact improvement. It
provides a concrete case for documenting the blind-cooperation procedure.
The isolated contribution of the deliberately altered sentence, and the
procedure's effectiveness across other tasks, remain unmeasured.
Kaggle submission and held-out leaderboard evaluation were not performed.

## Reproduction

The complete workflow is `.github/workflows/dqi-bm.yml`, stage `full-package`.
It obtains the preserved PR7 circuit from run 40414437653 and the unchanged
official competition files, builds this candidate with `--trace-phase5`, then
runs the gates and audits above. The final pass assertion rejects NOT_RUN.

The focused implementation checks are:

```sh
python -m unittest discover -s quantum -p 'test_*.py' -v
python research/bm_port/check_provenance.py
python research/bm_port/trace_phase5_probe.py --out build/trace-phase5-local
python research/bm_port/build_dqi.py --out build/bm-conservative --trace-allocations --trace-phase5
python research/bm_port/build_dqi.py --out build/bm-conservative --parse
```

Use the workflow's pinned Kickmix commit and environment for complete
reproduction. These focused commands alone do not run the official verifier;
the `full-package` workflow includes that step and saves its reports.
