"""Fail-closed allocation adapter and direct KMB v2 writer.

No resets on allocation/free: dirty scratch cannot be silently discarded.
Each HMR token is valid only until the next HMR using that private bit.
All declared E bits are read-only. Ownership claims are checked on every release.
"""
from array import array
from contextlib import contextmanager
from dataclasses import dataclass
import struct
import sys

Mark = int  # Only Journal is used from the attributed Bennett helper.
MAGIC = bytes.fromhex('d750c7d5c329d326e3cc9f6834f2b8bf')

@dataclass(frozen=True)
class Outcome:
    generation: int

class Builder:
    def __init__(self):
        self.p = {i: array('B' if i == 1 else 'I') for i in range(1,11)}
        self.tags = []
        self.nq = 0
        self.nb = 49142
        self.free = []
        self.live = set()
        self.owners = {}
        self.generation = 0
        self.peak_live = 0
        self.stages = []

    def raw(self, op, qs=(), bit=None, cond=None):
        if len(qs) != (op >> 4) & 3 or len(set(qs)) != len(qs):
            raise ValueError('gate arity or aliased operands')
        if any(q not in self.live for q in qs):
            raise ValueError('operation on a free wire')
        if cond is not None:
            if isinstance(cond, Outcome):
                if cond.generation != self.generation:
                    raise ValueError('stale measurement token')
                cond = 49140
            op |= 128
        self.p[1].append(op)
        packets = {0: [], 1:[7], 2:[5,6], 3:[2,3,4]}[len(qs)]
        for p,q in zip(packets,qs): self.p[p].append(q)
        if op & 64:
            if bit is None or bit < 49140: raise ValueError('E registers are read-only')
            self.p[8].append(bit)
        if op & 128:
            if cond is None or not 0 <= cond < self.nb: raise ValueError('bad condition')
            self.p[9].append(cond)

    def x(self,q,cond=None): self.raw(0x11,[q],cond=cond)
    def z(self,q,cond=None): self.raw(0x10,[q],cond=cond)
    def neg(self,cond=None): self.raw(0,cond=cond)
    def cx(self,a,b,cond=None): self.raw(0x21,[a,b],cond=cond)
    def cz(self,a,b,cond=None): self.raw(0x20,[a,b],cond=cond)
    def ccx(self,a,b,t): self.raw(0x31,[a,b,t])
    def ccz(self,a,b,c): self.raw(0x30,[a,b,c])
    def swap(self,a,b): self.raw(0x22,[a,b])
    def cswap(self,c,a,b):
        self.cx(a,b);self.ccx(c,b,a);self.cx(a,b)
    def hmr(self,q):
        self.generation += 1
        self.raw(0x50,[q],bit=49140)
        return Outcome(self.generation)

    def qubits(self,n):
        out=[]
        for _ in range(n):
            if self.free: q=self.free.pop()
            else: q=self.nq;self.nq+=1
            assert q not in self.live
            self.live.add(q);out.append(q)
        self.peak_live=max(self.peak_live,len(self.live))
        return out
    def reclaim(self,qs):
        for q in qs:
            if q in self.live or q not in self.free: raise ValueError('reclaim of occupied/nonexistent wire')
            self.free.remove(q);self.live.add(q)
        self.peak_live=max(self.peak_live,len(self.live))
    def claim(self,name,qs):
        for q in qs:
            if q not in self.live or q in self.owners: raise ValueError('ownership conflict')
            self.owners[q]=name
    def release(self,name,qs):
        for q in qs:
            if self.owners.pop(q,None)!=name: raise ValueError('ownership release mismatch')
    def recycle_all(self,qs):
        for q in qs:
            if q not in self.live or q in self.owners: raise ValueError('recycle of owned/free wire')
            self.live.remove(q);self.free.append(q)
    def release_recycle(self,name,qs):
        self.release(name,qs);self.recycle_all(reversed(qs))
    @contextmanager
    def phase(self,name):
        start=(len(self.p[1]),len(self.p[2]))
        self.tag('@enter:'+name)
        yield
        self.tag('@exit:'+name)
        self.stages.append({'stage':name,'ops':len(self.p[1])-start[0],
                            'static_Toffoli':len(self.p[2])-start[1]})
    def tag(self,text):
        self.p[1].append(6);self.tags.append(text.encode())
    def write(self,path):
        if sys.byteorder!='little': raise RuntimeError('KMB writer requires little endian')
        assert self.live==set(range(840)) and set(self.owners)==self.live
        for bit in (49140,49141): self.raw(0x40,bit=bit)
        chars=b''.join(self.tags);ends=[];end=0
        for tag in self.tags: end+=len(tag);ends.append(end)
        head=struct.pack('<4I9Q',2,self.nq,self.nb,4165,len(self.p[1]),len(self.p[2]),
            len(self.p[5]),len(self.p[7]),len(self.p[8]),len(self.p[9]),0,len(self.tags),len(chars))
        with open(path,'wb') as f:
            f.write(MAGIC+head)
            for prefix,n,quantum in [('S',70,True),('E',4095,False)]:
                for i in range(n):
                    name=f'{prefix}{i}'.encode()
                    regs=[(12*i+j)|(0x80000000 if quantum else 0) for j in range(12)]
                    data=struct.pack('<II',len(name),12)+name+struct.pack('<12I',*regs)
                    f.write(struct.pack('<QQ',0,len(data))+data)
            for i,p in self.p.items():
                f.write(struct.pack('<QQ',i,len(p)*p.itemsize));p.tofile(f)
            data=struct.pack('<Q',len(ends))+array('Q',ends).tobytes()+chars
            f.write(struct.pack('<QQ',11,len(data))+data)
