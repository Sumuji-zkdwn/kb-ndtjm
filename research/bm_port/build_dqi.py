#!/usr/bin/env python3
"""Conservative BM + variable-mask WFS/Forney DQI. Never submits to Kaggle.

Keep all coefficients and the complete DP-bounded reversal stack. Do not use
the public decoder's measured clipping, fixed masks, or approximate Psi route.
"""
import argparse
from contextlib import contextmanager
import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import time

HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[1]
sys.path.insert(0,str(ROOT/'quantum'))
sys.path.insert(0,str(ROOT/'research/eea_boolean'))
from dqi_gate import sha
from quotient_probe import parse
from wfs_mobile_ci import compile_ops, verify_exact
from uncompute import Builder
from uncompute.classical import GF2n,f2_matinv
from uncompute.gadgets import linear_in_place
from check_provenance import check as check_provenance

def load_vendor():
    spec=importlib.util.spec_from_file_location('attributed_bm',HERE/'vendor/circuit.py')
    v=importlib.util.module_from_spec(spec);spec.loader.exec_module(v)
    v.STK_CAP=v.W
    v.CAPS=list(v.CAPS_FULL)
    v.IMAXV=[min(r,v.W) for r in range(v.N)]
    v.KMSV=[min(r+1,v.W) for r in range(v.N)]
    v.KMMV=v.KMSV[:];v.KMMV[0]=0
    assert max(v.CAPS)==v.W==35
    return v

def basis_maps():
    import kickmix as km
    google=GF2n(12,0x1053);public=GF2n(12,0x10eb)
    assert google.gen==km.GF2Field(12).primitive_element==2
    def eval_poly(x):
        acc=0
        for i in range(12,-1,-1):acc=google.mul(acc,x)^((0x10eb>>i)&1)
        return acc
    root=next(x for x in range(2,4096) if eval_poly(x)==0)
    cols=[google.pow(root,i) for i in range(12)]
    phi=lambda x:__import__('functools').reduce(int.__xor__,(cols[i] for i in range(12) if x>>i&1),0)
    assert len({phi(x) for x in range(4096)})==4096
    for i in range(12):
        for j in range(12):assert phi(public.mul(1<<i,1<<j))==google.mul(cols[i],cols[j])
    rows=[sum(((cols[j]>>i)&1)<<j for j in range(12)) for i in range(12)]
    return google,rows,f2_matinv(rows,12),root

def linear_schedule(rows):
    class Recorder:
        def __init__(self):self.ops=[]
        def cx(self,a,b):self.ops.append((0x21,[a,b]))
        def swap(self,a,b):self.ops.append((0x22,[a,b]))
    r=Recorder();linear_in_place(r,list(range(12)),rows);return r.ops

def rows_of(fn):
    cols=[fn(1<<j) for j in range(12)]
    return [sum(((cols[j]>>i)&1)<<j for j in range(12)) for i in range(12)]

def emit_local(b,ops,mapping,mask=None):
    opcodes={'CX':0x21,'CCX':0x31,'CCZ':0x30,'SWAP':0x22,'CZ':0x20,'Z':0x10,'HMR':0x50}
    for gate,values,condition in ops:
        bit=None
        if gate=='HMR':
            assert values[1]==0
            qs=[mapping[values[0]]];bit=49141
        else:qs=[mapping[q] for q in values]
        cond=None if condition is None else (mask[condition] if mask is not None else 49141)
        b.raw(opcodes[gate],qs,bit=bit,cond=cond)

@contextmanager
def forney_workspace(b,clean_scratch=()):
    """Borrow only Em's three clean pivots; keep their held ownership.

    Em.pivot_pair unbuilds sA/sB and Em.fan_pair HMR-erases sT with
    phase repayment. No Em operation runs inside Forney. Its matched
    inverse erase, root-tree erase and WFS cleanup return all 81 wires
    to zero before the held pivots are used again. Never reset a wire.
    """
    borrowed=list(clean_scratch)
    if len(borrowed) not in (0,3) or len(set(borrowed))!=len(borrowed):
        raise ValueError('expected zero or three distinct clean Em pivots')
    if any(q not in b.live or b.owners.get(q)!='held' for q in borrowed):
        raise ValueError('borrowed Em pivots must remain live and held')
    owned=b.qubits(81-len(borrowed));b.claim('forney',owned)
    try:
        yield owned+borrowed
    finally:
        b.release_recycle('forney',owned)

def forney(b,v,sigma,omega,google,formal,clean_scratch=()):
    forward=parse((formal/'inverse66-forward.kmx').read_text())
    erase=parse((formal/'inverse66-erase.kmx').read_text())
    kernel=parse('\n'.join(compile_ops(0x1053,1)))
    verify_exact(compile_ops(0x1053,1),0x1053,1)
    sqrt_rows=rows_of(lambda x:google.pow(x,2048))
    square_rows=rows_of(lambda x:google.mul(x,x))
    sqrt_ops,square_ops=linear_schedule(sqrt_rows),linear_schedule(square_rows)
    for x in range(4096):assert google.mul(google.pow(x,2048),google.pow(x,2048))==x
    with forney_workspace(b,clean_scratch) as work:
        _forney_sweep(b,sigma,omega,google,work,forward,erase,kernel,sqrt_ops,square_ops)

def _forney_sweep(b,sigma,omega,google,work,forward,erase,kernel,sqrt_ops,square_ops):
    sig,den,num=work[:12],work[12:24],work[24:36]
    inv,tree,scratch=work[36:69],work[69:80],work[80]
    mapping=den+inv
    # sigma_k holds sigma_k*z^k; omega_i holds omega_i*z^(i+1).
    # Thus sum(odd sigma_k)=z*sigma'(z), sum(omega_i)=z*omega(z).
    steps=[]
    for k,reg in list(enumerate(sigma[1:],1))+list(enumerate(omega,1)):
        factor=google.pow(google.gen,(-k)%4095)
        steps.append((reg,linear_schedule(rows_of(lambda x,f=factor:google.mul(x,f)))))
    pairs=[(q,sig[i]) for reg in sigma[1:] for i,q in enumerate(reg)]
    pairs += [(q,den[i]) for reg in sigma[1::2] for i,q in enumerate(reg)]
    pairs += [(q,num[i]) for reg in omega for i,q in enumerate(reg)]
    with b.phase('variable_mask_forney'):
        for j in range(4095):
            b.x(sig[0])
            for q,t in pairs:b.cx(q,t)
            for q in sig:b.x(q)
            b.ccx(sig[0],sig[1],tree[0])
            for i in range(2,12):b.ccx(tree[i-2],sig[i],tree[i-1])
            emit_local(b,forward,mapping)
            for op,qs in sqrt_ops:b.raw(op,[inv[q] for q in qs])
            emit_local(b,kernel,num+inv[:12]+[tree[-1],scratch],list(range(j*12,(j+1)*12)))
            for op,qs in square_ops:b.raw(op,[inv[q] for q in qs])
            emit_local(b,erase,mapping)
            for i in range(11,1,-1):b.cz(tree[i-2],sig[i],cond=b.hmr(tree[i-1]))
            b.cz(sig[0],sig[1],cond=b.hmr(tree[0]))
            for q in sig:b.x(q)
            for q,t in reversed(pairs):b.cx(q,t)
            b.x(sig[0])
            for reg,ops in steps:
                for op,qs in ops:b.raw(op,[reg[q] for q in qs])

def build(out,decode_only=False,reuse_forney_scratch=True,trace_allocations=False,trace_phase=False):
    check_provenance()
    out.mkdir(parents=True,exist_ok=True)
    formal=out/'formal';formal.mkdir(exist_ok=True)
    subprocess.run([sys.executable,str(ROOT/'research/inverse66/formal_probe.py'),
                    '--out',str(formal/'inverse-report.json')],check=True,stdout=subprocess.DEVNULL)
    v=load_vendor();google,to_google,to_public,root=basis_maps()
    b=Builder(trace_allocations=trace_allocations);syn=[b.qubits(12) for _ in range(70)]
    b.claim('syn',[q for r in syn for q in r])
    with b.phase('google_to_public'):
        for reg in syn:linear_in_place(b,reg,to_public)
    held=b.qubits(v.B+v.DWB+3)
    Dw,dW=held[:12],held[12:20]
    b.claim('held',held)
    A=v.Alloc(b);E=v.Em(b,*held[20:23],A);bm=v.BM(E,A,syn,Dw,dW)
    bm.run()
    sigma=[list(x) for x in bm.SIG]
    v.mon_stage(E,bm.SIG,'monicize',range(1,36),True)
    mac=v.omega_rts(bm.SIG,syn)
    v.omega_pass(E,mac,'omega',range(len(mac)))
    if not decode_only:
        with b.phase('coefficients_to_google'):
            for reg in sigma[1:]+syn[:35]:linear_in_place(b,reg,to_google)
        if trace_phase:
            from trace_phase import forney_trace
            forney_trace(b,v,sigma,syn[:35],google,formal,held[20:23] if reuse_forney_scratch else ())
        else:
            forney(b,v,sigma,syn[:35],google,formal,held[20:23] if reuse_forney_scratch else ())
        with b.phase('coefficients_to_public'):
            for reg in sigma[1:]+syn[:35]:linear_in_place(b,reg,to_public)
    v.omega_pass(E,mac,'omega_restore',reversed(range(len(mac))))
    v.mon_stage(E,bm.SIG,'unmonicize',range(35,0,-1),False)
    bm.reverse()
    b.release_recycle('held',held)
    with b.phase('public_to_google'):
        for reg in syn:linear_in_place(b,reg,to_google)
    b.write(out/'dqi.kmb')
    report={'scope':'complete DQI conservative BM and variable-mask WFS Forney' if not decode_only else 'IDENTITY ROUNDTRIP DEBUG ONLY',
        'candidate_sha256':sha(out/'dqi.kmb'),'candidate_bytes':(out/'dqi.kmb').stat().st_size,
        'qubits':b.nq,'peak_live':b.peak_live,'bits':b.nb,'static_Toffoli':len(b.p[2]),
        'ops':len(b.p[1]),'basis_root':root,'basis_checked_values':4096,'basis_product_pairs':144,
        'BM_coefficient_clipping':False,'stack_cap':35,'stack_is_complete_DP_bound':True,
        'fixed_public_mask_used':False,'approximate_Psi_route_used':False,
        'forney_borrowed_clean_Em_pivots':3 if reuse_forney_scratch and not decode_only else 0,
        'forney_phase_method':'relative_trace_6' if trace_phase and not decode_only else 'inverse66_WFS12',
        'source_commit':'64b5a13aa249f1360846657392e6c66817b26d0f',
        'attribution':'andigu/uncompute BM, inverse66 and field tensors (Apache-2.0); adapted to Kaggle variable E masks',
        'stages':b.stages,'full_verifier':'NOT_RUN','kaggle_submission':'NOT_RUN'}
    (out/'generation.json').write_text(json.dumps(report,indent=2)+'\n')
    if trace_allocations:
        (out/'allocations.json').write_text(json.dumps(b.allocation_events,indent=2)+'\n')
    print(json.dumps({k:v for k,v in report.items() if k!='stages'},indent=2))

def parse_complete(out):
    import kickmix as km
    report=json.loads((out/'generation.json').read_text())
    assert sha(out/'dqi.kmb')==report['candidate_sha256']
    circuit=km.Circuit.from_file(str(out/'dqi.kmb'),format='kmb')
    assert (circuit.num_qubits,circuit.num_bits,circuit.num_registers)==(report['qubits'],report['bits'],4165)
    parsed={'status':'PASS','candidate_sha256':report['candidate_sha256'],
            'qubits':circuit.num_qubits,'bits':circuit.num_bits,'registers':circuit.num_registers,
            'scope':'native Kickmix parse of complete KMB; not a correctness proof'}
    (out/'parse.json').write_text(json.dumps(parsed,indent=2)+'\n')
    print(json.dumps(parsed,indent=2))

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--out',type=Path,default=ROOT/'build/bm-conservative')
    p.add_argument('--decode-only',action='store_true')
    p.add_argument('--no-reuse-forney-scratch',action='store_true',help='Reproduce the verified 2485-qubit allocation')
    p.add_argument('--trace-allocations',action='store_true',help='Record allocation, ownership and phase boundaries')
    p.add_argument('--trace-phase',action='store_true',help='Use the exactly checked 72-Toffoli inverse phase')
    p.add_argument('--parse',action='store_true',help='Parse an existing complete candidate without rebuilding')
    args=p.parse_args()
    if args.parse:parse_complete(args.out)
    else:build(args.out,args.decode_only,not args.no_reuse_forney_scratch,args.trace_allocations,args.trace_phase)
