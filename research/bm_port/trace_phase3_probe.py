#!/usr/bin/env python3
"""Exact ANF certificate for the nested 69-Toffoli Forney inverse phase."""
import argparse,json
from collections import Counter
from pathlib import Path
from trace_phase import lin
from trace_phase3 import TracePhase3
from trace_phase_probe import execute,kmx,product


def prefix_certificate(p):
    initial=[frozenset() for _ in range(70)]
    for i in range(12):initial[i]=frozenset([1<<i])
    q,phase,n,largest=execute(p.forward,initial,0,30)
    assert not phase and q[:12]==initial[:12]
    values=[]
    for x in range(4096):
        norm=p.f.mul(x,p.f.pow(x,64))
        norm3=p.f.mul(norm,p.f.pow(norm,8))
        cube=p.f.pow(norm3,3)
        assert p.f.pow(cube,2)==p.f.inv(norm3)
        assert p.f.mul(p.f.pow(norm,8),p.f.inv(norm3))==p.f.inv(norm)
        assert p.f.mul(p.f.pow(x,64),p.f.inv(norm))==p.f.inv(x)
        assert lin(p.m.LIN['A1ROWS'],norm)==0
        norm_coords=lin(p.m.LIN['A0ROWS'],norm)
        cube_coords=lin(p.m.LIN['A0ROWS'],cube)
        assert cube_coords<8
        values.append(norm_coords|(cube_coords<<6))
    for bit in range(12):
        for mask in range(4096):
            if mask>>bit&1:values[mask]^=values[mask^(1<<bit)]
    ideal=[frozenset(mask for mask,c in enumerate(values) if c>>j&1) for j in range(9)]
    assert q[24:30]+q[33:36]==ideal,'wrong norm or cube'
    # The middle is bilinear in Norm6 and cube3. Independent coherent
    # coefficients cover every such monomial before substituting D/N/mask/root.
    expected=frozenset()
    for i in range(6):
        for j in range(3):expected^=product(product(ideal[i],ideal[6+j]),frozenset([1<<(12+3*i+j)]))
    q,phase,n2,large2=execute(p.erase,q,0,30+n,expected)
    assert q==initial,'dirty prefix workspace'
    assert phase==expected,'prefix cleanup changed caller phase'
    return {'status':'PASS','method':'exact ANF and 4096-value independent finite-field reference',
        'field_inputs':4096,'input_variables':12,'independent_coherent_phase_coefficients':18,
        'phase_form':'arbitrary coherent coefficients on all Norm6_i*cube3_j monomials',
        'independent_measurement_variables':n+n2,'forward_CCX':24,'erase_CCX':0,
        'largest_polynomial_monomials':max(largest,large2),'inverse_zero_convention':'inv(0)=0',
        'all_norm_and_cube_outputs_checked':True,'workspace_clean':True,'phase_preserved':True}


def middle_certificate(p,ops=None):
    initial=[frozenset() for _ in range(70)]
    for i in range(12):
        initial[i]=frozenset([1<<i]);initial[58+i]=frozenset([1<<(12+i)])
    for i in range(6):initial[24+i]=frozenset([1<<(24+i)])
    for i in range(3):initial[33+i]=frozenset([1<<(30+i)])
    initial[57]=frozenset([1<<33])
    # D12, N12, independent Norm6, cube3, root1, classical mask12.
    q,phase,n,largest=execute(p.middle() if ops is None else ops,initial,34,46)
    expected=set();tensor_checks=0
    for i in range(12):
        for j in range(12):
            v=p.f.mul(1<<j,p.f.pow(1<<i,64))
            for a in range(6):
                vn=p.f.mul(v,p.f.pow(p.embed(1<<a),8))
                for t in range(3):
                    w=p.f.mul(vn,p.embed3(lin(p.m.LIN['SQ3R'],1<<t)))
                    for k in range(12):
                        tensor_checks+=1
                        if w>>k&1:
                            mon=(1<<i)|(1<<(12+j))|(1<<(24+a))|(1<<(30+t))|(1<<33)|(1<<(34+k))
                            if mon in expected:expected.remove(mon)
                            else:expected.add(mon)
    assert q==initial,'middle changed input or left dirty scratch'
    assert phase==frozenset(expected),'wrong nested phase or uncorrected measurement phase'
    return {'status':'PASS','method':'exact ANF including all masks and every HMR outcome',
        'independent_variables':46,'independent_measurement_variables':n,'tensor_basis_cases':tensor_checks,
        'phase_monomials':len(expected),'largest_polynomial_monomials':largest,
        'all_masks_and_root_branches':True,'all_quantum_inputs_restored':True,'scratch_clean':True,
        'CCX':42,'CCZ':3}


def verify(p):
    prefix=prefix_certificate(p);middle=middle_certificate(p)
    nested_erase_start=sum(12 if step is None else len(step) for step in p.middle_steps()[:8])
    nested_correction=nested_erase_start+next(i for i,(g,q,c) in enumerate(p.nested_erase) if g=='CZ')
    for label,index in [('phase',next(i for i,(g,q,c) in enumerate(p.middle()) if g=='CCZ')),
                        ('measurement_correction',next(i for i,(g,q,c) in enumerate(p.middle()) if g=='CZ' and c is not None)),
                        ('nested_measurement_correction',nested_correction)]:
        ops=p.middle();del ops[index]
        try:middle_certificate(p,ops)
        except AssertionError:pass
        else:raise AssertionError('accepted missing '+label)
    counts=Counter(g for g,_,_ in p.operations())
    assert counts['CCX']==66 and counts['CCZ']==3
    return {'status':'PASS','scope':'local nested Forney inverse phase; NOT a verified complete DQI',
        'prefix':prefix,'middle':middle,'negative_missing_phase_and_corrections':'REJECTED',
        'composition':'prefix computes Norm(D) and Norm_64/8(Norm(D))^3; middle phase is root*parity(mask & N*D^64*Norm(D)^8*embed3(square(cube))); exact prefix erasure preserves that phase',
        'old_inverse_plus_phase_Toffoli':72,'new_inverse_plus_phase_Toffoli':69,
        'root_tree_Toffoli_unchanged':11,'old_Forney_per_point':83,'new_Forney_per_point':80,
        'evaluation_points':4095,'expected_total_Toffoli_saving':12285,
        'expected_full_DQI_Toffoli':719881,'expected_full_DQI_Q':2482,
        'op_counts':dict(counts),'full_DQI_verifier':'NOT_RUN','kaggle_submission':'NOT_RUN',
        'trusted_boundary':'Python Boolean-polynomial checker and composition argument, not Lean checked',
        'attribution':'Unchanged andigu/uncompute inverse66 archive tower basis, KT6 and KT3 (Apache-2.0)'}


if __name__=='__main__':
    a=argparse.ArgumentParser(description=__doc__);a.add_argument('--out',type=Path,required=True);args=a.parse_args()
    args.out.mkdir(parents=True,exist_ok=True);p=TracePhase3();r=verify(p)
    text=kmx(p.operations());(args.out/'trace-phase3.kmx').write_text(text)
    import kickmix as km
    c=km.Circuit(text);assert c.operation_statistics().num_toffoli_like==69
    r['native_parse']='PASS';r['local_qubits']=c.num_qubits;r['local_bits']=c.num_bits
    (args.out/'report.json').write_text(json.dumps(r,indent=2)+'\n');print(json.dumps(r,indent=2))
