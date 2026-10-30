#!/usr/bin/env python3
"""Published verifier on explicit rare/deep-stack inputs; no Kaggle submission."""
import argparse
import json
from pathlib import Path
import sys
import time

import numpy as np
from dqi_gate import sha

def run(candidate,data,out):
    sys.path.insert(0,str(Path(data)/'verifiers'))
    import kickmix as km
    from dqi import verify_submission_dqi as v
    field=km.GF2Field(12);tables=v.FieldTables(field)
    cases=[{}]
    for p in (0,1,2047,4094):
        for x in (1,2,2048,4095):cases.append({p:x})
    # Odd-order subgroups have zero syndromes until their order. In particular
    # a weight-35 subgroup exercises a 34-zero prefix and deep BM history.
    for weight in (3,5,7,9,13,15,21,35):
        assert 4095%weight==0
        for shift in (0,17):
            for x in (1,2048):
                cases.append({(shift+i*(4095//weight))%4095:x for i in range(weight)})
    for a,b in ((0,1),(4,4094),(27,2091)):
        for u in (1,2048):cases.append({a:u,b:field.mul(u,field.pow(field.primitive_element,(a-b)%4095))})
    shots=1536;rng=np.random.default_rng(20261026)
    syndromes=np.zeros((shots,70),dtype=np.int64)
    masks=rng.integers(0,4096,size=(shots,4095),dtype=np.int64)
    phases=np.zeros(shots,dtype=bool)
    rows=np.arange(1,71,dtype=np.int64)[:,None]
    for i in range(shots):
        errors=cases[i%len(cases)]
        if errors:
            positions=np.array(list(errors),dtype=np.int64)
            values=np.array(list(errors.values()),dtype=np.int64)
            exps=(rows*positions[None,:]+tables.log[values][None,:])%4095
            syndromes[i]=np.bitwise_xor.reduce(tables.antilog[exps],axis=1)
        kind=(i//len(cases))%4
        if kind==0:masks[i,:]=0
        elif kind==1:masks[i,:]=4095
        elif kind==2:masks[i,:]=1<<((i//(4*len(cases)))%12)
        phases[i]=sum((int(masks[i,p])&x).bit_count() for p,x in errors.items())%2
    deep_index=next(i for i,c in enumerate(cases) if len(c)==35)
    assert not syndromes[deep_index,:34].any() and syndromes[deep_index,34]!=0
    circuit=km.Circuit.from_file(candidate,format='kmb')
    start=time.monotonic()
    result=v.verify(circuit,v.ProblemSpecDQI.benchmark_instance(num_shots=shots),
        salt='bm-deep-stack-explicit-cases',seed=20261026,max_workers=1,
        shots=(syndromes,masks,phases))
    assert result['value_errors']==result['phase_errors']==0, result
    report={'status':'PASS','scope':'targeted regression, not distributional confidence evidence',
        'candidate_sha256':sha(candidate),'verifier_sha256':sha(Path(data)/'verifiers/dqi/verify_submission_dqi.py'),
        'distinct_error_patterns':len(cases),'num_shots':shots,'mask_modes':['zero','all bits','single bit','random'],
        'includes_weight35_subgroup_with_34_zero_syndromes':True,
        'value_errors':int(result['value_errors']),'phase_errors':int(result['phase_errors']),
        'seed':20261026,'elapsed_seconds':time.monotonic()-start,
        'error_patterns':[{str(k):v for k,v in c.items()} for c in cases],
        'submits_to_kaggle':False}
    out=Path(out);out.parent.mkdir(parents=True,exist_ok=True)
    out.write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps({k:v for k,v in report.items() if k!='error_patterns'},indent=2))

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--candidate',required=True);p.add_argument('--data-root',required=True)
    p.add_argument('--out',required=True);a=p.parse_args();run(a.candidate,a.data_root,a.out)
