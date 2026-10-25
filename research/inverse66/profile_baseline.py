#!/usr/bin/env python3
"""Count static Toffoli-like operations under the baseline's nested INFO_TAGs."""
import argparse
from collections import Counter, defaultdict
import json
from pathlib import Path
import struct
import sys

import numpy as np

sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'quantum'))
from dqi_gate import sha
from wfs_dqi_single_site import BASE_DQI_SHA, KMB


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('baseline_dqi')
    p.add_argument('--out',default=str(Path(__file__).with_name('resource-profile.json')))
    a=p.parse_args()
    checksum=sha(a.baseline_dqi)
    assert checksum==BASE_DQI_SHA
    k=KMB(a.baseline_dqi)
    positions=np.flatnonzero(k.ops==6)
    ranks=np.searchsorted(np.flatnonzero(((k.ops>>4)&3)==3),positions)
    payload,length=k.packets[11]
    count=struct.unpack_from('<Q',k.data,payload)[0]
    assert count==len(positions)
    ends=np.frombuffer(k.data,dtype='<u8',count=count,offset=payload+8)
    text_start=payload+8+8*count
    stack=[];last=0;previous_end=0
    inclusive=Counter();exclusive=Counter();hist=defaultdict(Counter);top=[]
    for i,end in enumerate(ends):
        end=int(end)
        tag=k.data[text_start+previous_end:text_start+end].decode();previous_end=end
        now=int(ranks[i])
        exclusive[stack[-1][0] if stack else '(outside)']+=now-last;last=now
        if tag.startswith('@enter:'):
            stack.append((tag[7:],now,int(positions[i])))
        elif tag.startswith('@exit:'):
            name,start,pos=stack.pop();assert name==tag[6:]
            value=now-start
            inclusive[name]+=value;hist[name][value]+=1
            if not stack:
                top.append({'stage':name,'start_zero_based':pos,'stop_exclusive':int(positions[i])+1,
                            'static_toffoli_like':value})
    assert not stack and sum(exclusive.values())==k.header[5]==5725461
    assert hist['gf_inverse_chain']=={315:4983}
    assert hist['gf_uninverse_chain']=={0:4983}
    assert hist['forney_step']=={351:4095}
    result={'baseline_dqi_sha256':checksum,'quantum_bits':k.header[1],
            'static_toffoli_like':k.header[5],'top_level_stages':top,
            'exclusive_toffoli_by_innermost_tag':dict(exclusive.most_common()),
            'per_call_static_toffoli_histograms':{n:dict(hist[n]) for n in
                ['gf_inverse_chain','gf_uninverse_chain','forney_step']},
            'interpretation':'static counts; actual score uses measured mean conditional counts',
            'conservative_Forney_model':{
                'old_inverse_compute':315,'old_inverse_erase':0,
                'new_inverse_compute':66,'new_inverse_erase':66,
                'saved_per_active_position':183,'positions':4095,
                'static_saved_if_embedded':749385,'static_new_T_if_embedded':4976076,
                'assumptions':'each Forney inverse pair replaced; all other operations unchanged',
                'integration_status':'NOT_IMPLEMENTED','Q_prime':'UNKNOWN'}}
    result['retained_scaffold_model']={'old_compute':315,'old_erase':0,
        'new_compute':66,'new_erase':0,'positions':4095,
        'static_saved_if_embedded':1019655,'static_new_T_if_embedded':4705806,
        'integration_status':'NOT_IMPLEMENTED','Q_prime':'UNKNOWN','measured_mean_T':'NOT_RUN'}
    Path(a.out).write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps({n:result[n] for n in ['static_toffoli_like','per_call_static_toffoli_histograms','conservative_Forney_model']},indent=2))


if __name__=='__main__':
    main()
