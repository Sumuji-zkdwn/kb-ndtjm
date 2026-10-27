"""Local phase-only lowering of NIST f121049 (three CCX and two CCZ).

Terminal products t1 and t4 contribute only to the phase, so they are not
materialized. t0 = a0 + h1 removes a redundant linear component. Nonterminal
products remain live until every phase and measurement correction using them
has completed. The scalar lowering derives from NIST f121049; see NIST_f121049.txt.
"""
from collections import Counter


def product(a, b):
    out = set()
    for u in a:
        for v in b:
            w = u | v
            if w in out:
                out.remove(w)
            else:
                out.add(w)
    return frozenset(out)



# Symbolic node IDs: b0,b1,b2,h0,h1,h2,t0,t1,t2,t3,t4.
GATES = [([4], [2]),
         ([5, 4, 2], [2, 1]),
         ([1], [6, 5, 3, 2]),
         ([1], [6, 3, 2]),
         ([8, 2, 1, 0], [6, 9, 3, 2, 1, 0])]
ANCHORS = [(4, 2), (5, 1), (1, 5), (1, 3), (8, 9)]
OUTPUT = [7, 10, 6, 1, 0]
TERMINAL = {1, 4}


def evaluate(x):
    nodes = [x >> i & 1 for i in range(6)]
    for left, right in GATES:
        nodes.append((sum(nodes[i] for i in left) & 1)
                     & (sum(nodes[i] for i in right) & 1))
    return sum(nodes[i] for i in OUTPUT) & 1


def parity_ops(nodes, i):
    left, right = GATES[i]
    a, b = ANCHORS[i]
    assert a in left and a not in right and b in right and b not in left
    ops = [('CX', nodes[j], nodes[a]) for j in left if j != a]
    ops += [('CX', nodes[j], nodes[b]) for j in right if j != b]
    return ops, nodes[a], nodes[b]


def emit_scalar(m, inputs, scratch, root):
    assert len(inputs) == 6 and len(scratch) == 5
    assert len(set(inputs + scratch + [root])) == 12
    nodes = inputs + scratch
    forward, erase = [], []
    for i in [0, 1]:
        cx, left, right = parity_ops(nodes, i)
        gate = ('CCZ', root, left, right) if i in TERMINAL else ('CCX', left, right, scratch[i])
        forward += cx + [gate] + list(reversed(cx))
    b0, b1, b2, h0, h1, h2 = inputs
    t0, _, t2, t3, _ = scratch
    # Keep S = h0 + t0 + b2 in the h0 wire across the sibling products.
    # Toggle h2 once to compute t2, then restore every input before t4.
    forward += [('CX', t0, h0), ('CX', b2, h0), ('CCX', b1, h0, t3),
                ('CX', h2, h0), ('CCX', b1, h0, t2), ('CX', h2, h0),
                ('CX', b2, h0), ('CX', t0, h0)]
    cx, left, right = parity_ops(nodes, 4)
    forward += cx + [('CCZ', root, left, right)] + list(reversed(cx))
    phase = [('CZ', root, nodes[i]) for i in [6, 1, 0]]
    # S and S+h2 are also shared between the two measurement corrections.
    # Each classical result is consumed before bit 0 is overwritten.
    erase = [('HMR', t2, 0), ('CX', t0, h0), ('CX', b2, h0), ('CX', h2, h0),
             ('CZif', b1, h0, 0), ('CX', h2, h0), ('HMR', t3, 0),
             ('CZif', b1, h0, 0), ('CX', b2, h0), ('CX', t0, h0),
             ('HMR', t0, 0), ('CZif', h1, b2, 0)]
    return forward, phase, erase


def execute(ops, initial, measurement_start):
    q, phase, outcomes, bits, largest = initial[:], frozenset(), 0, {}, 0
    for op in ops:
        gate = op[0]
        if gate == 'CX':
            q[op[2]] ^= q[op[1]]
        elif gate == 'CCX':
            q[op[3]] ^= product(q[op[1]], q[op[2]])
        elif gate == 'CCZ':
            phase ^= product(q[op[1]], product(q[op[2]], q[op[3]]))
        elif gate == 'CZ':
            phase ^= product(q[op[1]], q[op[2]])
        elif gate == 'HMR':
            outcome = frozenset([1 << (measurement_start + outcomes)])
            outcomes += 1
            bits[op[2]] = outcome
            phase ^= product(outcome, q[op[1]])
            q[op[1]] = frozenset()
        elif gate == 'CZif':
            phase ^= product(bits[op[3]], product(q[op[1]], q[op[2]]))
        else:
            raise ValueError(op)
        largest = max(largest, len(phase), *(len(v) for v in q))
    return q, phase, outcomes, largest


def verify(m, target_values):
    assert all(evaluate(x) == target_values[x] for x in range(64))
    initial = [frozenset() for _ in range(45)]
    for i in range(7):
        initial[i] = frozenset([1 << i])
    parts = emit_scalar(m, list(range(6)), list(range(7, 12)), 6)
    ops = sum(parts, [])
    q, phase, outcomes, largest = execute(ops, initial, 7)
    coeffs = target_values[:]
    for bit in range(6):
        for x in range(64):
            if x >> bit & 1:
                coeffs[x] ^= coeffs[x ^ (1 << bit)]
    expected = frozenset(x | 1 << 6 for x, c in enumerate(coeffs) if c)
    assert q == initial, 'input or workspace not restored'
    assert phase == expected, 'target or measurement phase mismatch'
    rejected = 0
    for i, op in enumerate(ops):
        if op[0] in ('CZ', 'CZif', 'CCZ'):
            bad_q, bad_phase, _, _ = execute(ops[:i] + ops[i + 1:], initial, 7)
            assert bad_q != initial or bad_phase != expected, 'missing phase gate accepted'
            rejected += 1
    counts = dict(Counter(op[0] for op in ops))
    assert counts == {'CCX': 3, 'CX': 34, 'CCZ': 2, 'CZ': 3, 'HMR': 3, 'CZif': 3}
    return {
        'status': 'PASS', 'function_inputs_exhaustive': 64,
        'root_branches': 2, 'independent_measurement_outcomes': outcomes,
        'symbolic_scope': 'all 7 input bits and every independent X outcome; exact Boolean ANF',
        'all_input_and_scratch_wires_restored': True,
        'relative_phase_exact': True, 'negative_deleted_phase_gates_rejected': rejected,
        'largest_polynomial_monomials': largest, 'op_counts': counts,
        'Toffoli_like': 5, 'active_wires': 10,
        'scratch': {'nonterminal_AND_results': 3, 'parity_and_product_pivots': 0},
        'attribution': 'NIST f121049 with linear normalization, shared sibling parities, and terminal phase-only lowering',
    }, ops
