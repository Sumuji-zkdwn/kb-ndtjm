"""Executable models from 原始の操作と忘却の導出 (Python 3.10+, stdlib only).

Finite states are numbered 0..n-1. Operations are COMPLETE, deterministic
tables. Words are in EXECUTION ORDER: mathematical AB(x) is run(x, ["B","A"]).
Exact finite calculations and rational arithmetic are separate from the
floating-point sphere examples. This is not an infinite-state decision tool.

Run all examples: python -X utf8 primitive.py
Analyze a table:  python -X utf8 primitive.py --model example_model.json
Save JSON:        python -X utf8 primitive.py --out result.json
"""
from __future__ import annotations

import argparse
from collections import deque
from dataclasses import dataclass
from fractions import Fraction
import json
from pathlib import Path
from types import MappingProxyType
from typing import Iterable, Mapping, Sequence


def _observation_key(value):
    """Discrete exact observations. Keep bool and int distinct; no floats."""
    if value is None or type(value) in (bool, int, str):
        return (type(value).__name__, value)
    if isinstance(value, tuple):
        return ("tuple", tuple(_observation_key(v) for v in value))
    raise TypeError("Observations must be int, str, bool, None, or tuples of these")


def _canonical(labels: Iterable) -> tuple[int, ...]:
    names = {}
    return tuple(names.setdefault(label, len(names)) for label in labels)


@dataclass(frozen=True)
class Run:
    word: tuple[str, ...]
    states: tuple[int, ...]
    observations: tuple

    @property
    def final_state(self) -> int:
        return self.states[-1]

    @property
    def observation(self):
        return self.observations[-1]

    def as_dict(self) -> dict:
        return dict(word=list(self.word), states=list(self.states),
                    observations=list(self.observations),
                    final_state=self.final_state, observation=self.observation)


@dataclass(frozen=True)
class FiniteSystem:
    """A total finite G=(X, operations, P). Input tables are copied/frozen."""

    observation: tuple
    operations: Mapping[str, tuple[int, ...]]

    def __post_init__(self):
        obs = tuple(self.observation)
        if not obs:
            raise ValueError("At least one state is required")
        for value in obs:
            _observation_key(value)
        operations = {}
        for name, table in self.operations.items():
            if not isinstance(name, str) or not name:
                raise ValueError("Each operation must have a nonempty string name")
            operations[name] = self._validate_table(table, len(obs))
        object.__setattr__(self, "observation", obs)
        object.__setattr__(self, "operations", MappingProxyType(operations))

    @staticmethod
    def _validate_table(table: Sequence[int], n: int) -> tuple[int, ...]:
        result = tuple(table)
        if len(result) != n or any(type(x) is not int or not 0 <= x < n for x in result):
            raise ValueError(f"A total operation needs {n} integer targets in 0..{n-1}")
        return result

    @property
    def n(self) -> int:
        return len(self.observation)

    def _state(self, state: int) -> None:
        if type(state) is not int or not 0 <= state < self.n:
            raise ValueError(f"State must be an integer in 0..{self.n-1}")

    def _partition(self, partition: Sequence[int]) -> tuple[int, ...]:
        labels = tuple(partition)
        if len(labels) != self.n or any(type(v) is not int or v < 0 for v in labels):
            raise ValueError("A partition needs one nonnegative integer per state")
        return _canonical(labels)

    def initial_partition(self) -> tuple[int, ...]:
        return _canonical(_observation_key(v) for v in self.observation)

    def refinement_history(self) -> tuple[tuple[int, ...], ...]:
        """R_k tests words of length <= k. The repeated fixed point is omitted."""
        current = self.initial_partition()
        stages = [current]
        while True:
            following = _canonical(
                (current[x], tuple(current[table[x]] for table in self.operations.values()))
                for x in range(self.n)
            )
            if following == current:
                return tuple(stages)
            stages.append(following)
            current = following

    def future_partition(self) -> tuple[int, ...]:
        """E_O: exact equivalence for ALL finite words, on this finite system."""
        return self.refinement_history()[-1]

    def blocks(self, partition: Sequence[int] | None = None) -> tuple[tuple[int, ...], ...]:
        labels = self.future_partition() if partition is None else self._partition(partition)
        return tuple(tuple(x for x in range(self.n) if labels[x] == b)
                     for b in range(max(labels) + 1))

    def run(self, start: int, word: Iterable[str]) -> Run:
        """Execute left-to-right. The trace includes the initial state."""
        self._state(start)
        if isinstance(word, str):
            raise TypeError('Use a list/tuple of names, for example ["B", "A"]')
        word = tuple(word)
        states = [start]
        for name in word:
            if name not in self.operations:
                raise KeyError(f"Unknown operation: {name!r}")
            states.append(self.operations[name][states[-1]])
        return Run(word, tuple(states), tuple(self.observation[x] for x in states))

    def compose(self, word: Iterable[str]) -> tuple[int, ...]:
        """Return the total table for a word in execution order."""
        if isinstance(word, str):
            raise TypeError("Use a list/tuple of operation names")
        word = tuple(word)
        return tuple(self.run(x, word).final_state for x in range(self.n))

    def distinguishing_word(self, left: int, right: int) -> tuple[str, ...] | None:
        """Shortest distinguishing continuation; () means now, None means equivalent."""
        self._state(left)
        self._state(right)
        initial = self.initial_partition()
        first = (left, right)
        queue = deque([first])
        parents = {first: None}
        while queue:
            pair = queue.popleft()
            x, y = pair
            if initial[x] != initial[y]:
                reversed_word = []
                while parents[pair] is not None:
                    previous, name = parents[pair]
                    reversed_word.append(name)
                    pair = previous
                return tuple(reversed(reversed_word))
            for name, table in self.operations.items():
                following = (table[x], table[y])
                if following not in parents:
                    parents[following] = (pair, name)
                    queue.append(following)
        return None

    def preservation_witness(self, operation: Sequence[int],
                             partition: Sequence[int] | None = None) -> dict | None:
        """A pair proving that operation does not preserve the chosen equivalence."""
        table = self._validate_table(operation, self.n)
        labels = self.future_partition() if partition is None else self._partition(partition)
        for x in range(self.n):
            for y in range(x + 1, self.n):
                if labels[x] == labels[y] and labels[table[x]] != labels[table[y]]:
                    return dict(states=[x, y], image_states=[table[x], table[y]])
        return None

    def with_operation(self, name: str, table: Sequence[int]) -> FiniteSystem:
        """Return a new system. Existing operation names cannot be replaced."""
        if name in self.operations:
            raise ValueError(f"Operation already exists: {name!r}")
        return FiniteSystem(self.observation, dict(self.operations, **{name: tuple(table)}))

    def extension_report(self, name: str, table: Sequence[int]) -> dict:
        """Check E_(O+f)=E_O; return a witnessing pair and executable word if false."""
        enlarged = self.with_operation(name, table)
        added = enlarged.operations[name]
        old = self.future_partition()
        new = enlarged.future_partition()
        witness = self.preservation_witness(added, old)
        if witness is not None:
            x, y = witness["states"]
            suffix = self.distinguishing_word(added[x], added[y])
            if suffix is None:
                raise AssertionError("Separated future classes must have a distinguishing word")
            word = (name,) + suffix
            witness.update(word=list(word),
                           left_run=enlarged.run(x, word).as_dict(),
                           right_run=enlarged.run(y, word).as_dict())
        return dict(operation=name, conservative=(old == new),
                    preserves_old_equivalence=(witness is None),
                    old_partition=list(old), new_partition=list(new), witness=witness)

    def quotient(self, partition: Sequence[int] | None = None):
        """Return (quotient_system, state_to_block), rejecting unsafe partitions."""
        labels = self.future_partition() if partition is None else self._partition(partition)
        blocks = self.blocks(labels)
        initial = self.initial_partition()
        for block in blocks:
            if any(initial[x] != initial[block[0]] for x in block):
                raise ValueError("Partition forgets an output that must be retained")
        for name, table in self.operations.items():
            witness = self.preservation_witness(table, labels)
            if witness is not None:
                raise ValueError(f"Operation {name!r} does not descend: {witness}")
        result = FiniteSystem(
            tuple(self.observation[block[0]] for block in blocks),
            {name: tuple(labels[table[block[0]]] for block in blocks)
             for name, table in self.operations.items()},
        )
        return result, labels

    def as_dict(self) -> dict:
        return dict(observation=list(self.observation),
                    operations={name: list(table) for name, table in self.operations.items()})

    @classmethod
    def from_dict(cls, data: dict) -> FiniteSystem:
        if not isinstance(data, dict) or set(data) != {"observation", "operations"}:
            raise ValueError("Model JSON needs exactly 'observation' and 'operations'")
        if not isinstance(data["observation"], list) or not isinstance(data["operations"], dict):
            raise ValueError("observation must be an array; operations must be an object")
        def restore(value):
            return tuple(restore(item) for item in value) if isinstance(value, list) else value
        return cls(tuple(restore(v) for v in data["observation"]), data["operations"])


def three_state_system() -> FiniteSystem:
    return FiniteSystem((0, 0, 1), {"A": (1, 0, 2), "B": (0, 2, 1)})


def _exact_rational(value) -> Fraction:
    if type(value) is int or isinstance(value, Fraction):
        return Fraction(value)
    if isinstance(value, str):
        try:
            return Fraction(value)
        except (ValueError, ZeroDivisionError) as exc:
            raise ValueError(f"Invalid exact rational: {value!r}") from exc
    raise TypeError("Use int, Fraction, or a rational string; floats/bools are not exact inputs")


def hyper_add(a, b) -> frozenset[Fraction]:
    """Possible magnitudes after addition: {a+b, |a-b|}, a,b >= 0."""
    a, b = _exact_rational(a), _exact_rational(b)
    if min(a, b) < 0:
        raise ValueError("Magnitudes must be nonnegative")
    return frozenset((a + b, abs(a - b)))


def hyper_sum(values: Iterable, *, max_values: int = 100_000) -> frozenset[Fraction]:
    """Exact possible magnitudes. Independent leaves; shared-variable correlations excluded."""
    if type(max_values) is not int or max_values < 1:
        raise ValueError("max_values must be a positive integer")
    results = frozenset((Fraction(0),))
    for value in values:
        value = _exact_rational(value)
        if value < 0:
            raise ValueError("Magnitudes must be nonnegative")
        following = set()
        for previous in results:
            following.update((previous + value, abs(previous - value)))
            if len(following) > max_values:
                raise RuntimeError("hyper_sum exceeded max_values; no membership answer was computed")
        results = frozenset(following)
    return results


def signed_partition(weights: Iterable[int], *, max_states: int = 1_000_000):
    """Find signs summing integer weights to zero, or None; exact pseudo-polynomial DP.

    Empty input returns (). A resource limit raises an exception, not a false result.
    """
    weights = tuple(weights)
    if any(type(w) is not int or w < 0 for w in weights):
        raise ValueError("Weights must be nonnegative integers")
    if type(max_states) is not int or max_states < 1:
        raise ValueError("max_states must be a positive integer")
    total = sum(weights)
    if total % 2:
        return None
    target = total // 2
    parents = {0: None}
    for index, weight in enumerate(weights):
        for previous in tuple(parents):
            following = previous + weight
            if following <= target and following not in parents:
                parents[following] = (previous, index)
                if len(parents) > max_states:
                    raise RuntimeError("signed_partition exceeded max_states; answer remains unknown")
        if target in parents:
            break
    if target not in parents:
        return None
    signs = [-1] * len(weights)
    current = target
    while current:
        previous, index = parents[current]
        signs[index] = 1
        current = previous
    return tuple(signs)


def rational_exponent_signs(exponents: Iterable):
    """Signs for sum(sign_i * exp(u_i)) == 0 with EXACT RATIONAL u_i.

    Hermite's transcendence theorem reduces this to even multiplicities.
    exp() is deliberately never evaluated. None means no solution.
    This is not an algorithm for arbitrary real or approximate logarithmic inputs.
    """
    values = tuple(_exact_rational(value) for value in exponents)
    positions = {}
    for index, value in enumerate(values):
        positions.setdefault(value, []).append(index)
    if any(len(indices) % 2 for indices in positions.values()):
        return None
    signs = [0] * len(values)
    for indices in positions.values():
        for offset, index in enumerate(indices):
            signs[index] = 1 if offset % 2 == 0 else -1
    return tuple(signs)


"""Sphere constructions for the primitive-operations example.

Only the Python standard library is required.  ``AB`` means A after B.
The nonlinear B operation uses numerical integration; its demo is not a
proof of the strict comparison theorem.  All angles are in radians.

Point arguments must have three finite real coordinates and unit norm to
within 1e-10.  Accepted roundoff in their norm is normalized before use.
Reconstructed linear coordinates are intentionally NOT normalized: noisy
measurements may reconstruct a point off the unit sphere.
"""

import math as _sphere_math
from numbers import Real as _SphereReal


def _sphere_real(value, name):
    if isinstance(value, bool) or not isinstance(value, _SphereReal):
        raise ValueError(f"{name} must be a finite real number")
    try:
        value = float(value)
    except (OverflowError, ValueError) as exc:
        raise ValueError(f"{name} must be a finite real number") from exc
    if not _sphere_math.isfinite(value):
        raise ValueError(f"{name} must be a finite real number")
    return value


def _sphere_triple(values, name):
    try:
        values = tuple(values)
    except TypeError as exc:
        raise ValueError(f"{name} must contain three finite real numbers") from exc
    if len(values) != 3:
        raise ValueError(f"{name} must contain three finite real numbers")
    return tuple(_sphere_real(v, f"{name}[{i}]") for i, v in enumerate(values))


def _sphere_point(point):
    point = _sphere_triple(point, "point")
    norm = _sphere_math.hypot(*point)
    if abs(norm - 1.0) > 1e-10:
        raise ValueError("point must have unit norm within 1e-10")
    return tuple(v / norm for v in point)


def _sphere_positive(value, name):
    value = _sphere_real(value, name)
    if value <= 0.0:
        raise ValueError(f"{name} must be positive")
    return value


def _sphere_spiral_latitude(t, z0, epsilon):
    t = _sphere_real(t, "t")
    z0 = _sphere_real(z0, "z0")
    epsilon = _sphere_positive(epsilon, "epsilon")
    if t < 0.0:
        raise ValueError("t must be nonnegative")
    if not -1.0 <= z0 <= 1.0:
        raise ValueError("z0 must lie in [-1, 1]")
    if abs(z0) == 1.0 or z0 == 0.0:
        return z0, t, epsilon
    # Equivalent to z0 / sqrt(z0**2 + (1-z0**2)*exp(2*epsilon*t)),
    # without the exponentially growing factor.  Extreme times may underflow
    # to z=0; floating-point output does not certify strict positivity.
    numerator = z0 * _sphere_math.exp(-epsilon * t)
    radius0 = _sphere_math.sqrt((1.0 - z0) * (1.0 + z0))
    z = numerator / _sphere_math.hypot(radius0, numerator)
    return z, t, epsilon


def sphere_spiral_point(t, z0, phi0=0.0, epsilon=0.1):
    """Closed-form forward flow of e3 cross p - epsilon*z*(e3-z*p).

    For 0 < z0 < 1 the exact orbit winds forever, has strictly decreasing
    latitude, and never repeats a point.  Poles are equilibria; the equator
    is periodic.  Time is nonnegative and epsilon is strictly positive.
    Floating-point underflow can round a very small latitude to zero.
    """
    z, t, _ = _sphere_spiral_latitude(t, z0, epsilon)
    phi0 = _sphere_real(phi0, "phi0")
    # Reducing each term first also avoids overflow when adding large angles.
    phi = (_sphere_math.remainder(phi0, _sphere_math.tau)
           + _sphere_math.remainder(t, _sphere_math.tau))
    radius = _sphere_math.sqrt((1.0 - z) * (1.0 + z))
    return (radius * _sphere_math.cos(phi),
            radius * _sphere_math.sin(phi), z)


def sphere_spiral_speed(t, z0, epsilon=0.1):
    """Euclidean speed of ``sphere_spiral_point`` at time t."""
    z, _, epsilon = _sphere_spiral_latitude(t, z0, epsilon)
    radius = _sphere_math.sqrt((1.0 - z) * (1.0 + z))
    return radius * _sphere_math.hypot(1.0, epsilon * z)


def sphere_rotate_x(point, angle):
    """Right-handed rotation about the x axis."""
    x, y, z = _sphere_point(point)
    angle = _sphere_real(angle, "angle")
    s, c = _sphere_math.sin(angle), _sphere_math.cos(angle)
    return (x, c * y - s * z, s * y + c * z)


def sphere_rotate_z(point, angle):
    """Right-handed rotation about the z axis."""
    x, y, z = _sphere_point(point)
    angle = _sphere_real(angle, "angle")
    s, c = _sphere_math.sin(angle), _sphere_math.cos(angle)
    return (c * x - s * y, s * x + c * y, z)


def sphere_order_a(point):
    """The nonlinear diffeomorphism A(p) = Rz(1 + 2*z)*p."""
    point = _sphere_point(point)
    return sphere_rotate_z(point, 1.0 + 2.0 * point[2])


def sphere_order_b(point, epsilon=0.1, eta=0.4, steps=2000):
    """Approximate B, the time-one flow of -epsilon*z*(1+eta*a)*(e3-z*p).

    Longitude phi stays fixed.  Classical fixed-step RK4 integrates
      z' = -epsilon*z*(1-z*z)*(1+eta*sqrt(1-z*z)*cos(phi)).
    Epsilon must be positive, 0 < eta < 1, and steps an integer in
    [1, 1_000_000].  The conservative restriction
    epsilon*(1+eta)/steps <= 0.25 keeps the RK4 stages in the latitude
    domain.  This restriction is not an error estimate; check convergence
    by increasing steps when using the returned numerical values.
    """
    a, b, z = _sphere_point(point)
    epsilon = _sphere_positive(epsilon, "epsilon")
    eta = _sphere_real(eta, "eta")
    if not 0.0 < eta < 1.0:
        raise ValueError("eta must lie strictly between 0 and 1")
    if isinstance(steps, bool) or not isinstance(steps, int):
        raise ValueError("steps must be an integer in [1, 1000000]")
    if not 1 <= steps <= 1_000_000:
        raise ValueError("steps must be an integer in [1, 1000000]")
    if (epsilon / steps) * (1.0 + eta) > 0.25:
        raise ValueError("steps too small: require epsilon*(1+eta)/steps <= 0.25")
    radius = _sphere_math.hypot(a, b)
    if radius == 0.0:
        return (0.0, 0.0, z)
    cos_phi, sin_phi = a / radius, b / radius
    h = 1.0 / steps

    def derivative(latitude):
        r = _sphere_math.sqrt((1.0 - latitude) * (1.0 + latitude))
        return (-epsilon * latitude * (1.0 - latitude) * (1.0 + latitude)
                * (1.0 + eta * r * cos_phi))

    for _ in range(steps):
        k1 = derivative(z)
        k2 = derivative(z + 0.5 * h * k1)
        k3 = derivative(z + 0.5 * h * k2)
        k4 = derivative(z + h * k3)
        z += (h / 6.0) * (k1 + 2.0 * k2 + 2.0 * k3 + k4)
    radius = _sphere_math.sqrt((1.0 - z) * (1.0 + z))
    return (radius * cos_phi, radius * sin_phi, z)


def sphere_order_demo(epsilon=0.1, eta=0.4, steps=2000):
    """Return a numerical illustration of hidden order and its revelation.

    The chosen p0 has z=1/2, phi=-1.  In exact arithmetic PAB=PBA;
    applying B once more gives PBAB<PBBA.  Here the points and gaps are
    floating-point RK4 approximations, not an exact equality certificate.
    """
    p0 = sphere_spiral_point(0.0, 0.5, phi0=-1.0)
    bp0 = sphere_order_b(p0, epsilon, eta, steps)
    ab = sphere_order_a(bp0)
    ba = sphere_order_b(sphere_order_a(p0), epsilon, eta, steps)
    bab = sphere_order_b(ab, epsilon, eta, steps)
    bba = sphere_order_b(ba, epsilon, eta, steps)
    return {
        "method": "fixed-step RK4; numerical illustration, not a proof",
        "epsilon": float(epsilon), "eta": float(eta), "steps": steps,
        "p0": p0, "AB": ab, "BA": ba,
        "B_after_AB": bab, "B_after_BA": bba,
        "PAB": ab[2], "PBA": ba[2], "PBAB": bab[2], "PBBA": bba[2],
        "current_observation_gap": ab[2] - ba[2],
        "later_observation_gap": bba[2] - bab[2],
    }


def sphere_linear_measurements(point, epsilon):
    """Return (Pp, PBp, PBABp) for A=Rz(pi/2), B=Rx(epsilon), P=z.

    One trajectory suffices: measure, B, measure, A, B, measure.
    Equivalently evaluate the three words I, B, BAB on the same initial point.
    Do not apply the complete word BAB to the already advanced point Bp.
    Singular angles are valid here, but do not permit unique reconstruction.
    """
    x, y, z = _sphere_point(point)
    epsilon = _sphere_real(epsilon, "epsilon")
    s, c = _sphere_math.sin(epsilon), _sphere_math.cos(epsilon)
    m1 = s * y + c * z
    return (z, m1, s * x + c * m1)


def _sphere_linear_sine_cosine(epsilon, singular_tolerance):
    epsilon = _sphere_real(epsilon, "epsilon")
    tolerance = _sphere_positive(singular_tolerance, "singular_tolerance")
    if tolerance >= 1.0:
        raise ValueError("singular_tolerance must lie strictly between 0 and 1")
    s, c = _sphere_math.sin(epsilon), _sphere_math.cos(epsilon)
    if abs(s) <= tolerance:
        raise ValueError("singular or nearly singular angle: abs(sin(epsilon)) <= tolerance")
    return s, c


def sphere_linear_reconstruct(measurements, epsilon, singular_tolerance=1e-12):
    """Invert the three observables; do not renormalize measurement noise.

    In exact arithmetic the determinant is -sin(epsilon)**2.  Floating
    multiples of pi are rejected by a tolerance, not tested with sin==0.
    Passing this check does not promise well-conditioned reconstruction;
    ``sphere_linear_condition_number`` quantifies the linear sensitivity.
    """
    m0, m1, m2 = _sphere_triple(measurements, "measurements")
    s, c = _sphere_linear_sine_cosine(epsilon, singular_tolerance)
    result = ((m2 - c * m1) / s, (m1 - c * m0) / s, m0)
    if not all(_sphere_math.isfinite(v) for v in result):
        raise ValueError("reconstruction overflowed; measurements or angle are unsuitable")
    return result


def sphere_linear_condition_number(epsilon, singular_tolerance=1e-12):
    """Exact formula evaluated in floats for the observation matrix's kappa_2."""
    s, c = _sphere_linear_sine_cosine(epsilon, singular_tolerance)
    return (2.0 + c * c + abs(c) * _sphere_math.sqrt(c * c + 8.0)) / (2.0 * abs(s))


def analyze_finite(model: FiniteSystem) -> dict:
    quotient, state_to_block = model.quotient()
    history = model.refinement_history()
    return dict(
        kind="exact_finite_analysis",
        model=model.as_dict(),
        initial_blocks=model.blocks(model.initial_partition()),
        future_blocks=model.blocks(),
        refinement_history=history,
        strict_refinement_rounds=len(history) - 1,
        round_bound=model.n - len(set(history[0])),
        observation_obstructions={
            name: model.preservation_witness(table, model.initial_partition())
            for name, table in model.operations.items()
        },
        quotient=quotient.as_dict(),
        state_to_block=state_to_block,
    )


def demo_finite() -> dict:
    model = three_state_system()
    base = FiniteSystem((0, 0, 1), {"A": (1, 0, 2)})
    ab = model.run(2, ["B", "A"])
    ba = model.run(2, ["A", "B"])
    return dict(
        **analyze_finite(model),
        composition_convention="Words list execution order: AB means ['B', 'A'].",
        AB_2=ab.as_dict(),
        BA_2=ba.as_dict(),
        shortest_distinguishing_word=model.distinguishing_word(ab.final_state, ba.final_state),
        after_B=[model.run(ab.final_state, ["B"]).observation,
                 model.run(ba.final_state, ["B"]).observation],
        adding_B_to_A_only=base.extension_report("B", (0, 2, 1)),
        adding_a_composite=base.extension_report("AA", base.compose(["A", "A"])),
    )


def demo_sums() -> dict:
    exponents = ("1/2", "2/4", "-1/3", "-2/6")
    return dict(
        kind="exact_integer_and_rational_arithmetic",
        hyper_add_1_2=sorted(str(x) for x in hyper_add(1, 2)),
        hyper_sum_1_2_3=sorted(str(x) for x in hyper_sum((1, 2, 3))),
        partition_weights=[1, 2, 3],
        partition_signs=signed_partition((1, 2, 3)),
        impossible_partition=signed_partition((1, 2)),
        rational_exponents=exponents,
        rational_exponent_signs=rational_exponent_signs(exponents),
        impossible_exponent_signs=rational_exponent_signs(("0", "1", "2")),
        interpretation="Rational exponents are exact inputs; exp is not numerically evaluated.",
    )


def demo_sphere() -> dict:
    point = (0.36, 0.48, 0.8)
    epsilon = 0.4
    measurements = sphere_linear_measurements(point, epsilon)
    reconstructed = sphere_linear_reconstruct(measurements, epsilon)
    return dict(
        kind="floating_point_examples_not_global_proofs",
        spiral=[dict(time=t, point=sphere_spiral_point(t, z0=0.5),
                     speed=sphere_spiral_speed(t, z0=0.5))
                for t in (0.0, 1.0, 5.0, 20.0)],
        order_example=sphere_order_demo(),
        linear_observability=dict(
            original=point, measurements=measurements, reconstructed=reconstructed,
            max_error=max(abs(a-b) for a, b in zip(point, reconstructed)),
            condition_number=sphere_linear_condition_number(epsilon),
        ),
    )


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    source = parser.add_mutually_exclusive_group()
    source.add_argument("--demo", choices=("all", "finite", "sums", "sphere"), default="all")
    source.add_argument("--model", type=Path, help="Read a complete finite model from JSON")
    parser.add_argument("--out", type=Path, help="Save JSON to a new file")
    args = parser.parse_args(argv)
    try:
        if args.model is not None:
            result = analyze_finite(FiniteSystem.from_dict(
                json.loads(args.model.read_text(encoding="utf-8-sig"))))
        else:
            demos = {"finite": demo_finite, "sums": demo_sums, "sphere": demo_sphere}
            result = ({name: fn() for name, fn in demos.items()} if args.demo == "all"
                      else demos[args.demo]())
        serialized = json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False)
        if args.out is None:
            print(serialized)
        else:
            with args.out.open("x", encoding="utf-8", newline="\n") as output:
                output.write(serialized + "\n")
            print(f"Saved: {args.out.resolve()}")
    except (ValueError, TypeError, KeyError, OSError, RuntimeError, OverflowError) as exc:
        parser.exit(2, f"error: {exc}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
