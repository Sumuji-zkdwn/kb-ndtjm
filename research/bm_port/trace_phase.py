"""Exact variable-mask Forney phase via GF(4096)/GF(64) relative trace.

Uses the attributed inverse66 tower's first four stages (36 products),
two GF(64) products (30), and six root-controlled phase gates. The standalone
inverse66 is unchanged. No masks, coefficients or BM history are truncated.
"""
from collections import Counter
from functools import reduce
import hashlib
import json
from pathlib import Path
import types
import zipfile
from uncompute.classical import GF2n,f2_matinv
from uncompute.gadgets import linear_in_place

HERE=Path(__file__).resolve().parent
ARCHIVE=HERE.parent/'inverse66/tower_inverse66_probe.zip'
ARCHIVE_SHA='25c74454ef8c00b44bb42177f491c196743f3dedd24e3ec5f096fbb60e6c19c3'


def tower():
    assert hashlib.sha256(ARCHIVE.read_bytes()).hexdigest()==ARCHIVE_SHA
    with zipfile.ZipFile(ARCHIVE) as z:source=z.read('tower_inverse66.py').decode()
    m=types.ModuleType('attributed_tower_trace_phase')
    exec(compile(source,'attributed/tower_inverse66.py','exec'),m.__dict__)
    m.change_to_google_basis()
    return m


def lin(rows,x):
    return sum(((r&x).bit_count()&1)<<i for i,r in enumerate(rows))


def field_data(m):
    f=GF2n(12,0x1053);basis=m.LIN['E12']
    embed=lambda x:reduce(int.__xor__,(basis[i] for i in range(6) if x>>i&1),0)
    gram12=[sum(f.trace(f.mul(1<<i,1<<j))<<j for j in range(12)) for i in range(12)]
    dual=f2_matinv(gram12,12)
    gram6=[sum(f.trace(f.mul(basis[i],basis[j]),6)<<j for j in range(6)) for i in range(6)]
    f2_matinv(gram6,6)
    assert all(f.pow(basis[i],64)==basis[i] for i in range(6))
    assert all(f.pow(basis[i+6],64)==basis[i+6]^basis[i] for i in range(6))
    # U = tower_coordinates(C*N), where parity(mask*x)=Tr_4096(C*x).
    masked=[]
    for k in range(12):
        c=lin(dual,1<<k)
        assert all(f.trace(f.mul(c,1<<i))==int(k==i) for i in range(12))
        for j in range(12):
            col=lin(m.LIN['A0ROWS']+m.LIN['A1ROWS'],f.mul(c,1<<j))
            for i in range(12):
                if col>>i&1:masked.append((j,i,k))
    return f,embed,dual,gram6,masked


def schedule(rows):
    class Recorder:
        def __init__(self):self.ops=[]
        def cx(self,a,b):self.ops.append(('CX',[a,b],None))
        def swap(self,a,b):self.ops.append(('SWAP',[a,b],None))
    b=Recorder();linear_in_place(b,list(range(len(rows))),rows);return b.ops


def convert(ops):
    result=[]
    for op in ops:
        g=op[0]
        if g=='HMR':result.append(('HMR',[op[1]],op[2]))
        elif g.endswith('if'):result.append((g[:-2],list(op[1:-1]),op[-1]))
        else:result.append((g,list(op[1:]),None))
    return result


class TracePhase:
    """Canonical wires: den0:12, U12:24, norm24:42, pivots42:45,
    num45:57, root57, readonly numerator source58:70. num starts/ends zero.
    The numerator-copy operation is rebound to omega evaluation in full DQI.
    """
    def __init__(self):
        m=self.m=tower()
        self.f,self.embed,self.dual,self.gram6,self.masked=field_data(m)
        forward=m.Emitter();erase=m.Emitter()
        for _,_,prods,lins in m.STAGES[:4]:
            for s,t in lins:forward.emit('CX',s,t)
            for a,b,t in prods:forward.prod(a,b,t)
        for _,tg,prods,lins in reversed(m.STAGES[:4]):
            for target in reversed(tg):erase.erase_bit(target,prods,lins)
        self.forward,self.erase=convert(forward.ops),convert(erase.ops)
        a0=m.exprs_from_rows(m.LIN['A0ROWS'],list(range(12)))
        a1=m.exprs_from_rows(m.LIN['A1ROWS'],list(range(12)))
        u0=m.exprs_wire(list(range(12,18)));u1=m.exprs_wire(list(range(18,24)))
        # Tr_4096/64(U*conjugate(D)) = U0*D1 + U1*D0.
        self.prods=m.mult_terms(m.KT6,a1,u0,list(range(45,51)))+m.mult_terms(m.KT6,a0,u1,list(range(45,51)))
        out=m.Emitter();back=m.Emitter()
        for a,b,t in self.prods:out.prod(a,b,t)
        for t in reversed(range(45,51)):back.erase_bit(t,self.prods,[])
        self.coefficient_forward,self.coefficient_erase=convert(out.ops),convert(back.ops)
        self.pairing=schedule(self.gram6)
        assert Counter(g for g,_,_ in self.forward)['CCX']==36
        assert Counter(g for g,_,_ in self.coefficient_forward)['CCX']==30
        assert not any(g=='CCX' for g,_,_ in self.erase+self.coefficient_erase)

    def middle(self,num_pairs=None):
        pairs=num_pairs or [(58+i,45+i) for i in range(12)]
        copy=[('CX',[s,t],None) for s,t in pairs]
        mask=[('CX',[45+j,12+i],k) for j,i,k in self.masked]
        pairing=[(g,[36+q for q in qs],c) for g,qs,c in self.pairing]
        return (copy+mask+copy+self.coefficient_forward+pairing+
            [('CCZ',[57,45+i,36+i],None) for i in range(6)]+
            list(reversed(pairing))+self.coefficient_erase+copy+
            list(reversed(mask))+copy)

    def operations(self):
        return self.forward+self.middle()+self.erase

    def emit(self,b,mapping,mask_bits,num_pairs):
        opcodes={'CX':0x21,'CCX':0x31,'CCZ':0x30,'SWAP':0x22,'CZ':0x20,'Z':0x10}
        def emit(ops):
            for gate,qs,condition in ops:
                if gate=='HMR':b.raw(0x50,[mapping[qs[0]]],bit=49141)
                else:
                    bit=None if condition is None else (49141 if gate in ('Z','CZ') else mask_bits[condition])
                    b.raw(opcodes[gate],[mapping[q] for q in qs],cond=bit)
        def copy():
            for s,t in num_pairs:b.cx(s,t)
        emit(self.forward)
        copy()
        emit([('CX',[45+j,12+i],k) for j,i,k in self.masked])
        copy()
        emit(self.coefficient_forward)
        pairing=[(g,[36+q for q in qs],c) for g,qs,c in self.pairing]
        emit(pairing)
        emit([('CCZ',[57,45+i,36+i],None) for i in range(6)])
        emit(list(reversed(pairing)))
        emit(self.coefficient_erase)
        copy()
        emit([('CX',[45+j,12+i],k) for j,i,k in reversed(self.masked)])
        copy()
        emit(self.erase)


def forney_trace(b,v,sigma,omega,google,formal,clean_scratch=(),nested=False,scalar=False):
    from build_dqi import forney_workspace,linear_schedule,rows_of
    if nested and scalar:raise ValueError('select one trace implementation')
    if scalar:
        from trace_phase5 import TracePhase5 as Phase
        from trace_phase5_probe import verify
    elif nested:
        from trace_phase3 import TracePhase3 as Phase
        from trace_phase3_probe import verify
    else:
        Phase=TracePhase
        from trace_phase_probe import verify
    p=Phase();proof=verify(p)
    (formal/('trace-phase5-report.json' if scalar else 'trace-phase3-report.json' if nested else 'trace-phase-report.json')).write_text(json.dumps(proof,indent=2)+'\n')
    steps=[]
    for k,reg in list(enumerate(sigma[1:],1))+list(enumerate(omega,1)):
        factor=google.pow(google.gen,(-k)%4095)
        steps.append((reg,linear_schedule(rows_of(lambda x,f=factor:google.mul(x,f)))))
    with forney_workspace(b,clean_scratch) as work:
        sig,den,num=work[:12],work[12:24],work[24:36]
        inv,tree=work[36:69],work[69:80]
        mapping=den+inv+num+[tree[-1]]
        pairs=[(q,sig[i]) for reg in sigma[1:] for i,q in enumerate(reg)]
        pairs += [(q,den[i]) for reg in sigma[1::2] for i,q in enumerate(reg)]
        num_pairs=[(q,num[i]) for reg in omega for i,q in enumerate(reg)]
        with b.phase('variable_mask_forney'):
            for j in range(4095):
                b.x(sig[0])
                for q,t in pairs:b.cx(q,t)
                for q in sig:b.x(q)
                b.ccx(sig[0],sig[1],tree[0])
                for i in range(2,12):b.ccx(tree[i-2],sig[i],tree[i-1])
                p.emit(b,mapping,list(range(j*12,(j+1)*12)),num_pairs)
                for i in range(11,1,-1):b.cz(tree[i-2],sig[i],cond=b.hmr(tree[i-1]))
                b.cz(sig[0],sig[1],cond=b.hmr(tree[0]))
                for q in sig:b.x(q)
                for q,t in reversed(pairs):b.cx(q,t)
                b.x(sig[0])
                for reg,ops in steps:
                    for op,qs in ops:b.raw(op,[reg[q] for q in qs])
