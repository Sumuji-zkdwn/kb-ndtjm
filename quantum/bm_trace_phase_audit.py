#!/usr/bin/env python3
"""Require exact original KMB operands/opcodes outside the replaced Forney phase."""
import argparse,json,struct
from pathlib import Path
import numpy as np
from bm_scratch_audit import layout,arr
from dqi_gate import sha

REFERENCE_SHA='fd645ea4e7e5a2f6b7b2336ef510692f29a4fc6312910f82f975e1106c6d87c9'


def intervals(path):
    h,end,packets=layout(path);ops=arr(path,packets[1],'u1')
    with open(path,'rb') as f:
        f.seek(packets[11][0]);raw=f.read(packets[11][1])
    n=struct.unpack_from('<Q',raw)[0];ends=struct.unpack_from('<'+str(n)+'Q',raw,8)
    tags=[raw[8+8*n+a:8+8*n+b].decode() for a,b in zip((0,)+ends[:-1],ends)]
    offsets=np.flatnonzero(ops==6)
    start=int(offsets[tags.index('@enter:variable_mask_forney')])+1
    finish=int(offsets[tags.index('@exit:variable_mask_forney')])
    arity=(ops>>4)&3
    bounds={1:(start,finish)}
    for p,k in [(2,3),(3,3),(4,3),(5,2),(6,2),(7,1)]:
        bounds[p]=(int(np.count_nonzero(arity[:start]==k)),int(np.count_nonzero(arity[:finish]==k)))
    for p,flag in [(8,64),(9,128)]:bounds[p]=(int(np.count_nonzero(ops[:start]&flag)),int(np.count_nonzero(ops[:finish]&flag)))
    return h,end,packets,bounds


def audit(reference,candidate):
    assert sha(reference)==REFERENCE_SHA,'wrong verified BM reference'
    a,ae,ap,ab=intervals(reference);b,be,bp,bb=intervals(candidate)
    assert a[:32]==b[:32],'register/Q/bit contract changed'
    assert ae==be
    with open(reference,'rb') as x,open(candidate,'rb') as y:
        x.seek(104);y.seek(104);assert x.read(ae-104)==y.read(be-104),'named registers changed'
    assert set(ap)==set(bp)
    for p in ap:
        dtype='u1' if p in (1,11) else '<u4'
        x,y=arr(reference,ap[p],dtype),arr(candidate,bp[p],dtype)
        if p not in ab:
            assert np.array_equal(x,y),f'non-Forney packet {p} changed'
        else:
            alo,ahi=ab[p];blo,bhi=bb[p]
            assert alo==blo and len(x)-ahi==len(y)-bhi
            for lo,hi,other in [(0,alo,0),(ahi,len(x),bhi)]:
                for i in range(lo,hi,1<<20):
                    j=min(i+(1<<20),hi)
                    assert np.array_equal(x[i:j],y[other+i-lo:other+j-lo]),f'outside Forney packet {p} changed'
    old_t=struct.unpack_from('<Q',a,40)[0];new_t=struct.unpack_from('<Q',b,40)[0]
    assert old_t==756736 and new_t==732166
    assert ab[2][1]-ab[2][0]==364455 and bb[2][1]-bb[2][0]==339885
    return {'status':'PASS','reference_sha256':sha(reference),'candidate_sha256':sha(candidate),
        'qubits':struct.unpack_from('<I',b,20)[0],'old_static_Toffoli':old_t,'new_static_Toffoli':new_t,
        'saved_Toffoli':old_t-new_t,'all_BM_and_non_Forney_packets_byte_identical':True,
        'named_registers_E_masks_and_classical_private_bit_contract_unchanged':True,
        'proof_boundary':'Forney replacement checked separately by compositional exact ANF; whole-DQI public verification still required'}

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--reference',type=Path,required=True)
    p.add_argument('--candidate',type=Path,required=True);p.add_argument('--out',type=Path,required=True);a=p.parse_args()
    r=audit(a.reference,a.candidate);a.out.parent.mkdir(parents=True,exist_ok=True)
    a.out.write_text(json.dumps(r,indent=2)+'\n');print(json.dumps(r,indent=2))
