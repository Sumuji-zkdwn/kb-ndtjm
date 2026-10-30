#!/usr/bin/env python3
"""Local GF(2^12) multiplication probe; not integrated into complete DQI.

Reuse the attributed KT6 tower tensor (45 CCX) or published KT12 tensor
(42 CCX), from andigu/uncompute under Apache-2.0.
Verify the actual Boolean circuit including arbitrary targets and all HMR
branches. This does not change the 141-Toffoli quotient currently tested in CI.
"""
import argparse
from collections import Counter
from functools import reduce
import hashlib
import json
from operator import xor
from pathlib import Path
import struct
import sys
import types
import zipfile

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'research/inverse66'))
from formal_probe import mul, product
from quotient_probe import parse


def support(mask):
    return [i for i in range(12) if mask >> i & 1]


def decomposition(kind):
    archive = ROOT / 'research/inverse66/tower_inverse66_probe.zip'
    with zipfile.ZipFile(archive) as source:
        code = source.read('tower_inverse66.py').decode()
    module = types.ModuleType('archived_tower')
    exec(compile(code, 'archived/tower_inverse66.py', 'exec'), module.__dict__)
    module.change_to_google_basis()
    columns = module.LIN['E12']
    a0, a1 = module.LIN['A0ROWS'], module.LIN['A1ROWS']
    rows = a0 + a1
    # The input maps must be the inverse of the claimed tower basis.
    assert all(sum(((r & value).bit_count() % 2) << i for i, r in enumerate(rows))
               == 1 << j for j, value in enumerate(columns))
    w = columns[6]
    assert all(columns[6+i] == mul(w, columns[i]) for i in range(6))
    for i in range(6):
        for j in range(6):
            got = reduce(xor, (columns[k] for a, b, c in module.KT6
                               if i in a and j in b for k in c), 0)
            assert got == mul(columns[i], columns[j])
    # (a0+a1*w)(b0+b1*w) = p0*(1+w)+p1*(w*w+w)+p2*w,
    # with p0=a0*b0, p1=a1*b1, p2=(a0+a1)*(b0+b1).
    terms = []
    if kind == 'tower45':
        for projection, factor in [(a0, 1 ^ w), (a1, mul(w, w) ^ w),
                                   ([x ^ y for x, y in zip(a0, a1)], w)]:
            for a, b, c in module.KT6:
                left = reduce(xor, (projection[i] for i in a), 0)
                right = reduce(xor, (projection[i] for i in b), 0)
                target = mul(reduce(xor, (columns[i] for i in c), 0), factor)
                assert left and right and target
                terms.append((left, right, target))
        assert len(terms) == 45
    elif kind == 'public42':
        def phi(value):
            return reduce(xor, (module.PHI_COLUMNS[i] for i in support(value)), 0)
        inverse = [None] * 4096
        for public in range(4096):
            google = phi(public)
            assert inverse[google] is None
            inverse[google] = public
        inverse_rows = [sum(((inverse[1 << j] >> i) & 1) << j for j in range(12))
                        for i in range(12)]
        constants = json.loads(Path(__file__).with_name('public42-constants.json').read_text())
        assert constants['source_polynomial'] == '0x10eb'
        for a, b, c in constants['KT12']:
            for indices in (a, b, c):
                assert indices and len(indices) == len(set(indices)) and all(0 <= i < 12 for i in indices)
            terms.append((reduce(xor, (inverse_rows[i] for i in a), 0),
                          reduce(xor, (inverse_rows[i] for i in b), 0),
                          phi(sum(1 << i for i in c))))
        assert len(terms) == 42
    else:
        raise ValueError(kind)
    # Bilinearity makes these 144 basis pairs an exhaustive tensor equality.
    for i in range(12):
        for j in range(12):
            got = reduce(xor, (t for a, b, t in terms if a >> i & 1 and b >> j & 1), 0)
            assert got == mul(1 << i, 1 << j)
    return terms, hashlib.sha256(archive.read_bytes()).hexdigest()


def parity_network(mask, offset):
    wires = [offset + i for i in support(mask)]
    return wires[0], [('CX', [q, wires[0]], None) for q in wires[1:]]


def xor_product_naive(terms, target_offset):
    operations = []
    for a, b, target in terms:
        left, an = parity_network(a, 0)
        right, bn = parity_network(b, 12)
        out = [target_offset + i for i in support(target)]
        fanout = [('CX', [out[0], q], None) for q in out[1:]]
        operations += an + bn + fanout
        operations.append(('CCX', [left, right, out[0]], None))
        operations += list(reversed(fanout)) + list(reversed(bn)) + list(reversed(an))
    return operations


def inverse_rows(rows):
    left, right = rows[:], [1 << i for i in range(12)]
    for column in range(12):
        pivot = next(i for i in range(column, 12) if left[i] >> column & 1)
        left[column], left[pivot] = left[pivot], left[column]
        right[column], right[pivot] = right[pivot], right[column]
        for i in range(12):
            if i != column and left[i] >> column & 1:
                left[i] ^= left[column]
                right[i] ^= right[column]
    assert left == [1 << i for i in range(12)]
    return right


def xor_product(terms, target_offset):
    """Keep linear input/output frames between products, then restore them.

    Each frame is an invertible 12x12 binary matrix. Inputs expose the required
    parities in one physical wire; the output frame maps the desired XOR mask
    to one physical wire. A single CCX then adds that rank-one tensor term.
    """
    frames = [[1 << i for i in range(12)] for _ in range(3)]
    offsets, operations = [0, 12, target_offset], []

    def cx(block, source, target):
        operations.append(('CX', [offsets[block]+source, offsets[block]+target], None))
        frames[block][target] ^= frames[block][source]

    pending = list(terms)
    while pending:
        ai, bi = inverse_rows(frames[0]), inverse_rows(frames[1])

        def coordinates(term):
            a, b, t = term
            ac = reduce(xor, (ai[i] for i in support(a)), 0)
            bc = reduce(xor, (bi[i] for i in support(b)), 0)
            tc = sum(((row & t).bit_count() % 2) << i for i, row in enumerate(frames[2]))
            return ac, bc, tc

        choices = [coordinates(term) for term in pending]
        index = min(range(len(pending)), key=lambda i: sum(v.bit_count()-1 for v in choices[i]))
        masks = choices[index]
        term = pending.pop(index)
        pivots = [support(mask)[0] for mask in masks]
        for block in range(2):
            for i in support(masks[block])[1:]:
                cx(block, i, pivots[block])
            assert frames[block][pivots[block]] == term[block]
        for i in support(masks[2])[1:]:
            cx(2, pivots[2], i)
        assert sum(((row & term[2]).bit_count() % 2) << i for i, row in enumerate(frames[2])) == 1 << pivots[2]
        operations.append(('CCX', [offsets[i]+pivots[i] for i in range(3)], None))

    # Gaussian row operations implement each frame's inverse on the wires.
    for block in range(3):
        for column in range(12):
            pivot = next(i for i in range(column, 12) if frames[block][i] >> column & 1)
            if pivot != column:
                operations.append(('SWAP', [offsets[block]+column, offsets[block]+pivot], None))
                frames[block][column], frames[block][pivot] = frames[block][pivot], frames[block][column]
            for i in range(12):
                if i != column and frames[block][i] >> column & 1:
                    cx(block, column, i)
        assert frames[block] == [1 << i for i in range(12)]
    return operations


def controlled_product(terms):
    # a=q0..11, b=q12..23, arbitrary t=q24..35, coherent c=q36,
    # clean product workspace=q37..48. Reuse the pinned upstream phase cleanup.
    import kickmix as km
    builder = km.CircuitBuilder()
    q = builder.create_quantum_register(49, name='local')
    builder.del_gf2_mul(q[:12], q[12:24], target=q[37:49], field=km.GF2Field(12))
    cleanup = builder.finish_circuit()
    clear = [('BIT_STORE0', [i], None) for i in range(cleanup.num_bits)]
    operations = clear + xor_product(terms, 37)
    operations += [('CCX', [36, 37+i, 24+i], None) for i in range(12)]
    operations += parse(str(cleanup)) + clear
    return operations


def verify(operations, controlled):
    inputs, count = (37, 49) if controlled else (36, 36)
    q = [frozenset({1 << i}) if i < inputs else frozenset() for i in range(count)]
    initial, expected = q[:], q[:]
    for i in range(12):
        for j in range(12):
            term = product(initial[i], initial[12+j])
            if controlled:
                term = product(term, initial[36])
            for k in support(mul(1 << i, 1 << j)):
                expected[24+k] ^= term
    phase, bits, measurements = frozenset(), {}, 0
    for gate, wires, condition in operations:
        if gate == 'CX' and condition is None:
            q[wires[1]] ^= q[wires[0]]
        elif gate == 'CCX' and condition is None:
            q[wires[2]] ^= product(q[wires[0]], q[wires[1]])
        elif gate == 'SWAP' and condition is None:
            q[wires[0]], q[wires[1]] = q[wires[1]], q[wires[0]]
        elif gate == 'R' and condition is None:
            assert not q[wires[0]], 'reset of nonzero symbolic qubit'
        elif gate == 'HMR' and condition is None:
            value = frozenset({1 << (inputs + measurements)})
            measurements += 1
            bits[wires[1]] = value
            phase ^= product(value, q[wires[0]])
            q[wires[0]] = frozenset()
        elif gate == 'CZ':
            term = product(q[wires[0]], q[wires[1]])
            phase ^= product(term, bits[condition]) if condition is not None else term
        elif gate == 'BIT_STORE0' and condition is None:
            bits[wires[0]] = frozenset()
        elif gate == 'BIT_INVERT':
            bits[wires[0]] ^= bits[condition] if condition is not None else frozenset({0})
        else:
            raise ValueError((gate, wires, condition))
    assert q == expected, 'incorrect product, changed inputs, or dirty workspace'
    assert not phase, 'uncancelled measurement-dependent phase'
    assert all(not value for value in bits.values()), 'dirty private measurement record'
    return {'status': 'PASS', 'method': 'exact Boolean ANF',
            'input_variables': inputs, 'independent_measurement_variables': measurements,
            'measurement_branches_represented': f'2^{measurements}',
            'arbitrary_xor_target': True, 'coherent_control': controlled,
            'inputs_restored': True, 'quantum_workspace_clean': True,
            'temporary_classical_bits_clean': True, 'residual_phase_monomials': 0}


def text(operations, controlled):
    lines = ['# LOCAL GF(2^12) multiplier probe; polynomial 0x1053; not complete DQI.',
             '# a=q0..11; b=q12..23; arbitrary XOR target=q24..35.',
             '# Attributed bilinear/tower constants: andigu/uncompute, Apache-2.0.']
    if controlled:
        lines.append('# Coherent control=q36; clean workspace=q37..48; private bits=b0..12.')
    for gate, wires, condition in operations:
        operands = [('b' if gate.startswith('BIT_') or (gate == 'HMR' and i == 1) else 'q') + str(wire)
                    for i, wire in enumerate(wires)]
        lines.append(gate + ' ' + ' '.join(operands)
                     + ('' if condition is None else f' if b{condition}'))
    return '\n'.join(lines) + '\n'


def audit_reference(path, term_count):
    """Read-only mapping audit for the 32,408 EEA controlled multiplications."""
    import kickmix as km
    import numpy as np
    sys.path.insert(0, str(ROOT / 'quantum'))
    from dqi_gate import sha
    from eea_quotient_dqi import REFERENCE_SHA, instructions, match_template
    from inverse66_dqi import prefix_counts, read_ops
    from wfs_dqi_single_site import KMB
    assert sha(path) == REFERENCE_SHA
    k = KMB(path)
    packet, _ = k.packets[11]
    count = struct.unpack_from('<Q', k.data, packet)[0]
    ends = np.frombuffer(k.data, dtype='<u8', count=count, offset=packet+8)
    text_start = packet+8+8*count
    positions = np.flatnonzero(k.ops == 6)
    assert len(positions) == count
    stack, sites, previous = [], [], 0
    for i, end in enumerate(ends):
        end = int(end)
        tag = k.data[text_start+previous:text_start+end].decode()
        previous = end
        if tag.startswith('@enter:'):
            stack.append((tag[7:], int(positions[i])))
        elif tag.startswith('@exit:'):
            name, start = stack.pop()
            assert name == tag[6:]
            if name == 'gf_mul' and stack and stack[-1][0] == 'c_gf_mul':
                sites.append((start+1, int(positions[i]), stack[0][0]))
    assert not stack and len(sites) == 32408
    builder = km.CircuitBuilder()
    q = builder.create_quantum_register(36, name='external')
    builder.ixor_gf2_mul(q[:12], q[12:24], target=q[24:36], field=km.GF2Field(12))
    template = instructions(str(builder.finish_circuit()))
    assert all(not op & 192 for op, _ in template)
    boundaries = np.asarray(sorted({p for start, stop, _ in sites for p in (start, stop)}))
    rank = {p: prefix_counts(k.ops, boundaries, p) for p in range(2, 10)}
    manifest_hash, stages, first = hashlib.sha256(), Counter(), {}
    for start, stop, stage in sites:
        actual = read_ops(k, start, stop, rank)
        qmap, bmap = match_template(template, actual)
        assert set(qmap) == set(range(36)) and not bmap
        row = {'stage': stage, 'start': start, 'stop': stop,
               'a': [qmap[i] for i in range(12)],
               'b': [qmap[i] for i in range(12, 24)],
               'product': [qmap[i] for i in range(24, 36)]}
        manifest_hash.update((json.dumps(row, sort_keys=True)+'\n').encode())
        stages[stage] += 1
        first.setdefault(stage, row)
    return {'status': 'PASS', 'mode': 'read-only; input circuit unchanged',
            'reference_dqi_sha256': REFERENCE_SHA, 'matched_sites': len(sites),
            'per_stage': dict(stages), 'first_mapping_per_stage': first,
            'all_old_instructions_matched_under_injective_renaming': True,
            'classical_bits_or_conditions_in_replaced_span': 0,
            'canonical_mapping_manifest_sha256': manifest_hash.hexdigest(),
            'static_toffoli_saved_if_integrated': (63-term_count)*len(sites),
            'full_DQI_generation': 'NOT_RUN', 'full_DQI_verifier': 'NOT_RUN'}


def main():
    import kickmix as km
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path)
    parser.add_argument('--tensor', choices=['tower45', 'public42'], default='public42')
    parser.add_argument('--reference', type=Path, help='Optional pinned Forney full-DQI read-only caller audit')
    args = parser.parse_args()
    if args.out is None:
        args.out = Path(__file__).parent / f'multiply-{args.tensor}-local'
    args.out.mkdir(parents=True, exist_ok=True)
    terms, archive_sha = decomposition(args.tensor)
    naive = xor_product_naive(terms, 24)
    naive_proof = verify(naive, False)
    result = {'scope': 'local multiplier only; complete DQI integration NOT_RUN',
              'field_polynomial': '0x1053', 'tensor': args.tensor, 'bilinear_tensor_terms': len(terms),
              'tensor_basis_pairs_checked': 144,
              'attribution': 'Bilinear tensors and tower basis: andigu/uncompute (Apache-2.0)',
              'archive_sha256': archive_sha,
              'source_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
              'trusted_boundary': 'Python finite-field and ANF checker; not Lean checked',
              'variants': {}, 'complete_DQI': 'NOT_RUN', 'official_verifier': 'NOT_RUN',
              'kaggle_submission': 'NOT_RUN'}
    result['linear_schedule'] = {'method': 'greedy invertible input/output frames; exact restoration',
                                 'unoptimized_xor_op_counts': dict(Counter(g for g, _, _ in naive)),
                                 'unoptimized_xor_certificate': naive_proof}
    if args.tensor == 'public42':
        constants_path = Path(__file__).with_name('public42-constants.json')
        constants = json.loads(constants_path.read_text())
        result['constants_source'] = {k: v for k, v in constants.items() if k != 'KT12'}
        result['constants_sha256'] = hashlib.sha256(constants_path.read_bytes()).hexdigest()
    for controlled in (False, True):
        name = 'controlled' if controlled else 'xor'
        ops = controlled_product(terms) if controlled else xor_product(terms, 24)
        proof = verify(ops, controlled)
        source = text(ops, controlled)
        circuit = km.Circuit(source)
        want_t, want_q = (len(terms)+12, 49) if controlled else (len(terms), 36)
        assert circuit.num_qubits == want_q
        assert circuit.operation_statistics().num_toffoli_like == want_t
        # Measure the pinned upstream API for this identical external contract.
        builder = km.CircuitBuilder()
        q = builder.create_quantum_register(37 if controlled else 36, name='external')
        kwargs = {'control': q[36]} if controlled else {}
        builder.ixor_gf2_mul(q[:12], q[12:24], target=q[24:36], field=km.GF2Field(12), **kwargs)
        old = builder.finish_circuit()
        baseline_t = int(old.operation_statistics().num_toffoli_like)
        assert baseline_t == (75 if controlled else 63)
        clear = [('BIT_STORE0', [i], None) for i in range(old.num_bits)]
        old_proof = verify(clear + parse(str(old)) + clear, controlled)
        (args.out / f'multiply-{name}.kmx').write_text(source)
        result['variants'][name] = {'certificate': proof, 'kickmix_parse': 'PASS',
                                   'qubits': circuit.num_qubits, 'static_toffoli': want_t,
                                   'upstream_qubits': old.num_qubits,
                                   'upstream_static_toffoli': baseline_t,
                                   'upstream_certificate': old_proof,
                                   'op_counts': dict(Counter(g for g, _, _ in ops)),
                                   'kmx_sha256': hashlib.sha256(source.encode()).hexdigest()}
        bad = ops[:]
        if controlled:
            index = next(i for i, (g, _, c) in enumerate(bad) if g == 'CZ' and c is not None)
        else:
            index = next(i for i, (g, _, _) in enumerate(bad) if g == 'CCX')
        del bad[index]
        try:
            verify(bad, controlled)
        except AssertionError:
            result['variants'][name]['negative_control'] = 'REJECTED'
        else:
            raise AssertionError('damaged circuit was accepted')
    if args.reference:
        result['read_only_DQI_caller_audit'] = audit_reference(args.reference, len(terms))
    (args.out / 'report.json').write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
