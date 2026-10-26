"""Exact GF(4096)/GF(64)/GF(8) Forney trace phase, 69 Toffoli-like.

Retains all BM history, coefficients, masks and the existing 81-wire workspace.
The old six-coordinate inverse norm output is reused for a three-coordinate
relative trace. The standalone inverse66 and previous trace phase are unchanged.
"""
from collections import Counter
from trace_phase import TracePhase,convert,schedule,lin


class TracePhase3(TracePhase):
    def __init__(self):
        super().__init__()
        m=self.m;f=self.f;basis=m.LIN['E12']
        self.embed3=lambda x:self.embed(x&7)
        assert all(f.pow(basis[i],8)==basis[i] for i in range(3))
        assert all(f.pow(basis[i+3],8)==basis[i+3]^basis[i] for i in range(3))
        self.gram3=[sum(f.trace(f.mul(basis[i],basis[j]),3)<<j for j in range(3)) for i in range(3)]
        forward=m.Emitter();erase=m.Emitter()
        for _,_,prods,lins in m.STAGES[:3]:
            for s,t in lins:forward.emit('CX',s,t)
            for a,b,t in prods:forward.prod(a,b,t)
        for _,tg,prods,lins in reversed(m.STAGES[:3]):
            for target in reversed(tg):erase.erase_bit(target,prods,lins)
        self.forward,self.erase=convert(forward.ops),convert(erase.ops)
        # Norm(D)=n0+n1*alpha; G=g0+g1*alpha, alpha^8=alpha+1.
        # Tr_64/8(G*conjugate(Norm(D))) = g0*n1 + g1*n0.
        n0=m.exprs_wire(list(range(24,27)));n1=m.exprs_wire(list(range(27,30)))
        g0=m.exprs_wire(list(range(45,48)));g1=m.exprs_wire(list(range(48,51)))
        self.nested_prods=m.mult_terms(m.KT3,n1,g0,list(range(36,39)))+m.mult_terms(m.KT3,n0,g1,list(range(36,39)))
        out=m.Emitter();back=m.Emitter()
        for a,b,t in self.nested_prods:out.prod(a,b,t)
        for t in reversed(range(36,39)):back.erase_bit(t,self.nested_prods,[])
        self.nested_forward,self.nested_erase=convert(out.ops),convert(back.ops)
        # QS holds Norm_64/8(Norm_4096/64(D))^3; square gives inverse.
        self.pairing3=[(g,[33+q for q in qs],c) for rows in (m.LIN['SQ3R'],self.gram3) for g,qs,c in schedule(rows)]
        assert Counter(g for g,_,_ in self.forward)['CCX']==24
        assert Counter(g for g,_,_ in self.nested_forward)['CCX']==12
        assert not any(g=='CCX' for g,_,_ in self.erase+self.nested_erase)

    def middle_steps(self):
        mask=[('CX',[45+j,12+i],k) for j,i,k in self.masked]
        # None marks a fresh omega evaluation (or readonly local N copy).
        return [None,mask,None,self.coefficient_forward,self.nested_forward,self.pairing3,
            [('CCZ',[57,36+i,33+i],None) for i in range(3)],
            list(reversed(self.pairing3)),self.nested_erase,self.coefficient_erase,
            None,list(reversed(mask)),None]

    def middle(self,num_pairs=None):
        copy=[('CX',[s,t],None) for s,t in (num_pairs or [(58+i,45+i) for i in range(12)])]
        return [op for step in self.middle_steps() for op in (copy if step is None else step)]

    def emit(self,b,mapping,mask_bits,num_pairs):
        opcodes={'CX':0x21,'CCX':0x31,'CCZ':0x30,'SWAP':0x22,'CZ':0x20,'Z':0x10}
        def emit(ops):
            for gate,qs,condition in ops:
                if gate=='HMR':b.raw(0x50,[mapping[qs[0]]],bit=49141)
                else:
                    bit=None if condition is None else (49141 if gate in ('Z','CZ') else mask_bits[condition])
                    b.raw(opcodes[gate],[mapping[q] for q in qs],cond=bit)
        emit(self.forward)
        for step in self.middle_steps():
            if step is None:
                for s,t in num_pairs:b.cx(s,t)
            else:emit(step)
        emit(self.erase)
