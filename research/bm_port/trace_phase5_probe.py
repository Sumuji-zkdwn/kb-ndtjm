"""Exact local certificate for the 68-Toffoli-like Forney phase variant.

Trust boundary: Python Boolean-polynomial arithmetic and the stated composition
argument. No Lean proof, native Kickmix execution, full DQI or Kaggle result.
"""
from collections import Counter
import hashlib
import json
from pathlib import Path
import time

from trace_phase5 import TracePhase5
from trace_phase3 import TracePhase3
from trace_phase import lin, convert
from trace_phase_probe import kmx
from trace_phase5_scalar import verify as verify_scalar, emit_scalar
from functools import lru_cache
from trace_phase import tower

ROOT = Path(__file__).resolve().parent


@lru_cache(maxsize=1)
def target_table():
    m = tower()
    basis = m.LIN['E12'][:3]
    def embed(v):
        out = 0
        for i, b in enumerate(basis):
            if v >> i & 1:
                out ^= b
        return out
    def trace(x):
        return x ^ m.gf_pow(x, 2) ^ m.gf_pow(x, 4)
    values = [trace(m.gf_mul(embed(x >> 3), m.gf_pow(embed(x & 7), 6)))
              for x in range(64)]
    assert all(v in (0, 1) for v in values)
    coeffs = values[:]
    for bit in range(6):
        for x in range(64):
            if x >> bit & 1:
                coeffs[x] ^= coeffs[x ^ (1 << bit)]
    return values, basis, [i for i, c in enumerate(coeffs) if c]




def product(a, b):
    # In the Boolean quotient C*C=C; remove shared terms before cross products.
    common = a & b
    left, right = a - common, b - common
    out = set(common)
    for u, v in ((left, right), (common, left ^ right)):
        for x in u:
            for y in v:
                term = x | y
                if term in out:
                    out.remove(term)
                else:
                    out.add(term)
    return frozenset(out)


def execute(ops, initial, mask_start, measurement_start, phase=frozenset()):
    q, bits, outcomes, largest = initial[:], {}, 0, 0
    for gate, v, condition in ops:
        if gate == 'CX':
            term = q[v[0]]
            if condition is not None:
                term = product(term, frozenset([1 << (mask_start + condition)]))
            q[v[1]] ^= term
        elif gate == 'SWAP':
            q[v[0]], q[v[1]] = q[v[1]], q[v[0]]
        elif gate == 'CCX':
            q[v[2]] ^= product(q[v[0]], q[v[1]])
        elif gate == 'CCZ':
            phase ^= product(q[v[0]], product(q[v[1]], q[v[2]]))
        elif gate == 'HMR':
            result = frozenset([1 << (measurement_start + outcomes)])
            outcomes += 1
            bits[condition] = result
            phase ^= product(result, q[v[0]])
            q[v[0]] = frozenset()
        elif gate in ('Z', 'CZ'):
            term = q[v[0]] if gate == 'Z' else product(q[v[0]], q[v[1]])
            if condition is not None:
                term = product(bits[condition], term)
            phase ^= term
        else:
            raise ValueError(gate)
        largest = max(largest, len(phase), *(len(x) for x in q))
    return q, phase, outcomes, largest


def prefix_certificate(p):
    initial = [frozenset() for _ in range(70)]
    for i in range(12):
        initial[i] = frozenset([1 << i])
    q, phase, n, largest = execute(p.forward, initial, 0, 12)
    assert not phase
    values = []
    for d in range(4096):
        a = p.f.mul(d, p.f.pow(d, 64))
        b = p.f.mul(a, p.f.pow(a, 8))
        ac = lin(p.m.LIN['A0ROWS'], a)
        bc = lin(p.m.LIN['A0ROWS'], b)
        assert bc < 8 and p.f.pow(a, 64) == a and p.f.pow(b, 8) == b
        values.append(ac | (bc << 6))
    for bit in range(12):
        for d in range(4096):
            if d >> bit & 1:
                values[d] ^= values[d ^ (1 << bit)]
    expected = [frozenset(d for d, c in enumerate(values) if c >> j & 1) for j in range(9)]
    assert q[24:33] == expected
    after, cleanup_phase, n2, large2 = execute(p.erase, q, 0, 12 + n)
    assert after == initial and not cleanup_phase
    return {'status': 'PASS', 'field_inputs': 4096, 'all_norm6_and_norm3_outputs': True,
            'independent_measurement_variables': n + n2,
            'workspace_clean': True, 'cleanup_phase_identically_zero': True,
            'largest_polynomial_monomials': max(largest, large2),
            'composition': 'The eraser has zero incremental phase for every outcome and restores D/scratch. Any previously applied phase on the computed norm values is therefore preserved.'}


def middle_certificate(p):
    initial = [frozenset() for _ in range(70)]
    for i in range(12):
        initial[i] = frozenset([1 << i])
        initial[58 + i] = frozenset([1 << (12 + i)])
    for i in range(6):
        initial[24 + i] = frozenset([1 << (24 + i)])
    for i in range(3):
        initial[30 + i] = frozenset([1 << (30 + i)])
    initial[57] = frozenset([1 << 33])
    # D12, N12, A6, B3, root1, mask12; 46 independent inputs.
    # Exact composition avoids expanding products between the large correlated
    # H polynomials inside a4. Prove the scalar block on independent B,H,r first,
    # check literal operation correspondence, then substitute the actual values.
    scalar_proof, scalar_ops = verify_scalar(p.m, target_table()[0])
    scalar_map = dict(zip(range(6), p.scalar_inputs))
    scalar_map.update({6: 57, **dict(zip(range(7, 12), p.scalar_scratch)),
                       42: 42, 43: 43, 44: 44})
    mapped = [(g, [scalar_map[v] for v in wires], c) for g, wires, c in convert(scalar_ops)]
    assert mapped == p.scalar_forward + p.scalar_pairing + p.scalar_erase
    def flatten(steps):
        copy = [('CX', [58 + i, 45 + i], None) for i in range(12)]
        return [op for step in steps for op in (copy if step is None else step)]
    steps = p.middle_steps()
    pre, post = flatten(steps[:5]), flatten(steps[8:])
    assert p.middle() == pre + mapped + post
    before, pre_phase, n_pre, largest_pre = execute(pre, initial, 34, 46)
    assert not pre_phase
    assert all(not before[v] for v in p.scalar_scratch + [42, 43, 44])
    nodes = [before[v] for v in p.scalar_inputs]
    scalar_phase = frozenset()
    for monomial in target_table()[2]:
        term = before[57]
        for i in range(6):
            if monomial >> i & 1:
                term = product(term, nodes[i])
        scalar_phase ^= term
    n_scalar = scalar_proof['independent_measurement_outcomes']
    q, phase, n_post, largest_post = execute(post, before, 34, 46 + n_pre + n_scalar, scalar_phase)
    n, largest = n_pre + n_scalar + n_post, max(largest_pre, largest_post)
    assert q == initial, 'middle changed input or left dirty scratch'
    expected = set()
    basis_cases = 0
    inverse_b = [p.f.inv(p.embed3(b)) for b in range(8)]
    for i in range(12):
        for j in range(12):
            v = p.f.mul(1 << j, p.f.pow(1 << i, 64))
            for a in range(6):
                va = p.f.mul(v, p.f.pow(p.embed(1 << a), 8))
                coefficients = [p.f.mul(va, inverse_b[b]) for b in range(8)]
                for bit in range(3):
                    for b in range(8):
                        if b >> bit & 1:
                            coefficients[b] ^= coefficients[b ^ (1 << bit)]
                assert coefficients[0] == 0 and coefficients[7] == 0
                for b, coefficient in enumerate(coefficients):
                    for k in range(12):
                        basis_cases += 1
                        if coefficient >> k & 1:
                            term = ((1 << i) | (1 << (12 + j)) | (1 << (24 + a))
                                    | (b << 30) | (1 << 33) | (1 << (34 + k)))
                            if term in expected:
                                expected.remove(term)
                            else:
                                expected.add(term)
    assert phase == frozenset(expected), 'ideal field phase or measurement phase mismatch'
    assert all(term >> 46 == 0 for term in phase), 'measurement outcomes remain in phase'
    return {'status': 'PASS', 'independent_inputs': 46,
            'independent_measurement_variables': n,
            'coefficient_comparisons': basis_cases,
            'all_masks_and_root_branches': True,
            'all_inputs_and_scratch_restored': True,
            'phase_monomials': len(expected), 'largest_polynomial_monomials': largest,
            'ideal': 'root * parity(mask & (N * D^64 * A^8 * inv(embed3(B))))',
            'method': 'exact ANF for pre/post and field reference; independently certified scalar circuit substituted after literal operation-list correspondence',
            'scalar_proof_substitution': True,
            'measurement_count_breakdown': [n_pre, n_scalar, n_post]}


def verify(p=None):
    started = time.monotonic()
    p, baseline = (p or TracePhase5()), TracePhase3()
    nist = json.loads((ROOT / 'nist_bent_mc5.json').read_text())
    assert len(nist) == 1 and nist[0]['name'] == 'f121049'
    assert nist[0]['truth_table'] == target_table()[0]
    # The retained stages are byte-for-byte the same operation lists.
    for attr in ('coefficient_forward', 'coefficient_erase', 'nested_forward', 'nested_erase', 'masked'):
        assert getattr(p, attr) == getattr(baseline, attr)
    scalar, _ = verify_scalar(p.m, target_table()[0])
    prefix = prefix_certificate(p)
    middle = middle_certificate(p)
    counts = Counter(g for g, _, _ in p.operations())
    old_counts = Counter(g for g, _, _ in baseline.operations())
    assert counts['CCX'] + counts['CCZ'] == 68
    assert old_counts['CCX'] + old_counts['CCZ'] == 69
    assert max(q for _, wires, _ in p.operations() for q in wires) == 69
    assert p.scalar_scratch == [33, 34, 35, 39, 40]
    # The same inherited emitter maps canonical wires and mask/measurement bits.
    class Recorder:
        def __init__(self):
            self.ops = []
        def raw(self, opcode, wires, bit=None, cond=None):
            self.ops.append((opcode, wires, bit, cond))
        def cx(self, a, b):
            self.raw(0x21, [a, b])
    recorder = Recorder()
    mapping = [1000 + 7 * i for i in range(58)]
    pairs = [(9000 + 3 * i, mapping[45 + i]) for i in range(12)]
    masks = [12000 + 5 * i for i in range(12)]
    p.emit(recorder, mapping, masks, pairs)
    opcodes = {'CX': 0x21, 'CCX': 0x31, 'CCZ': 0x30, 'SWAP': 0x22, 'CZ': 0x20, 'Z': 0x10}
    physical = mapping + [s for s, _ in pairs]
    expected_emit = []
    for gate, wires, condition in p.operations():
        qs = [physical[q] for q in wires]
        if gate == 'HMR':
            expected_emit.append((0x50, qs, 49141, None))
        else:
            cond = None if condition is None else (49141 if gate in ('Z', 'CZ') else masks[condition])
            expected_emit.append((opcodes[gate], qs, None, cond))
    assert recorder.ops == expected_emit, 'physical emitter differs from proved operation list'
    circuit = kmx(p.operations()).replace('via relative trace;', 'via 5-AND scalar trace;')
    result = {
        'status': 'PASS', 'scope': 'local Forney inverse/phase replacement only',
        'scalar': scalar, 'prefix': prefix, 'middle': middle,
        'published_NIST_truth_table_identity': 'PASS, f121049 matches all 64 values',
        'retained_G_H_mask_stages_identical': True,
        'physical_emitter_correspondence': 'PASS, nontrivial qubit and mask mapping',
        'old_Toffoli_like_per_point': 69, 'new_Toffoli_like_per_point': 68,
        'root_tree_unchanged': 11, 'old_Forney_per_point': 80, 'new_Forney_per_point': 79,
        'op_counts_baseline': dict(old_counts), 'op_counts_candidate': dict(counts),
        'baseline_total_operations': sum(old_counts.values()), 'candidate_total_operations': sum(counts.values()),
        'workspace_mapping': {'B': [30, 31, 32], 'H': [36, 37, 38],
                              'available_scalar_scratch': p.scalar_scratch, 'used_AND_results': [33, 35, 39], 'existing_pivots': [42, 43, 44]},
        'extra_physical_wires_required_by_local_replacement': 0,
        'conditional_full_DQI_projection': {'Toffoli_like': 715786, 'Q': 2482,
                                           'savings': 4095, 'Toffoli_percent': 100 * 4095 / 719881},
        'full_DQI_built': False, 'native_full_DQI_Kickmix_parser': 'NOT_RUN',
        'official_verifier': 'NOT_RUN', 'kaggle_submission': 'NOT_RUN',
        'seconds': time.monotonic() - started,
        'circuit_sha256': hashlib.sha256(circuit.encode()).hexdigest(),
        'trusted_boundary': 'Python exact ANF and compositional reasoning; no Lean kernel',
    }
    return result


if __name__ == '__main__':
    import argparse
    import kickmix as km
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    phase = TracePhase5()
    result = verify(phase)
    circuit_text = kmx(phase.operations()).replace('via relative trace;', 'via 5-AND scalar trace;')
    (args.out / 'trace-phase5.kmx').write_text(circuit_text)
    circuit = km.Circuit(circuit_text)
    assert circuit.operation_statistics().num_toffoli_like == 68
    result['native_parse'] = 'PASS'
    result['local_qubits'] = circuit.num_qubits
    result['local_bits'] = circuit.num_bits
    (args.out / 'report.json').write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps(result, indent=2))
