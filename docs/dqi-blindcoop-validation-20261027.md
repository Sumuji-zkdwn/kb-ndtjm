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
These are not yet a fresh full-circuit verifier result.

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

PENDING: append the measured source commit, Actions URL, complete circuit hash,
official-verifier output and package audit after the requested gates finish.
Kaggle submission and held-out leaderboard evaluation are separate and are not
performed by this workflow.
