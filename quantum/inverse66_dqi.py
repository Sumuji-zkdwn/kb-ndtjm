#!/usr/bin/env python3
"""Replace Forney inverse/cleanup pairs in the COMPLETE pinned v1.0 DQI.

Reuse 21 of each original 48-qubit scaffold. Add one private classical bit.
All non-replaced instructions, named registers and outer conditions are preserved.
Only nested metadata inside replaced inverse blocks is removed. Never submits.
"""
import argparse
import json
from pathlib import Path
import shutil
import struct
import subprocess
import sys
import zipfile

import numpy as np

from dqi_gate import BASE_SHA, sha
from wfs_dqi_single_site import BASE_DQI_SHA, KMB, selected, stream_copy, targets

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'research/inverse66'))
from formal_probe import parse as parse_kmx

OP={'CX':0x21,'CCX':0x31,'HMR':0x50,'CZ_IF':0xa0,'Z_IF':0x90}


def find_sites(k):
    p,n=k.packets[11]
    count=struct.unpack_from('<Q',k.data,p)[0]
    ends=np.frombuffer(k.data,dtype='<u8',count=count,offset=p+8)
    text=p+8+8*count
    positions=np.flatnonzero(k.ops==6)
    assert len(positions)==count
    previous=0;stack=[];sites=[];active=None
    for i,end in enumerate(ends):
        end=int(end);tag=k.data[text+previous:text+end].decode();previous=end
        if tag.startswith('@enter:'):
            name=tag[7:]
            if name=='forney_step':
                assert active is None
                active={'index':len(sites),'step_start':int(positions[i])}
            stack.append((name,int(positions[i]),i))
        elif tag.startswith('@exit:'):
            name,start,tag_start=stack.pop();assert name==tag[6:]
            if active is not None and name in ('gf_inverse_chain','gf_uninverse_chain'):
                key='forward' if name=='gf_inverse_chain' else 'erase'
                assert key not in active
                active[key]={'start':start+1,'stop':int(positions[i]),
                             'tag_start':tag_start+1,'tag_stop':i}
            if name=='forney_step':
                active['step_stop']=int(positions[i])+1
                assert set(active)>={'forward','erase'}
                sites.append(active);active=None
    assert not stack and len(sites)==4095
    return sites,ends,text


def prefix_counts(ops,boundaries,packet):
    # O(N) per operand family, not O(N * number_of_sites).
    starts=np.r_[0,boundaries]
    starts=np.unique(starts)
    mask=selected(ops,packet)
    sums=np.add.reduceat(mask,starts,dtype=np.int64)
    prefix=np.r_[0,np.cumsum(sums[:-1])]
    return {int(b):int(p) for b,p in zip(starts,prefix)}


def read_ops(k,start,stop,rank):
    cursors={p:rank[p][start] for p in range(2,10)}
    out=[]
    for typ in k.ops[start:stop]:
        typ=int(typ);vals=[]
        for p in targets(typ):
            vals.append(int(k.array(p)[cursors[p]]));cursors[p]+=1
        out.append((typ,vals))
    return out


def wire(local,mapping,bit,clear):
    out=[]
    for name,q,b in local:
        vals=[mapping[x] for x in q]
        if b is not None:
            assert b==0
            vals.append(bit)
        out.append((OP[name],vals))
    # Private classical garbage is never an observable DQI register.
    out.extend((0x40,[b]) for b in sorted(set(clear)|{bit}))
    return out


def encode(operations):
    result={1:bytes(op for op,_ in operations)}
    for p in range(2,10):
        values=[vals[targets(op).index(p)] for op,vals in operations if p in targets(op)]
        result[p]=np.asarray(values,dtype='<u4').tobytes()
    return result


def equal_chunks(a,ap,b,bp,length):
    for i in range(0,length,1<<22):
        n=min(1<<22,length-i)
        if a[ap+i:ap+i+n]!=b[bp+i:bp+i+n]:
            raise AssertionError('unchanged KMB span differs')


def build(baseline,output,number):
    output=Path(output);output.mkdir(parents=True,exist_ok=True)
    if sha(baseline)!=BASE_SHA:
        raise ValueError('v1.0 archive hash mismatch')
    base=output/'baseline-dqi.kmb'
    with zipfile.ZipFile(baseline) as z,z.open('dqi.kmb') as src,base.open('wb') as dst:
        shutil.copyfileobj(src,dst,1<<22)
    assert sha(base)==BASE_DQI_SHA
    k=KMB(base)
    sites,tag_ends,tag_text=find_sites(k)
    number=len(sites) if number=='all' else int(number)
    assert 1<=number<=len(sites)
    sites=sites[:number]

    formal=output/'formal';formal.mkdir(exist_ok=True)
    subprocess.run([sys.executable,str(ROOT/'research/inverse66/formal_probe.py'),
        '--out',str(formal/'formal-report.json')],check=True,stdout=subprocess.DEVNULL)
    proof=json.loads((formal/'formal-report.json').read_text())
    assert proof['retained_scaffold']['status']=='PASS'
    local={name:parse_kmx((formal/f'inverse66-{name}.kmx').read_text()) for name in ['forward','erase']}

    boundaries=set()
    for s in sites:
        for name in ['forward','erase']:
            boundaries.update([s[name]['start'],s[name]['stop']])
        boundaries.update([s['forward']['start']-1,s['forward']['start']+1,
                           s['step_start'],s['step_start']+14])
    boundaries=np.asarray(sorted(boundaries),dtype=np.int64)
    assert boundaries[-1]<len(k.ops)
    rank={p:prefix_counts(k.ops,boundaries,p) for p in range(2,10)}
    bit=k.header[2]  # fresh classical bit, outside every original target/condition
    edits={p:[] for p in range(1,10)}
    kept_tags=np.ones(len(tag_ends),dtype=bool)
    manifest=[]

    for s in sites:
        fs,fe=s['forward']['start'],s['forward']['stop']
        es,ee=s['erase']['start'],s['erase']['stop']
        # The original first gf_iadd copies input into the initially clean output.
        assert np.all(k.ops[fs+1:fs+13]==0x21)
        a=rank[5][fs+1]
        inputs=k.array(5)[a:a+12].astype(int).tolist()
        outputs=k.array(6)[a:a+12].astype(int).tolist()
        # Native init_gf2_inverse_with_scaffold resets output(12)+scaffold(48)
        # immediately before its outer INFO_TAG. These resets remain untouched.
        entry=fs-1
        assert np.all(k.ops[entry-60:entry]==0x12)
        qi=rank[7][entry]
        resets=k.array(7)[qi-60:qi].astype(int).tolist()
        assert resets[:12]==outputs and len(set(resets))==60
        scaffold=resets[12:]
        mapping=inputs+outputs+scaffold[:21]
        assert len(set(mapping))==45

        header=read_ops(k,s['step_start'],s['step_start']+14,rank)
        assert header[0][0]==6 and header[-1][0]==0x81
        guard=header[-1][1][0]
        for i,(op,v) in enumerate(header[1:13]):
            assert op==0xc1 and v==[guard,12*s['index']+i]

        # The caller cannot read the private scaffold, and only phases the inverse output.
        for p in range(2,8):
            values=k.array(p)[rank[p][fe]:rank[p][es]]
            assert not set(map(int,values))&set(scaffold)
        middle=read_ops(k,fe,es,rank)
        for op,v in middle:
            qs=v[:((op>>4)&3)]
            if set(qs)&set(outputs):
                assert op in (0x10,0x90,0x20,0xa0,0x30,0xb0)
            assert not set(qs)&set(inputs)

        row={'index':s['index'],'input_qubits':inputs,'output_qubits':outputs,
             'reused_workspace':scaffold[:21],'outer_guard_bit':guard,
             'new_temporary_bit':bit,'replacements':{}}
        for name in ['forward','erase']:
            region=s[name];start,stop=region['start'],region['stop']
            types=k.ops[start:stop]
            assert not np.any((types==0x81)|(types==0x01))
            oldT=int(np.count_nonzero(((types>>4)&3)==3))
            assert oldT==(315 if name=='forward' else 0)
            clear=k.array(8)[rank[8][start]:rank[8][stop]].astype(int).tolist()
            assert all(49140<=b<k.header[2] and b!=guard for b in clear)
            new=wire(local[name],mapping,bit,clear)
            data=encode(new)
            kept_tags[region['tag_start']:region['tag_stop']]=False
            edits[1].append((start,stop,data[1]))
            for p in range(2,10):
                edits[p].append((4*rank[p][start],4*rank[p][stop],data[p]))
            row['replacements'][name]={'old_start_zero_based':start,'old_stop_exclusive':stop,
                'old_ops':stop-start,'new_ops':len(new),'old_Toffoli_like':oldT,
                'new_Toffoli_like':sum((op>>4)&3==3 for op,_ in new)}
        manifest.append(row)

    head=bytearray(k.data[:104])
    struct.pack_into('<I',head,24,bit+1)
    for index,(packet,width) in enumerate([(1,1),(2,4),(5,4),(7,4),(8,4),(9,4)]):
        delta=sum(len(payload)-(b-a) for a,b,payload in edits[packet])//width
        struct.pack_into('<Q',head,32+8*index,k.header[4+index]+delta)
    old_lengths=np.diff(np.r_[np.uint64(0),tag_ends])
    new_ends=np.cumsum(old_lengths[kept_tags],dtype='<u8')
    char_edits=[]
    for s in sites:
        for name in ['forward','erase']:
            x=s[name]
            a=0 if x['tag_start']==0 else int(tag_ends[x['tag_start']-1])
            b=0 if x['tag_stop']==0 else int(tag_ends[x['tag_stop']-1])
            char_edits.append((a,b,b''))
    new_chars=int(new_ends[-1]) if len(new_ends) else 0
    struct.pack_into('<Q',head,88,len(new_ends))
    struct.pack_into('<Q',head,96,new_chars)
    candidate=output/'dqi.kmb'
    with candidate.open('wb') as dst:
        dst.write(head)
        stream_copy(dst,k.data,104,k.packets[1][0]-16)
        for p in range(1,12):
            original,size=k.packets[p]
            if p==11:
                dst.write(struct.pack('<QQQ',11,8+8*len(new_ends)+new_chars,len(new_ends)))
                dst.write(new_ends.tobytes())
                cursor=0
                for a,b,_ in char_edits:
                    stream_copy(dst,k.data,tag_text+cursor,tag_text+a);cursor=b
                stream_copy(dst,k.data,tag_text+cursor,tag_text+int(tag_ends[-1]))
                continue
            changes=edits.get(p,[])
            dst.write(struct.pack('<QQ',p,size+sum(len(v)-(b-a) for a,b,v in changes)))
            cursor=0
            for a,b,v in changes:
                assert cursor<=a<=b<=size
                stream_copy(dst,k.data,original+cursor,original+a)
                dst.write(v);cursor=b
            stream_copy(dst,k.data,original+cursor,original+size)

    c=KMB(candidate)
    assert c.registers==k.registers and c.header[1]==1893 and c.header[2]==49155
    assert c.header[5]==k.header[5]-249*number
    equal_chunks(k.data,104,c.data,104,k.packets[1][0]-16-104)
    preserved=0
    for p in range(1,11):
        old,size=k.packets[p];new,ns=c.packets[p]
        original_cursor=0;new_cursor=0
        for a,b,v in edits.get(p,[]):
            length=a-original_cursor
            equal_chunks(k.data,old+original_cursor,c.data,new+new_cursor,length)
            preserved+=length;new_cursor+=length
            assert c.data[new+new_cursor:new+new_cursor+len(v)]==v
            new_cursor+=len(v);original_cursor=b
        equal_chunks(k.data,old+original_cursor,c.data,new+new_cursor,size-original_cursor)
        preserved+=size-original_cursor
        assert new_cursor+size-original_cursor==ns

    (output/'site-map.json').write_text(json.dumps(manifest,indent=2)+'\n')
    report={'status':'PASS','scope':'complete DQI; retained-scaffold inverse66 replacement',
        'baseline_zip_sha256':BASE_SHA,'baseline_dqi_sha256':BASE_DQI_SHA,
        'candidate_sha256':sha(candidate),'candidate_bytes':candidate.stat().st_size,
        'sites_replaced':number,'inverse_regions_replaced':2*number,
        'qubits':c.header[1],'bits':c.header[2],'registers':c.header[3],
        'baseline_static_Toffoli_like':k.header[5],'candidate_static_Toffoli_like':c.header[5],
        'static_Toffoli_saved':249*number,'ops':c.header[4],
        'workspace_policy':'reuse first 21 of each original 48-qubit scaffold',
        'named_registers_unchanged':True,'outer_classical_guards_preserved':True,
        'unchanged_packet_span_bytes_verified':preserved,
        'nested_metadata_only_removed':int(np.count_nonzero(~kept_tags)),
        'local_formal_proof':proof['retained_scaffold'],
        'kickmix_full_parse':'NOT_RUN','official_DQI_verifier':'NOT_RUN',
        'score_improvement':'UNCONFIRMED','submits_to_kaggle':False}
    (output/'integration-report.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps({key:report[key] for key in ['status','sites_replaced','qubits','bits',
        'candidate_static_Toffoli_like','static_Toffoli_saved','candidate_sha256','candidate_bytes']},indent=2))


def parse_full(output):
    import kickmix as km
    output=Path(output);path=output/'integration-report.json'
    report=json.loads(path.read_text())
    candidate=output/'dqi.kmb'
    assert sha(candidate)==report['candidate_sha256']
    circuit=km.Circuit.from_file(candidate,format='kmb')
    assert circuit.num_qubits==report['qubits'] and circuit.num_bits==report['bits']
    assert circuit.operation_statistics().num_toffoli_like==report['candidate_static_Toffoli_like']
    report['kickmix_full_parse']='PASS'
    path.write_text(json.dumps(report,indent=2)+'\n')
    print('Complete inverse66 DQI Kickmix parse PASS')


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--baseline')
    p.add_argument('--output',default='build/inverse66')
    p.add_argument('--sites',default='all')
    p.add_argument('--parse',action='store_true')
    a=p.parse_args()
    if a.parse:parse_full(a.output)
    elif not a.baseline:p.error('--baseline required')
    else:build(a.baseline,a.output,a.sites)
