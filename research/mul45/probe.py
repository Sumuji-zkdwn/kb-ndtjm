#!/usr/bin/env python3
"""45-Toffoli GF(2^12) XOR multiplication, with zero extra workspace.

Reuse the attributed KT6/basis data from the pinned inverse66 source archive.
All gates are CX/CCX: this is an exact permutation unitary, with no measurement
records or measurement phase corrections. No Kaggle submission functionality.
"""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import sys
import types
import zipfile

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'research/inverse66'))
from formal_probe import mul, product

ARCHIVE_SHA = '25c74454ef8c00b44bb42177f491c196743f3dedd24e3ec5f096fbb60e6c19c3'


def xor(values):
    result = 0
    for value in values:
        result ^= value
    return result


def parity_rows(rows, value):
    return sum(((row & value).bit_count() & 1) << i for i, row in enumerate(rows))


def decomposition():
    archive = ROOT / 'research/inverse66/tower_inverse66_probe.zip'
    assert hashlib.sha256(archive.read_bytes()).hexdigest() == ARCHIVE_SHA
    with zipfile.ZipFile(archive) as z:
        source = z.read('tower_inverse66.py').decode()
    tower = types.ModuleType('attributed_tower')
    exec(compile(source, 'archived/tower_inverse66.py', 'exec'), tower.__dict__)
    tower.change_to_google_basis()

    def embed(value, offset=0):
        return xor(tower.LIN['E12'][i + offset] for i in range(6) if value >> i & 1)

    def mul6(a, b):
        return xor(sum(1 << i for i in cc) for aa, bb, cc in tower.KT6
                   if sum((a >> i) & 1 for i in aa) & 1
                   and sum((b >> i) & 1 for i in bb) & 1)

    t = tower.LIN['E12'][6]
    delta12 = mul(t, t) ^ t
    delta6 = parity_rows(tower.LIN['A0ROWS'], delta12)
    assert parity_rows(tower.LIN['A1ROWS'], delta12) == 0
    assert embed(delta6) == delta12
    for i in range(6):
        for j in range(6):
            assert embed(mul6(1 << i, 1 << j)) == mul(embed(1 << i), embed(1 << j))
    rows0, rows1 = tower.LIN['A0ROWS'], tower.LIN['A1ROWS']
    rows01 = [a ^ b for a, b in zip(rows0, rows1)]
    terms = []
    for rows, output in [(rows0, lambda c: embed(c) ^ embed(c, 6)),
                         (rows1, lambda c: embed(mul6(delta6, c))),
                         (rows01, lambda c: embed(c, 6))]:
        for aa, bb, cc in tower.KT6:
            terms.append((xor(rows[i] for i in aa), xor(rows[i] for i in bb),
                          output(sum(1 << i for i in cc))))
    assert len(terms) == 45 and all(a and b and c for a, b, c in terms)
    for i in range(12):
        for j in range(12):
            actual = xor(c for a, b, c in terms if a >> i & 1 and b >> j & 1)
            assert actual == mul(1 << i, 1 << j)
    return terms, delta6


def compile_ops(terms):
    operations = []
    for am, bm, cm in terms:
        a = [i for i in range(12) if am >> i & 1]
        b = [12 + i for i in range(12) if bm >> i & 1]
        c = [24 + i for i in range(12) if cm >> i & 1]
        # Conjugate by invertible CX maps. Arbitrary target contents are preserved
        # except for the requested XOR; no clean parity or product ancilla is needed.
        before = ([('CX', [i, a[0]]) for i in a[1:]]
                  + [('CX', [i, b[0]]) for i in b[1:]]
                  + [('CX', [c[0], i]) for i in c[1:]])
        operations += before + [('CCX', [a[0], b[0], c[0]])] + list(reversed(before))
    return operations


def ideal_polynomials():
    expected = [frozenset({1 << i}) for i in range(36)]
    for i in range(12):
        for j in range(12):
            coefficient = mul(1 << i, 1 << j)
            monomial = (1 << i) | (1 << (12 + j))
            for bit in range(12):
                if coefficient >> bit & 1:
                    expected[24 + bit] ^= frozenset({monomial})
    return expected


def certify(operations):
    quantum = [frozenset({1 << i}) for i in range(36)]
    for name, wires in operations:
        if name == 'CX':
            quantum[wires[1]] ^= quantum[wires[0]]
        elif name == 'CCX':
            quantum[wires[2]] ^= product(quantum[wires[0]], quantum[wires[1]])
        elif name == 'SWAP':
            a, b = wires
            quantum[a], quantum[b] = quantum[b], quantum[a]
        else:
            raise ValueError('Only positive permutation gates are allowed')
    assert quantum == ideal_polynomials(), 'wrong product or non-restored input/target'
    return {'status': 'PASS', 'method': 'exact Boolean ANF on 36 independent variables',
            'arbitrary_xor_target': True, 'inputs_restored': True,
            'unitary_phase': 'exactly zero: CX/CCX/SWAP positive permutation gates only',
            'measurement_outcomes': 0, 'extra_quantum_workspace': 0,
            'entangled_reference_allowed': True}


def reference_ops():
    import kickmix as km
    sys.path.insert(0, str(ROOT / 'quantum'))
    from eea_quotient_dqi import instructions
    b = km.CircuitBuilder()
    a = b.create_quantum_register(12, name='a')
    rhs = b.create_quantum_register(12, name='b')
    t = b.create_quantum_register(12, name='target')
    field = km.GF2Field(12)
    assert field.modulus == 0x1053
    b.ixor_gf2_mul(a, rhs, target=t, field=field)
    circuit = b.finish_circuit()
    assert circuit.num_qubits == 36 and circuit.num_bits == 0
    encoded = instructions(str(circuit))
    names = {0x21: 'CX', 0x31: 'CCX', 0x22: 'SWAP'}
    return [(names[op], operands) for op, operands in encoded]


def main():
    import kickmix as km
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, default=Path(__file__).parent)
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    terms, delta = decomposition()
    operations = compile_ops(terms)
    certificate = certify(operations)
    old = reference_ops()
    old_certificate = certify(old)
    bad = operations[:]
    del bad[next(i for i, (name, _) in enumerate(bad) if name == 'CCX')]
    try:
        certify(bad)
    except AssertionError:
        pass
    else:
        raise AssertionError('missing product was accepted')
    text = '# GF(2^12) polynomial 0x1053; a=q0..11, b=q12..23, arbitrary XOR target=q24..35.\n'
    text += '# No workspace, measurements, classical bits or phase gates.\n'
    text += '\n'.join(name + ' ' + ' '.join('q' + str(q) for q in wires)
                      for name, wires in operations) + '\n'
    circuit = km.Circuit(text)
    assert circuit.num_qubits == 36 and circuit.num_bits == 0
    assert circuit.operation_statistics().num_toffoli_like == 45
    report = {'status': 'PASS', 'scope': 'local multiplier, not complete DQI',
              'archive_sha256': ARCHIVE_SHA, 'polynomial': '0x1053', 'tower_delta6': delta,
              'bilinear_basis_pairs_checked': 144, 'bilinear_terms': terms,
              'certificate': certificate, 'old_certificate': old_certificate,
              'negative_control_missing_CCX': 'REJECTED', 'kickmix_parse': 'PASS',
              'old_op_counts': dict(Counter(name for name, _ in old)),
              'new_op_counts': dict(Counter(name for name, _ in operations)),
              'uncontrolled_Toffoli_like': {'old': 63, 'new': 45},
              'controlled_Toffoli_like_model': {'old': 75, 'new': 57},
              'extra_qubits': 0, 'extra_classical_bits': 0,
              'full_DQI_verifier': 'NOT_RUN', 'kaggle_submission': 'NOT_RUN'}
    (args.out / 'mul45.kmx').write_text(text)
    (args.out / 'local-report.json').write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps({k: v for k, v in report.items() if k != 'bilinear_terms'}, indent=2))


if __name__ == '__main__':
    main()
