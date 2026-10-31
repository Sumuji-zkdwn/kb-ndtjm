# Exact state equality, hypothesis ambiguity, and bounded search

## Relation to primitive-lean

The existing source was read at commit
`4bf1c2236a08dea2571806e33b7dc79fad7346ea`:

- [FutureObservations.inc](https://github.com/Sumuji-zkdwn/primitive-lean/blob/4bf1c2236a08dea2571806e33b7dc79fad7346ea/linear_input/lean_check/FutureObservations.inc)
- [FutureFiniteHorizon.inc](https://github.com/Sumuji-zkdwn/primitive-lean/blob/4bf1c2236a08dea2571806e33b7dc79fad7346ea/linear_input/lean_check/FutureFiniteHorizon.inc)

`future_step`, `representation_iterate`, and `predictive_kernel_sub` articulate
the requirement that an exact compressed representation preserve observations
and deterministic transitions. `finite_horizon_complete` concerns a fixed
deterministic transition on a finite state type. It is not a license to treat
matching a few ARC demonstrations as global program equivalence, or to claim
that a time-bounded beam search is complete.

## The state used by the Python search

Let X be the ordered tuple of all demonstration inputs and all current test
inputs. For a partial transformation program p, store

\[
S_X(p)=(p(x_1),\ldots,p(x_m)).
\]

The key includes every grid's height, width, and complete color bytes. It uses
exact equality of byte strings, not equality of a lossy image feature or an
unchecked numeric hash. The outputs used as labels are not part of X.

For the pure deterministic suffix operators in the fixed problem's language,

\[
S_X(p)=S_X(q)\quad\Longrightarrow\quad S_X(r\circ p)=S_X(r\circ q).
\]

This follows coordinate by coordinate from function application to equal
arguments. No theorem about color-renaming equivariance or geometric symmetry
is presumed. Fixed-color and inferred-background rules may agree on all
demonstrations and disagree on a test input, so both must first be evaluated
on X before this equality can remove one.

The implementation keeps a cheaper representative of an equal grid-state
tuple. Nonnegative operator costs motivate this local dominance check. The
beam, time limit, finite operator language, and state budget still discard
other potentially useful programs. The solver therefore makes no exhaustive
solution guarantee. The Python implementation is tested, not Lean-extracted
or formally linked to the existing Lean declarations.

## Example consistency and two attempts

The version space searched is

\[
\mathcal V=\{p: p(x_i)=y_i\text{ for every demonstration }i\}.
\]

For each test input independently, candidate programs are grouped by their
predicted output grid. Returning the same grid twice does not cover two
different possible answers. The selector keeps at most two distinct outputs,
using demonstration consistency and program complexity. When there is only
one available grid, both required attempt fields contain it.

Consistency is empirical evidence, not proof of generalization. Complex local
lookup rules can overfit. Their cost includes feature dimensionality, changed
contexts, and weakly supported contexts, but that penalty does not establish
Bayesian calibration. Partial-fit fallbacks are explicitly marked in diagnostics.

## Information boundary and execution boundary

The solver reads `train[*].input`, `train[*].output`, and `test[*].input` only.
The runner reconstructs this restricted payload before spawning a worker.
Neither task ID nor external solution files enter the solver API. Scoring
uses test answers only after the complete prediction file has been written.

Each problem has a soft search deadline and a separate process hard deadline.
Before any worker runs, the submission already contains a valid fallback for
every test input. Atomic replacement prevents a killed write from corrupting
the only output. A failed worker is recorded; it is never reported as a
successfully synthesized rule.

Tests include a training-symmetric/test-asymmetric counterexample to train-only
state merging, deliberately poisoned test-answer fields, distinct unknown-color
predictions, contradictory recolor examples, and a real stuck-worker timeout.

## Independent C++ generator and fixed selection policy

The optional engine is adapted from Johan S. Wind's 2020 generic DSL search at
`top-quarks/ARC-solution`, commit `9407072659de1270358c2ba34c527785214dd68b`.
Its own search is a distinct implementation; the Python byte-equality argument
above is not a verification of that C++ engine. See its retained MIT license
and the explicit adaptation log in `vendor/icecuber/PROVENANCE.md`.

The wrapper removes caller task IDs and test answers and runs depths 1, 2, 3.
The adapted runner reconstructs each candidate's predictions on the original
demonstration inputs and exports the number of exact matches. It exports at
most three distinct candidate outputs per completed depth. Timeouts preserve
earlier completed depth files. POSIX limits bound address space and CPU time;
the parent task process additionally enforces wall time and kills descendants.

The portfolio policy is fixed before public evaluation. Complete demonstration
fits take priority over partial fits. Among exact candidates, a very simple
Python program (cost at most 2.8) takes first priority, then an exact C++ result,
then more complex Python hypotheses. The second distinct output favors the
other engine at the same fit tier, except that a complex Python lookup (cost
over 8) does not displace an exact C++ alternative merely for diversity.
These cost thresholds are engineering choices, not proved or calibrated odds.

The report stores both engines' predictions from the same run, enabling
component comparisons without rerunning or adapting to public answers. Those
component metrics use each engine's allocated share of the total task budget;
they are not separate full-budget evaluations. The final score is recorded
before any decision about future algorithm changes.
