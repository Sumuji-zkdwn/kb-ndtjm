#!/usr/bin/env python3
"""Compositional exact ANF proof of the 72-Toffoli trace phase (not full DQI)."""
import argparse
from collections import Counter
import json
from pathlib import Path
from trace_phase import TracePhase,lin
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'inverse66'))
from formal_probe import product


def execute(ops,initial,mask_start,measurement_start,phase=frozenset()):
    q=initial[:];bits={};measurements=0;largest=0
    for g,v,c in ops:
        if g=='CX':
            term=q[v[0]]
            if c is not None:term=product(term,frozenset([1<<(mask_start+c)]))
            q[v[1]]^=term
        elif g=='SWAP':q[v[0]],q[v[1]]=q[v[1]],q[v[0]]
        elif g=='CCX':q[v[2]]^=product(q[v[0]],q[v[1]])
        elif g=='CCZ':phase^=product(q[v[0]],product(q[v[1]],q[v[2]]))
        elif g=='HMR':
            outcome=frozenset([1<<(measurement_start+measurements)])
            measurements+=1;bits[c]=outcome
            phase^=product(outcome,q[v[0]]);q[v[0]]=frozenset()
        elif g in ('Z','CZ'):
            term=q[v[0]]
            if g=='CZ':term=product(term,q[v[1]])
            assert c is not None
            phase^=product(bits[c],term)
        else:raise ValueError(g)
        largest=max(largest,len(phase),*(len(x) for x in q))
    return q,phase,measurements,largest


def prefix_certificate(p):
    initial=[frozenset() for _ in range(70)]
    for i in range(12):initial[i]=frozenset([1<<i])
    q,phase,n,largest=execute(p.forward,initial,0,18)
    assert not phase and q[:12]==initial[:12]
    coefficients=[]
    for x in range(4096):
        norm=p.f.mul(x,p.f.pow(x,64));inv=p.f.inv(norm)
        assert p.f.mul(p.f.pow(x,64),inv)==p.f.inv(x)
        assert lin(p.m.LIN['A1ROWS'],inv)==0
        coefficients.append(lin(p.m.LIN['A0ROWS'],inv))
    for bit in range(12):
        for mask in range(4096):
            if mask>>bit&1:coefficients[mask]^=coefficients[mask^(1<<bit)]
    ideal=[frozenset(mask for mask,c in enumerate(coefficients) if c>>j&1) for j in range(6)]
    assert q[36:42]==ideal,'wrong norm inverse'
    # Independent coherent phase coefficients; substitute the middle block's
    # D/N/mask/root-dependent coefficients after this identity is proved.
    expected=frozenset()
    for j in range(6):expected^=product(ideal[j],frozenset([1<<(12+j)]))
    q,phase,n2,large2=execute(p.erase,q,0,18+n,expected)
    assert q==initial,'dirty norm workspace'
    assert phase==expected,'norm cleanup changed caller phase'
    return {'status':'PASS','method':'exact Boolean ANF and 4096-value independent field reference',
        'field_inputs':4096,'input_variables':12,'independent_coherent_phase_coefficients':6,
        'independent_measurement_variables':n+n2,'forward_CCX':36,'erase_CCX':0,
        'largest_polynomial_monomials':max(largest,large2),'inverse_zero_convention':'inv(0)=0',
        'workspace_clean':True,'phase_preserved':True}


def middle_certificate(p,ops=None):
    initial=[frozenset() for _ in range(70)]
    for i in range(12):
        initial[i]=frozenset([1<<i]);initial[58+i]=frozenset([1<<(12+i)])
    for i in range(6):initial[36+i]=frozenset([1<<(24+i)])
    initial[57]=frozenset([1<<30])
    # 43 independent variables: D12, N12, Y6, root1, classical mask12.
    q,phase,n,largest=execute(p.middle() if ops is None else ops,initial,31,43)
    expected=set();tensor_checks=0
    for k in range(12):
        for i in range(12):
            for j in range(12):
                v=p.f.mul(1<<j,p.f.pow(1<<i,64))
                for t in range(6):
                    tensor_checks+=1
                    if p.f.mul(v,p.embed(1<<t))>>k&1:
                        mon=(1<<i)|(1<<(12+j))|(1<<(24+t))|(1<<30)|(1<<(31+k))
                        if mon in expected:expected.remove(mon)
                        else:expected.add(mon)
    assert q==initial,'middle changed input or left dirty scratch'
    assert phase==frozenset(expected),'wrong phase or uncorrected measurement phase'
    return {'status':'PASS','method':'exact Boolean ANF including classical masks and every HMR outcome',
        'independent_variables':43,'independent_measurement_variables':n,'tensor_basis_cases':tensor_checks,
        'phase_monomials':len(expected),'largest_polynomial_monomials':largest,
        'all_masks_and_root_branches':True,'all_quantum_inputs_restored':True,'scratch_clean':True,
        'CCX':30,'CCZ':6}


def kmx(ops):
    lines=['# Exact GF(4096) inverse phase via relative trace; no full DQI submission.',
        '# D=q0..11, readonly N=q58..69, root=q57, masks=b0..11; b12 private measurement.',
        '# All remaining quantum wires initially zero and returned to zero.']
    for g,qs,c in ops:
        if g=='HMR':lines.append(f'HMR q{qs[0]} b12')
        else:
            suffix='' if c is None else f' if b{12 if g in ("Z","CZ") else c}'
            lines.append(g+' '+' '.join('q'+str(q) for q in qs)+suffix)
    lines.append('BIT_STORE0 b12')
    return '\n'.join(lines)+'\n'


def verify(p):
    prefix=prefix_certificate(p);middle=middle_certificate(p)
    for label,index in [('phase',next(i for i,(g,q,c) in enumerate(p.middle()) if g=='CCZ')),
                        ('measurement_correction',next(i for i,(g,q,c) in enumerate(p.middle()) if g=='CZ' and c is not None))]:
        ops=p.middle();del ops[index]
        try:middle_certificate(p,ops)
        except AssertionError:pass
        else:raise AssertionError('accepted missing '+label)
    ops=p.operations();counts=Counter(g for g,_,_ in ops)
    assert counts['CCX']==66 and counts['CCZ']==6
    return {'status':'PASS','scope':'local Forney inverse phase; NOT a verified complete DQI',
        'prefix':prefix,'middle':middle,'negative_missing_phase_and_correction':'REJECTED',
        'composition':'prefix produces inv(Norm(D)); middle phase is root*parity(mask & N*conjugate(D)*embed(Y)); prefix erase preserves any coherent linear phase on Y',
        'old_inverse_plus_phase_Toffoli':78,'new_inverse_plus_phase_Toffoli':72,
        'root_tree_Toffoli_unchanged':11,'old_Forney_per_point':89,'new_Forney_per_point':83,
        'evaluation_points':4095,'expected_total_Toffoli_saving':24570,
        'expected_full_DQI_Toffoli':732166,'expected_full_DQI_Q':2482,
        'op_counts':dict(counts),'full_DQI_verifier':'NOT_RUN','kaggle_submission':'NOT_RUN',
        'trusted_boundary':'Python Boolean-polynomial checker and composition argument, not Lean checked',
        'attribution':'Unchanged andigu/uncompute tower basis and KT6 tables via existing Apache-2.0 inverse66 archive'}


if __name__=='__main__':
    a=argparse.ArgumentParser(description=__doc__);a.add_argument('--out',type=Path,required=True);args=a.parse_args()
    args.out.mkdir(parents=True,exist_ok=True);p=TracePhase();r=verify(p)
    text=kmx(p.operations());(args.out/'trace-phase.kmx').write_text(text)
    import kickmix as km
    c=km.Circuit(text);assert c.operation_statistics().num_toffoli_like==72
    r['native_parse']='PASS';r['local_qubits']=c.num_qubits;r['local_bits']=c.num_bits
    (args.out/'report.json').write_text(json.dumps(r,indent=2)+'\n');print(json.dumps(r,indent=2))
