"""Exact, synthetic witnesses for temporal observation loss.

This module is a finite toy model inspired by primitive-lean PR #19, commit
6bd74237f7b1910942988e6f542987857e9dec91.  It does not identify an ARC3 game
state with (x, u), assert that game frames follow a quarter rotation, or infer
game performance from information preservation.

All arithmetic uses Fraction.  Complex Fourier coefficients are represented
by their exact (real, imaginary) pair, not Python's floating complex type.
The rational WFS-coordinate examples use positive rational intensities; no
exponential, floating-point approximation, or real-game intensity is assumed.
"""

from fractions import Fraction
from itertools import product


PROOF_COMMIT = "6bd74237f7b1910942988e6f542987857e9dec91"
PROOF_URL = (
    "https://github.com/Sumuji-zkdwn/primitive-lean/blob/"
    + PROOF_COMMIT
    + "/linear_input/lean_check/WFSMobiusFourier.inc"
)


def _rational(value):
    """Accept exact rational inputs only; accidental float input is an error."""
    if isinstance(value, bool) or not isinstance(value, (int, Fraction)):
        raise TypeError("expected int or Fraction, without a float conversion")
    return Fraction(value)


def rotate(state):
    """The fixed toy update H(x, u) = (-u, x)."""
    x, u = (_rational(value) for value in state)
    return -u, x


def trace(state, count=4):
    """Observe x before each of count consecutive toy updates."""
    if isinstance(count, bool) or not isinstance(count, int) or count < 0:
        raise ValueError("count must be a nonnegative integer")
    current = tuple(_rational(value) for value in state)
    if len(current) != 2:
        raise ValueError("the toy state has exactly two coordinates")
    readings = []
    for _ in range(count):
        readings.append(current[0])
        current = rotate(current)
    return tuple(readings)


def trace4(state):
    return trace(state, 4)


def first_mode(values):
    """Exact normalized DFT k=1 for exp(-2*pi*i*j/4), as (real, imag)."""
    values = tuple(_rational(value) for value in values)
    if len(values) != 4:
        raise ValueError("the first four-point mode requires exactly 4 readings")
    a0, a1, a2, a3 = values
    return (a0 - a2) / 4, (-a1 + a3) / 4


def mode_power(values):
    """Power is intentionally lossy: it discards the complex coefficient's phase."""
    real, imag = first_mode(values)
    return real * real + imag * imag


def reconstruct_adjacent(first, second):
    """Recover the initial toy state from two consecutive x observations."""
    return _rational(first), -_rational(second)


def wfs2(intensity):
    """Toy coordinate (r^2-1)/2, restricted to exact positive intensity r."""
    intensity = _rational(intensity)
    if intensity <= 0:
        raise ValueError("the positive-intensity coordinate requires r > 0")
    return (intensity * intensity - 1) / 2


def mobius(coordinate):
    """M(z)=-z/(1+2z) on the stated positive-intensity image z > -1/2.

    Reject the excluded boundary and the other algebraic branch explicitly.
    This helper deliberately claims only the domain covered by the model.
    """
    coordinate = _rational(coordinate)
    denominator = 1 + 2 * coordinate
    if denominator <= 0:
        raise ValueError("the modeled Mobius domain requires z > -1/2")
    return -coordinate / denominator


def state_space():
    """Nine states, closed under rotate; (0, 0) is a fixed point."""
    return tuple(product((Fraction(-1), Fraction(0), Fraction(1)), repeat=2))


def _strings(values):
    return [str(value) for value in values]


def report():
    """Return JSON-friendly exact-model evidence, with its scope explicit."""
    states = state_space()
    traces = {state: trace4(state) for state in states}
    even_pair = ((Fraction(0), Fraction(0)), (Fraction(0), Fraction(1)))
    last_pair = ((Fraction(1), Fraction(0)), (Fraction(-1), Fraction(0)))
    phase_states = (
        (Fraction(1), Fraction(0)),
        (Fraction(0), Fraction(1)),
        (Fraction(-1), Fraction(0)),
        (Fraction(0), Fraction(-1)),
    )
    intensities = tuple(map(Fraction, (1, 2, 3, 8))) + (
        Fraction(1, 8), Fraction(1, 4), Fraction(1, 2),
    )
    coordinates = tuple(wfs2(intensity) for intensity in intensities)
    checks = {
        "closed_state_space": all(rotate(state) in states for state in states),
        "four_steps_identity": all(
            rotate(rotate(rotate(rotate(state)))) == state for state in states
        ),
        "trace_formula": all(
            traces[state] == (state[0], -state[1], -state[0], state[1])
            for state in states
        ),
        "normalized_negative_exponent_dft": all(
            first_mode(traces[state]) == (state[0] / 2, state[1] / 2)
            for state in states
        ),
        "adjacent_reconstruction": all(
            reconstruct_adjacent(*traces[state][:2]) == state for state in states
        ),
        "even_collision_distinguished_by_full_trace": (
            traces[even_pair[0]][::2] == traces[even_pair[1]][::2]
            and traces[even_pair[0]] != traces[even_pair[1]]
        ),
        "last_frame_collision_different_next_observation": (
            traces[last_pair[0]][-1] == traces[last_pair[1]][-1]
            and traces[last_pair[0]] != traces[last_pair[1]]
            and trace(last_pair[0], 5)[4] != trace(last_pair[1], 5)[4]
        ),
        "power_only_negative_control": (
            len({first_mode(trace4(state)) for state in phase_states}) == 4
            and len({mode_power(trace4(state)) for state in phase_states}) == 1
        ),
        "mobius_domain_preserved": all(
            1 + 2 * coordinate > 0 and 1 + 2 * mobius(coordinate) > 0
            for coordinate in coordinates
        ),
        "mobius_reciprocal_intensity": all(
            mobius(wfs2(intensity)) == wfs2(1 / intensity)
            for intensity in intensities
        ),
        "mobius_involution": all(
            mobius(mobius(coordinate)) == coordinate for coordinate in coordinates
        ),
    }
    return {
        "scope": "exact_synthetic_finite_model_only",
        "real_game_correspondence_established": False,
        "game_performance_improvement_established": False,
        "proof_commit": PROOF_COMMIT,
        "proof_url": PROOF_URL,
        "state_space": "{-1,0,1}^2",
        "update": "H(x,u)=(-u,x)",
        "observation": "K(x,u)=x",
        "state_count": len(states),
        "signature_counts": {
            "ordered_four_observations": len(set(traces.values())),
            "even_observations": len({values[::2] for values in traces.values()}),
            "last_observation_only": len({values[-1] for values in traces.values()}),
        },
        "dft_convention": {
            "exponent": "-2*pi*i*j/4",
            "normalization": "1/4",
            "exact_coefficient": "(x/2,u/2) as (real,imaginary)",
            "checked_states": len(states),
        },
        "even_sampling_witness": [
            {"state": _strings(state), "trace": _strings(traces[state]),
             "even": _strings(traces[state][::2])}
            for state in even_pair
        ],
        "last_packet_witness": [
            {"state": _strings(state), "packet": _strings(traces[state]),
             "next_observation": str(trace(state, 5)[4])}
            for state in last_pair
        ],
        "power_only_negative_control": {
            "distinct_complex_modes": len({first_mode(trace4(s)) for s in phase_states}),
            "distinct_powers": len({mode_power(trace4(s)) for s in phase_states}),
            "power": str(mode_power(trace4(phase_states[0]))),
        },
        "positive_rational_intensity_cases": len(intensities),
        "mobius_domain": "z > -1/2; boundary and lower branch rejected",
        "checks": checks,
        "all_checks_passed": all(checks.values()),
        "limits": [
            "No ARC3 state variables, controlled transition, or four-cycle are identified.",
            "Packet indices are not asserted to be physical time steps.",
            "Two adjacent readings suffice only for this explicitly defined toy update.",
            "Preserving observations does not establish a gameplay or score improvement.",
        ],
    }
