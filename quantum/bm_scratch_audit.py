#!/usr/bin/env python3
"""Check every KMB packet against the hash-pinned, verified BM circuit.

Only the three wire substitutions INSIDE variable_mask_forney and the
Q header may differ. This establishes a local circuit correspondence;
clean borrowing still relies on Em and Forney's cleanup contracts.
"""
import argparse
import json
from pathlib import Path
import struct
import numpy as np
from dqi_gate import sha

VERIFIED_SHA='107496dc7309eb15f227c80e7ed45b19dddb878b761ec5dc204db5ee812b7857'
WIRE_MAP={2482:860,2483:861,2484:862}

def layout(path):
    packets={}
    with open(path,'rb') as f:
        header=f.read(104)
        for _ in range(struct.unpack_from('<I',header,28)[0]):
            kind,size=struct.unpack('<QQ',f.read(16));assert kind==0
            f.seek(size,1)
        register_end=f.tell()
        while raw:=f.read(16):
            kind,size=struct.unpack('<QQ',raw)
            assert kind not in packets,'duplicate packet'
            packets[kind]=(f.tell(),size);f.seek(size,1)
    return header,register_end,packets

def arr(path,packet,dtype):
    offset,size=packet
    return np.memmap(path,mode='r',dtype=dtype,offset=offset,shape=(size//np.dtype(dtype).itemsize,))

def compare(reference,candidate,expected_map=WIRE_MAP):
    rh,re,rp=layout(reference);ch,ce,cp=layout(candidate)
    assert re==ce and rp==cp,'KMB layout changed'
    assert rh[:20]==ch[:20] and rh[24:]==ch[24:],'header changed beyond Q'
    assert struct.unpack_from('<I',rh,20)[0]-struct.unpack_from('<I',ch,20)[0]==len(expected_map),'Q saving mismatch'
    with open(reference,'rb') as r,open(candidate,'rb') as c:
        r.seek(104);c.seek(104)
        assert r.read(re-104)==c.read(ce-104),'named registers changed'
    ops=arr(reference,rp[1],'u1')
    tag_offsets=np.flatnonzero(ops==6)
    off,size=rp[11]
    with open(reference,'rb') as f:
        f.seek(off);raw=f.read(size)
    n=struct.unpack_from('<Q',raw)[0];ends=struct.unpack_from('<'+str(n)+'Q',raw,8)
    chars=raw[8+8*n:];starts=(0,)+ends[:-1]
    tags=[chars[a:b].decode() for a,b in zip(starts,ends)]
    assert len(tags)==len(tag_offsets),'tag count mismatch'
    start=int(tag_offsets[tags.index('@enter:variable_mask_forney')])+1
    end=int(tag_offsets[tags.index('@exit:variable_mask_forney')])
    arity=(ops>>4)&3
    changes={}
    for p in sorted(rp):
        x=arr(reference,rp[p],'u1' if p in (1,11) else '<u4')
        y=arr(candidate,cp[p],'u1' if p in (1,11) else '<u4')
        n={2:3,3:3,4:3,5:2,6:2,7:1}.get(p)
        lo=int(np.count_nonzero(arity[:start]==n)) if n else 0
        hi=lo+int(np.count_nonzero(arity[start:end]==n)) if n else 0
        changed=0
        for a in range(0,len(x),1<<20):
            b=min(a+(1<<20),len(x));expected=np.array(x[a:b])
            if n:
                left=max(a,lo)-a;right=min(b,hi)-a
                if left<right:
                    original=expected[left:right].copy()
                    assert not np.isin(original,list(expected_map.values())).any(),'borrowed pivots were already used inside Forney'
                    for old,new in expected_map.items():expected[left:right][original==old]=new
                outside=np.concatenate((x[a:min(b,lo)],x[max(a,hi):b]))
                assert not np.isin(outside,list(expected_map)).any(),'retired wire used outside Forney'
            assert np.array_equal(expected,y[a:b]),f'packet {p}: non-renaming circuit change'
            changed+=int(np.count_nonzero(x[a:b]!=y[a:b]))
        changes[p]=changed
    return {'status':'PASS','reference_sha256':sha(reference),'candidate_sha256':sha(candidate),
        'wire_map':expected_map,'changed_wire_operands_by_packet':changes,
        'all_opcodes_classical_targets_conditions_and_tags_identical':True,
        'all_other_wire_operands_identical':True,'forney_op_interval':[start,end],
        'scope':'exact complete packet correspondence plus separately audited clean-workspace contracts; not a formal BM proof'}

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--reference',type=Path,required=True);p.add_argument('--candidate',type=Path,required=True)
    p.add_argument('--out',type=Path,required=True);a=p.parse_args()
    assert sha(a.reference)==VERIFIED_SHA,'not the verified BM reference'
    result=compare(a.reference,a.candidate)
    a.out.parent.mkdir(parents=True,exist_ok=True);a.out.write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps(result,indent=2))
