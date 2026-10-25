#!/usr/bin/env python3
"""Exact local probe for coherent controlled quotient accumulation.

No full DQI rewrite or Kaggle submission. Requires the repository's retained
inverse66 components and the pinned Kickmix used by the existing CI.
"""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import struct
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'research/inverse66'))
from formal_probe import inverse_anf, mul, product


def parse(text):
    operations = []
    for line in text.splitlines():
        tokens = line.split('#', 1)[0].split()
        if not tokens or tokens[0] in {'REGISTER', 'APPEND_TO_REGISTER', 'INFO_TAG'}:
            continue
        condition = None
        if 'if' in tokens:
            split = tokens.index('if')
            condition = int(tokens[split + 1][1:])
            tokens = tokens[:split]
        operations.append((tokens[0], [int(x[1:]) for x in tokens[1:]], condition))
    return operations


def verify(operations, ideal, *, layout=None):
    # den[12], num[12], arbitrary XOR target[12], coherent control[1].
    if layout is None:
        layout = {'qubits': 82, 'den': list(range(12)), 'num': list(range(45, 57)),
                  'target': list(range(69, 81)), 'control': 81}
    q = [frozenset() for _ in range(layout['qubits'])]
    for variable, wire in enumerate(layout['den'] + layout['num'] + layout['target'] + [layout['control']]):
        q[wire] = frozenset({1 << variable})
    initial = q[:]
    expected = q[:]
    for i in range(12):
        for j in range(12):
            coefficient = mul(1 << i, 1 << j)
            term = product(initial[layout['control']], product(initial[layout['num'][i]], ideal[j]))
            for bit in range(12):
                if (coefficient >> bit) & 1:
                    expected[layout['target'][bit]] ^= term

    bits = {}
    phase = frozenset()
    measurements = 0
    for gate, wires, condition in operations:
        if gate == 'CX' and condition is None:
            q[wires[1]] ^= q[wires[0]]
        elif gate == 'CCX' and condition is None:
            q[wires[2]] ^= product(q[wires[0]], q[wires[1]])
        elif gate == 'SWAP' and condition is None:
            a, b = wires
            q[a], q[b] = q[b], q[a]
        elif gate == 'R' and condition is None:
            # Reject any attempt to discard nonzero quantum information.
            assert not q[wires[0]], 'reset of nonzero symbolic qubit'
        elif gate == 'HMR' and condition is None:
            a, b = wires
            outcome = frozenset({1 << (37 + measurements)})
            measurements += 1
            bits[b] = outcome
            phase ^= product(outcome, q[a])
            q[a] = frozenset()
        elif gate == 'BIT_STORE0' and condition is None:
            bits[wires[0]] = frozenset()
        elif gate == 'BIT_INVERT':
            bits[wires[0]] ^= bits[condition] if condition is not None else frozenset({0})
        elif gate in {'Z', 'CZ'}:
            term = q[wires[0]]
            if gate == 'CZ':
                term = product(term, q[wires[1]])
            if condition is not None:
                term = product(term, bits[condition])
            phase ^= term
        else:
            raise ValueError((gate, wires, condition))
    assert q == expected, 'wrong controlled quotient or dirty quantum workspace'
    assert not phase, 'uncancelled measurement-dependent phase'
    assert all(not value for value in bits.values()), 'uncleared temporary classical bits'
    return {
        'status': 'PASS',
        'method': 'exact Boolean ANF, not trajectory sampling',
        'independent_input_variables': 37,
        'independent_measurement_variables': measurements,
        'measurement_branches_represented': f'2^{measurements}',
        'coherent_control': True,
        'arbitrary_xor_target': True,
        'zero_divisor_convention': 'inv(0) = 0',
        'quantum_workspace_clean': True,
        'temporary_classical_bits_clean': True,
        'residual_phase_monomials': len(phase),
    }


def audit_quotient_regions(path):
    """Count actual quotient_div regions, without asserting operand compatibility."""
    import numpy as np
    sys.path.insert(0, str(ROOT / 'quantum'))
    from dqi_gate import sha
    from wfs_dqi_single_site import BASE_DQI_SHA, KMB
    assert sha(path) == BASE_DQI_SHA
    circuit = KMB(path)
    payload, _ = circuit.packets[11]
    count = struct.unpack_from('<Q', circuit.data, payload)[0]
    ends = np.frombuffer(circuit.data, dtype='<u8', count=count, offset=payload + 8)
    text_start = payload + 8 + 8 * count
    positions = np.flatnonzero(circuit.ops == 6)
    ranks = np.searchsorted(np.flatnonzero(((circuit.ops >> 4) & 3) == 3), positions)
    stack, stages, histogram, first = [], Counter(), Counter(), {}
    previous = 0
    for i, end in enumerate(ends):
        end = int(end)
        tag = circuit.data[text_start + previous:text_start + end].decode()
        previous = end
        if tag.startswith('@enter:'):
            stack.append((tag[7:], int(positions[i]), int(ranks[i])))
        elif tag.startswith('@exit:'):
            name, start, cost_start = stack.pop()
            assert name == tag[6:]
            if name == 'quotient_div':
                stage = stack[0][0]
                stages[stage] += 1
                histogram[int(ranks[i]) - cost_start] += 1
                first.setdefault(stage, {'start_zero_based': start,
                                         'stop_exclusive': int(positions[i]) + 1})
    assert not stack
    assert stages == {'forward_eea': 444, 'reverse_eea': 444}
    assert histogram == {390: 888}
    return {'baseline_dqi_sha256': BASE_DQI_SHA,
            'by_stage': dict(stages), 'static_toffoli_histogram': dict(histogram),
            'first_intervals': first, 'actual_operand_mapping': 'NOT_RUN'}


def main():
    import kickmix as km
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, default=Path(__file__).parent)
    parser.add_argument('--baseline', type=Path, help='Optional pinned baseline dqi.kmb tag/count audit')
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    field = km.GF2Field(12)
    assert field.modulus == 0x1053

    # Keep the existing pinned multiplication and measurement cleanup.
    builder = km.CircuitBuilder()
    q = builder.create_quantum_register(82, name='local_wires')
    builder.init_gf2_mul(q[45:57], q[12:24], target=q[57:69], field=field)
    builder.gf2_iadd(q[57:69], target=q[69:81], field=field, control=q[81])
    builder.del_gf2_mul(q[45:57], q[12:24], target=q[57:69], field=field)
    middle = builder.finish_circuit()
    middle_text = '\n'.join(line for line in str(middle).splitlines()
                            if not line.startswith(('REGISTER ', 'APPEND_TO_REGISTER ')))
    # Generated KMx files are not required to exist in a fresh checkout.
    # Rebuild them from the tracked, attributed source archive and certify them.
    components = args.out / 'inverse-components'
    components.mkdir(parents=True, exist_ok=True)
    subprocess.run([sys.executable, str(ROOT/'research/inverse66/formal_probe.py'),
                    '--out', str(components/'formal-report.json')],
                   check=True, stdout=subprocess.DEVNULL)
    inverse_report = json.loads((components/'formal-report.json').read_text())
    assert inverse_report['retained_scaffold']['status'] == 'PASS'
    forward = (components / 'inverse66-forward.kmx').read_text()
    erase = (components / 'inverse66-erase.kmx').read_text()
    clear_bits = '\n'.join(f'BIT_STORE0 b{i}' for i in range(middle.num_bits))
    text = (
        '# LOCAL PROBE, not a complete DQI submission.\n'
        '# q0..11 denominator; q45..56 numerator; q69..80 arbitrary XOR target; q81 coherent control.\n'
        '# All other quantum wires start and end at zero. inv(0)=0.\n'
        + clear_bits + '\n' + forward + '\n' + middle_text + '\n' + erase + '\n' + clear_bits + '\n'
    )
    candidate = km.Circuit(text)
    assert candidate.num_qubits == 82
    assert candidate.operation_statistics().num_toffoli_like == 141
    ideal = inverse_anf()
    operations = parse(text)
    certificate = verify(operations, ideal)

    # A missing HMR fixup must be detected, including in the arithmetic caller.
    bad = operations[:]
    del bad[next(i for i, (g, _, c) in enumerate(bad) if g == 'CZ' and c is not None)]
    try:
        verify(bad, ideal)
    except AssertionError as error:
        assert 'phase' in str(error)
    else:
        raise AssertionError('missing phase fixup was accepted')

    # Compare the same local contract built by the existing division routine.
    builder = km.CircuitBuilder()
    a = builder.create_quantum_register(12, name='numerator')
    b = builder.create_quantum_register(12, name='denominator')
    target = builder.create_quantum_register(12, name='target')
    control = builder.create_quantum_register(1, name='control')[0]
    ratio, scaffold = builder.init_gf2_div_with_scaffold(a, b, field=field)
    builder.gf2_iadd(ratio, target=target, field=field, control=control)
    builder.del_gf2_div_with_scaffold(a, b, target=ratio, scaffold=scaffold, field=field)
    builder.free(scaffold + ratio)
    baseline = builder.finish_circuit()
    old_t = int(baseline.operation_statistics().num_toffoli_like)
    assert old_t == 390
    baseline_clear = '\n'.join(f'BIT_STORE0 b{i}' for i in range(baseline.num_bits))
    old_layout = {'qubits': baseline.num_qubits, 'den': list(range(12, 24)),
                  'num': list(range(12)), 'target': list(range(24, 36)), 'control': 36}
    old_operations = parse(str(baseline))
    baseline_certificate = verify(parse(baseline_clear) + old_operations + parse(baseline_clear),
                                  ideal, layout=old_layout)
    # A reused parity accumulator is explicitly cleared on its first access;
    # a freshly allocated one starts zero and omits that redundant instruction.
    first_parity_use = next(i for i, (gate, operands, condition) in enumerate(old_operations)
                            if (gate.startswith('BIT_') and operands[0] == 12) or condition == 12)
    assert old_operations[first_parity_use][0] == 'BIT_INVERT'
    reused = old_operations[:first_parity_use] + [('BIT_STORE0', [12], None)] + old_operations[first_parity_use:]
    reused_certificate = verify(parse(baseline_clear) + reused + parse(baseline_clear), ideal, layout=old_layout)
    (args.out / 'quotient-local.kmx').write_text(text)
    report = {
        'scope': 'local coherent quotient contract; NOT a full DQI candidate',
        'contract': '|a,b,t,c,0> -> |a,b,t XOR c*(a*inv(b)),c,0>',
        'polynomial': '0x1053',
        'certificate': certificate,
        'baseline_certificate': baseline_certificate,
        'baseline_reused_parity_certificate': reused_certificate,
        'negative_control_missing_fixup': 'REJECTED',
        'kickmix_parse': 'PASS',
        'baseline_local_qubits': baseline.num_qubits,
        'candidate_local_qubits': candidate.num_qubits,
        'baseline_static_toffoli': old_t,
        'candidate_static_toffoli': 141,
        'static_saved_per_call': old_t - 141,
        'candidate_op_counts': dict(Counter(g for g, _, _ in operations)),
        'local_kmx_sha256': hashlib.sha256(text.encode()).hexdigest(),
        'probe_source_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        'inverse_component_sha256': {
            name: hashlib.sha256((components / f'inverse66-{name}.kmx').read_bytes()).hexdigest()
            for name in ('forward', 'erase')
        },
        'kickmix_reference_source_commit': '638777fac4379bc62e2a1e4a52cf1a1753895d48',
        'trusted_boundary': 'Python ANF checker, finite-field reference, gate/HMR semantics; not Lean checked',
        'full_DQI_integration': 'NOT_RUN',
        'official_verifier': 'NOT_RUN',
        'kaggle_submission': 'NOT_RUN',
    }
    if args.baseline:
        report['actual_quotient_regions'] = audit_quotient_regions(args.baseline)
    (args.out / 'quotient-local-report.json').write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
