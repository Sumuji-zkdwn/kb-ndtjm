# Think broadly; specify the interface exactly

2026-10-25 JST. This research checkpoint revisits the prior decision to stop after a
Clifford-only phase replacement failed to improve DQI cost. That result concerns one site,
not the cost of all alternative DQI circuits. The integration checkpoint below records the new complete candidate separately from this local proof.

## Existing material reused and actual circuit measured

The original user archive `DQI_tower_inverse66_probe_2026-10-25.zip` is preserved as
`tower_inverse66_probe.zip`, including its source, attribution and Apache-2.0 license.
Its tower/bilinear constants credit `andigu/uncompute`, not a new discovery in this checkpoint.

The pinned baseline DQI is SHA-256
`959471d05a26373b4f14ca0cae2d8639ea25f18170d9f6532139aa51ccc04995`.
The INFO_TAG/operation packets give these **static**, overlapping per-call counts:

| Block | Calls | Toffoli-like operations per call |
|---|---:|---:|
| gf_inverse_chain | 4,983 | 315 |
| gf_uninverse_chain | 4,983 | 0 |
| forney_step | 4,095 | 351 |

The original whole circuit has Q=1,893 and static T=5,725,461.
The arithmetic gfinverse and its cleanup must be considered together; replacing a free cleanup
by a second inverse would otherwise overstate the benefit.

## 1. A clean inverse contract, proved by exact symbolic evaluation

Let F=GF(2^12) with polynomial `0x1053`; define inv(0)=0.
The archived 66-CCX circuit has quantum interface

    I |x,y,0> = |x, y XOR inv(x), 0>.

This is a quantum channel statement after discarding its temporary measurement record.
For each of its 84 measurement outcome strings m, the Kraus operator on the computational
interface is exactly 2^(-42) I: neither a residual outcome-dependent phase nor garbage remains.
Consequently the equality extends to arbitrary superpositions and entanglement with a reference.
The XOR target y may be arbitrary; it is not assumed zero in this first certificate.

The checker uses the Boolean quotient ring F2[v]/(v_i^2-v_i). It propagates every CX/CCX,
adds m*f to the phase when HMR erases a qubit containing f, then propagates the conditional
Z/CZ corrections. Independent variables are x[12], y[12], and all 84 measurement results.
The ideal inverse ANF is derived independently by a Moebius transform of all 4,096 field values.
The final residual phase polynomial is zero. The twice-applied circuit is also checked with
168 independent measurement variables and implements the identity.
Deleting a measurement correction is a negative control: the checker rejects its nonzero phase.

This is exact finite algebra, not sampled trajectories. Its trusted boundary is the Python checker
and stated gate/HMR semantics; it is **not a Lean-kernel proof**.

## 2. A stronger contract: keep the scaffold until after the phase

The safe first construction is I → caller phase → I, costing 66+66=132 CCX.
It is not necessary to pay for the second inverse if intermediate values are retained.

The generated `inverse66-forward.kmx` computes the inverse and keeps 18 intermediate qubits.
The caller uses the inverse only through a diagonal phase. The generated
`inverse66-erase.kmx` then erases the inverse output FIRST, followed by the intermediate
stages in reverse dependency order. Each erased value is linear or quadratic in still-live
parents, so its HMR kickback is cancelled by classically conditioned Z/CZ operations.
No CCX is required by that cleanup.

For independent coherent phase coefficients z[12], define Phi_z(y)=(-1)^(sum_i z_i*y_i).
The verified interface is

    E Phi_z F |x,0,0> = (-1)^(sum_i z_i*inv(x)_i) |x,0,0>.

More precisely, every complete measurement branch has that same action multiplied by 2^(-48).
There are 96 independent HMR outcome variables. The symbolic calculation preserves the caller's
phase exactly and returns the output and all 21 workspace qubits to zero.

| Generated component | CCX | HMR | Other operations |
|---|---:|---:|---|
| forward | 66 | 66 | 1,269 CX, 66 conditional CZ |
| erase | 0 | 30 | 3,674 CX, 228 conditional CZ, 47 conditional Z |

The local footprint is 45 qubits: input 12, inverse output 12, workspace 21, plus one reusable
classical measurement bit. The classical temporary may be cleared after its final correction.
The quantum output must initially be zero, the caller phase must be diagonal, and the caller
must leave input/scaffold computational values unchanged. These are essential assumptions.

### Why the interface includes the actual Forney phase

The published reference's Forney body obtains y=inv(sigma_prime), then applies
the phase (-1)^(r*parity(mask & (omega*y))), and then deletes the inverse.
For the field basis e_i this phase is linear in y, with coefficients

    z_i = r * parity(mask & (omega*e_i)).

Substitute these polynomials for z_i in the proved ANF identity. This permits quantum r and omega,
classical mask, and all correlations with sigma_prime. Independence of the abstract z variables
is a stronger hypothesis space for the identity, not a required independence of physical data.
The actual caller must still be checked to ensure no scaffold accesses or aliasing are introduced.
The published Python source has no scaffold use between inverse initialization and deletion,
apart from passing it to the deletion routine.

## 3. Resource claims separated from integration claims

Forney-only substitution, leaving every other operation unchanged, gives these static models:

| Model | Inverse compute + cleanup | Whole static T | Reduction |
|---|---:|---:|---:|
| Baseline | 315 + 0 | 5,725,461 | 0 |
| Clean inverse used twice | 66 + 66 | 4,976,076 | 749,385 (13.09%) |
| Retained scaffold | 66 + 0 | 4,705,806 | 1,019,655 (17.81%) |

The second replacement is 4,095*(315-66); it does not replace a Clifford correction that already costs zero T.
These are conditional static counts, **not measured integrated score improvements**.
The actual objective is C=R(eps_plus)*Q^2*mean(T). Necessary and sufficient for a lower cost is

    mean(T')/mean(T) < (Q/Q')^2 * R(eps_plus)/R(eps_plus').

Under the same error bound, this reduces to Q'^2*mean(T') < Q^2*mean(T).
In a static surrogate, the retained-scaffold model can tolerate Q'<2088.0401 when Q=1893.
If one fresh 21-qubit workspace is shared by all positions, a deliberately conservative
Q'=1914 surrogate would give a cost ratio of about 0.84025. This is a design bound to realize,
not an assertion that a complete generated circuit already has that Q or measured mean T.
Q=1914 requires disjoint fresh wires and verified cleanup at every reuse.

Forney steps are guarded by whether their classical 12-bit mask is nonzero. Thus measured
mean savings depend on active positions, not just the static 4,095 count. In the model where all
other execution conditions are preserved, the mean saving is 249*E[A], with A the number of
active positions. The published uniform-mask distribution has E[A]=4095*(1-1/4096).
The integrated verifier and Q/T measurement remain mandatory.

## 4. A precise obstruction to a tempting shortcut

All twelve inverse-output Boolean ANFs have degree 11. If the intermediate scaffold is erased
first, measuring an inverse output requires a correction containing that degree-11 function.
Z/CZ phases on the original input alone have degree at most two. CNOT basis changes are linear.
Therefore a generic cleanup using only those Clifford phase corrections on x, with no retained
nonlinear intermediates, cannot implement all required inverse-output measurement corrections.
This does not rule out the retained-scaffold construction: its still-live parents encode nonlinear
functions of x. The shortcut fails only under the explicitly restricted interface.

## Reproduce and current boundary

```bash
python research/inverse66/formal_probe.py --parse-kickmix
python research/inverse66/profile_baseline.py /path/to/baseline-dqi.kmb
```

Kickmix parsing succeeded for the archived inverse (66 Toffoli-like) and the newly generated
forward/erase components (66/0). See `formal-report.json` and `resource-profile.json`.
The archive retains all generator source and license information.

## Integration checkpoint: complete DQI (2026-10-25 UTC)

`quantum/inverse66_dqi.py` now patches the SHA-pinned v1.0 complete circuit. It discovers
Forney inverse/cleanup regions from nested INFO_TAGs and records every actual operand in
`site-map.json`; it does not assume that all sites use the first site's wires. The output
reset and all 48 original scaffold resets are preserved, and only 21 of those scaffold
qubits are reused. The caller must leave scaffold/input untouched and use the inverse
output only in diagonal phases. Every site is checked for these conditions before rewriting.

| Actual generated complete candidate | Sites | Q | Classical bits | Static Toffoli-like | SHA-256 |
|---|---:|---:|---:|---:|---|
| Minimal | 1 | 1,893 | 49,155 | 5,725,212 | `5db467398895cec947292ae67cab42a6aab67e702d8b0dbabc6fd63f4ebe0f47` |
| All Forney positions | 4,095 | 1,893 | 49,155 | 4,705,806 | `ea0d6717e7b37fb386a0d99730eebf150c0e78de1cc8547f0727c2f6845a99bc` |

The fresh bit b49154 is a reused private HMR outcome. Original E0..E4094 occupy
b0..b49139. The original b49153 mask-nonzero guard and its PUSH/POP conditions are
preserved; old private inverse temporary bits are cleared at the new block exits.
The first site's input is q888..899, inverse output q1803..1814, original scaffold
q1828..1875, of which q1828..1848 is reused. These concrete numbers are a single-site
example; the manifest contains all mappings and old instruction intervals.

For each rewritten KMB packet, unchanged spans are compared byte for byte. Named registers
are byte-identical. Only nested inverse INFO_TAGs are removed/reindexed. Both complete
circuits passed native Kickmix parsing. The one-site circuit passed the **unmodified published
DQI verifier** with 1,536 shots, value_errors=0, phase_errors=0, seed=20261025,
log2_delta=-128, and effective error upper bound 0.0561256873183065 < 1/16.
The all-site circuit also passed candidate and 1,536-shot smoke checks with zero value/phase errors.
Full-package verification is pending at this checkpoint.

```bash
python quantum/inverse66_dqi.py --baseline /path/to/submission.zip --sites 1 --output build/one-site
python quantum/inverse66_dqi.py --output build/one-site --parse
python quantum/run_wfs_gates.py --stage smoke --baseline /path/to/submission.zip \
  --candidate build/one-site/dqi.kmb --data-root /path/to/official-data --out build/report/one-site
python quantum/inverse66_dqi.py --baseline /path/to/submission.zip --sites all --output build/integration
python quantum/inverse66_dqi.py --output build/integration --parse
python quantum/run_wfs_gates.py --stage full-package --baseline /path/to/submission.zip \
  --candidate build/integration/dqi.kmb --data-root /path/to/official-data --out build/report
```

The existing `dqi-gated.yml` now repeats one-site candidate/smoke, builds the all-site
candidate, and then runs candidate → smoke → full-package. Missing official data is
reported as NOT_RUN. Candidate hashes, mapping, formal proof and gate JSON are uploaded.
Full-package produces the 13-member ZIP only if published-verifier correctness and cost
improvement over the unchanged baseline pass. Release v1.0 is preserved. Nothing submits
to Kaggle. Public-verifier cost is not the secret-salt official Kaggle score.

The older Clifford-phase candidate's full verification remains a separate result.

