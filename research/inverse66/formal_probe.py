#!/usr/bin/env python3
"""Exact Boolean-ANF certificate for the existing 66-Toffoli inverse.

No random sampling: x[12], XOR target y[12], and every HMR outcome are
independent Boolean variables. The trusted checker is Python, not a Lean kernel.
"""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import types
import zipfile

POLY = 0x1053


def mul(a, b):
    out = 0
    while b:
        if b & 1:
            out ^= a
        a <<= 1
        if a & 4096:
            a ^= POLY
        b >>= 1
    return out


def power(x, n):
    out = 1
    while n:
        if n & 1:
            out = mul(out, x)
        x = mul(x, x)
        n >>= 1
    return out


def product(a, b):
    out = set()
    for x in a:
        for y in b:
            monomial = x | y  # Boolean quotient: x_i^2=x_i.
            if monomial in out:
                out.remove(monomial)
            else:
                out.add(monomial)
    return frozenset(out)


def inverse_anf():
    # Independent field reference; joint-output Boolean Moebius transform.
    coefficients = [power(x, 4094) for x in range(4096)]
    assert coefficients[0] == 0
    assert all(mul(x, coefficients[x]) == 1 for x in range(1,4096))
    for bit in range(12):
        for mask in range(4096):
            if mask & (1 << bit):
                coefficients[mask] ^= coefficients[mask ^ (1 << bit)]
    return [frozenset(mask for mask,c in enumerate(coefficients) if (c >> i) & 1)
            for i in range(12)]


def parse(text):
    out = []
    for line in text.splitlines():
        line = line.split('#',1)[0].strip()
        if not line:
            continue
        p = line.split()
        if p[0] not in {'CX','CCX','HMR','CZ','Z'}:
            raise ValueError('unsupported gate: '+line)
        if 'if' in p:
            split = p.index('if')
            out.append((p[0]+'_IF', [int(s[1:]) for s in p[1:split]], int(p[split+1][1:])))
        elif p[0] == 'HMR':
            out.append(('HMR',[int(p[1][1:])],int(p[2][1:])))
        else:
            out.append((p[0],[int(s[1:]) for s in p[1:]],None))
    return out


def certify(ops, ideal, repeats=1):
    initial = [frozenset([1 << i]) for i in range(24)] + [frozenset() for _ in range(21)]
    q = initial[:]
    bits = {}
    phase = frozenset()
    measurements = 0
    largest = 0
    for _ in range(repeats):
        for gate, v, b in ops:
            if gate == 'CX':
                q[v[1]] ^= q[v[0]]
            elif gate == 'CCX':
                q[v[2]] ^= product(q[v[0]], q[v[1]])
            elif gate == 'HMR':
                outcome = frozenset([1 << (24+measurements)])
                bits[b] = outcome
                phase ^= product(outcome, q[v[0]])
                q[v[0]] = frozenset()
                measurements += 1
            elif gate == 'CZ_IF':
                phase ^= product(bits[b], product(q[v[0]],q[v[1]]))
            elif gate == 'Z_IF':
                phase ^= product(bits[b], q[v[0]])
            else:
                raise ValueError(gate)
            largest = max(largest, len(phase), *(len(p) for p in q))
    expected = initial[:]
    if repeats % 2:
        for i in range(12):
            expected[12+i] ^= ideal[i]
    assert q == expected, 'wrong coherent XOR inverse or dirty scratch'
    assert not phase, 'uncancelled measurement-dependent phase'
    return {'status':'PASS','proof':'exact Boolean ANF',
            'input_variables':24,'independent_measurement_variables':measurements,
            'measurement_branches_represented':'2^'+str(measurements),
            'arbitrary_input_and_xor_target':True,'scratch_clean':True,
            'residual_phase_monomials':len(phase),'largest_polynomial_monomials':largest,
            'inverse_applications':repeats}


def retained_scaffold(generator_source, ideal, directory, parse_kickmix):
    # Reuse the archived generator's attributed bilinear decomposition, but keep
    # its intermediate stages until AFTER the caller's diagonal phase.
    module=types.ModuleType('archived_tower_inverse66')
    exec(compile(generator_source,'archived/tower_inverse66.py','exec'),module.__dict__)
    module.change_to_google_basis()
    forward=module.Emitter()
    for name,tg,prods,lins in module.STAGES:
        for s,t in lins:
            forward.emit('CX',s,t)
        for a,b,targets in prods:
            forward.prod(a,b,targets)
    erase=module.Emitter()
    for name,tg,prods,lins in reversed(module.STAGES):
        for j in reversed(tg):
            erase.erase_bit(j,prods,lins)
    texts=[]
    for name,emitter in [('forward',forward),('erase',erase)]:
        text='# Retained-scaffold GF(2^12) inverse, Google polynomial 0x1053.\n'
        text+='# q0..11 input, q12..23 initially-zero output, q24..44 workspace, b0 temporary.\n'
        text+='# Only the MATCHED forward + diagonal phase + erase returns all workspace/output to zero.\n'
        text+='\n'.join(s for s in module.kmx_str(emitter.ops).splitlines() if not s.startswith('#'))+'\n'
        (directory/f'inverse66-{name}.kmx').write_text(text)
        texts.append(text)
    first,last=map(parse,texts)
    q=[frozenset([1<<i]) for i in range(12)]+[frozenset() for _ in range(33)]
    initial=q[:];bits={};phase=frozenset();measurements=0

    def run(operations):
        nonlocal phase,measurements
        for gate,v,b in operations:
            if gate=='CX':
                q[v[1]]^=q[v[0]]
            elif gate=='CCX':
                q[v[2]]^=product(q[v[0]],q[v[1]])
            elif gate=='HMR':
                bits[b]=frozenset([1<<(24+measurements)])
                phase^=product(bits[b],q[v[0]])
                q[v[0]]=frozenset();measurements+=1
            elif gate=='CZ_IF':
                phase^=product(bits[b],product(q[v[0]],q[v[1]]))
            elif gate=='Z_IF':
                phase^=product(bits[b],q[v[0]])
            else:
                raise ValueError(gate)
    run(first)
    assert q[:12]==initial[:12] and q[12:24]==ideal and not phase
    assert all(not q[i] for i in [42,43,44])
    # Coherent, independent phase coefficients z_i. Universal polynomial
    # substitution later permits z_i = r*parity(mask & (omega*2^i)).
    expected=frozenset()
    for i in range(12):
        coefficient=frozenset([1<<(12+i)])
        phase^=product(coefficient,q[12+i])
        expected^=product(coefficient,ideal[i])
    run(last)
    assert q==initial,'retained-scaffold cleanup did not restore quantum registers'
    assert phase==expected,'retained-scaffold cleanup changed the caller phase'
    fc=Counter(g for g,_,_ in first);ec=Counter(g for g,_,_ in last)
    assert fc['CCX']==66 and ec['CCX']==0
    if parse_kickmix:
        import kickmix as km
        for text,want in zip(texts,[66,0]):
            assert km.Circuit(text).operation_statistics().num_toffoli_like==want
    return {'status':'PASS','proof':'exact Boolean ANF with independent coherent phase coefficients',
        'input_variables':12,'phase_coefficient_variables':12,
        'independent_measurement_variables':measurements,
        'measurement_branches_represented':'2^'+str(measurements),
        'forward_CCX':66,'erase_CCX':0,'forward_op_counts':dict(fc),'erase_op_counts':dict(ec),
        'phase_preserved':True,'output_and_workspace_clean':True,
        'output_precondition':'zero initially; caller phase diagonal and scaffold untouched',
        'local_qubits':45,'workspace_beyond_input_and_output':21,
        'DQI_integration':'NOT_IMPLEMENTED','DQI_Q_T_measurement':'NOT_RUN'}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--archive',default=str(Path(__file__).with_name('tower_inverse66_probe.zip')))
    p.add_argument('--out',default=str(Path(__file__).with_name('formal-report.json')))
    p.add_argument('--parse-kickmix',action='store_true')
    a = p.parse_args()
    archive = Path(a.archive)
    with zipfile.ZipFile(archive) as z:
        raw = z.read('inverse66_google.kmx')
        generator_source=z.read('tower_inverse66.py').decode()
    ops = parse(raw.decode())
    counts = Counter(g for g,_,_ in ops)
    assert counts['CCX'] == 66 and counts['HMR'] == 84
    ideal = inverse_anf()
    result = {'scope':'local inverse contract and composition, NOT an integrated DQI candidate',
              'archive_sha256':hashlib.sha256(archive.read_bytes()).hexdigest(),
              'kmx_sha256':hashlib.sha256(raw).hexdigest(),
              'polynomial':hex(POLY),'op_counts':dict(counts),
              'inverse_output_ANF_degrees':[max(m.bit_count() for m in p) for p in ideal],
              'single':certify(ops,ideal,1),'double':certify(ops,ideal,2),
              'trusted_boundary':'Python ANF checker, KMx gate/HMR semantics; not Lean-checked',
              'DQI_Q_T_measurement':'NOT_RUN','official_DQI_verifier':'NOT_RUN',
              'kickmix_parser':'NOT_RUN','kaggle_submissions':0}
    bad = ops[:]
    del bad[next(i for i,(g,_,_) in enumerate(bad) if g == 'CZ_IF')]
    try:
        certify(bad,ideal,1)
    except AssertionError as error:
        assert 'phase' in str(error)
        result['negative_control_missing_phase_correction']='REJECTED'
    else:
        raise AssertionError('checker accepted a missing measurement phase correction')
    result['retained_scaffold']=retained_scaffold(generator_source,ideal,Path(a.out).parent,a.parse_kickmix)
    if a.parse_kickmix:
        import kickmix as km
        circuit = km.Circuit(raw.decode())
        assert circuit.num_qubits == 45 and circuit.num_bits == 1
        assert circuit.operation_statistics().num_toffoli_like == 66
        result['kickmix_parser']='PASS'
    Path(a.out).write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps(result,indent=2))


if __name__=='__main__':
    main()
