# Think broadly; specify the interface exactly

2026-10-25 JST. This research checkpoint revisits the prior decision to stop after a
Clifford-only phase replacement failed to improve DQI cost. That result concerns one site,
not the cost of all alternative DQI circuits. No new full DQI candidate or submission is claimed here.

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

**Not yet done:** full DQI register/bit allocation for this inverse replacement, a new complete
dqi.kmb, measured whole-circuit Q/T, published-verifier smoke/full checks for this new replacement,
or Kaggle submission. The previous Clifford-phase candidate's full verification remains a separate result.
