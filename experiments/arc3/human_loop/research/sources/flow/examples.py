"""Generate exact pedagogical and response-only finite systems, not a 3D solver."""
from itertools import permutations
from pathlib import Path
import json
from finite import System,witness_certificate,verify_witness

BASE=Path(__file__).resolve().parent.parent

def hidden_load():
    return System.from_dict(dict(format='flow-finite-system-r2',states=['calm','loaded','open'],
        actions=['push','rest'],observation={'calm':'closed','loaded':'closed','open':'open'},
        transitions=[{'from':s,'action':a,'to':t} for s,a,t in
        [('calm','push','loaded'),('loaded','push','open'),('open','push','open'),
         ('calm','rest','calm'),('loaded','rest','calm'),('open','rest','open')]]))

def compose(p,q):return tuple(p[q[i]] for i in range(3))
def inverse(p):return tuple(p.index(i) for i in range(3))
def state_id(p,k):return ''.join(map(str,p))+':'+str(k)

def response_system(amplification=True, bound=40):
    if type(bound) is not int or bound<1:raise ValueError('Positive integer bound required')
    pairs=[(p,k) for p in permutations(range(3)) for k in range(-bound,bound+1)]
    actions=['invert','normalise','turnA','turnB','backA','backB']
    if amplification:actions+=['double','half']
    A=(1,0,2);B=(0,2,1);tr=[]
    for p,k in pairs:
        for a in actions:
            if a=='invert':pp,kk=inverse(p),-k
            elif a=='normalise':pp,kk=p,0
            elif a in ('double','half'):pp,kk=p,k+(1 if a=='double' else -1)
            else:pp,kk=compose(A if a in ('turnA','backA') else B,p),k
            if abs(kk)<=bound:tr.append({'from':state_id(p,k),'action':a,'to':state_id(pp,kk)})
    return System.from_dict(dict(format='flow-finite-system-r2',states=[state_id(p,k) for p,k in pairs],
        actions=actions,observation={state_id(p,k):list(p) for p,k in pairs},transitions=tr))

def main():
    out=BASE/'examples';out.mkdir(exist_ok=True)
    report={}
    for name,s,left,right in [('hidden_load',hidden_load(),'calm','loaded'),
                              ('response_bounded',response_system(),'012:39','012:40'),
                              ('response_safe',response_system(False),'012:39','012:40')]:
        (out/(name+'.json')).write_text(json.dumps(s.to_dict(),ensure_ascii=False,indent=2),encoding='utf-8')
        refined=s.refine()
        pc=dict(format='flow-partition-certificate-r2',system_sha256=s.digest(),blocks=refined['blocks'])
        (out/(name+'_partition.json')).write_text(json.dumps(pc,ensure_ascii=False,indent=2),encoding='utf-8')
        answer=s.distinguish(left,right)
        report[name]=dict(states=len(s.states),actions=len(s.actions),classes=len(set(refined['blocks'].values())),
                          refinement_stages=len(refined['stages']),obstruction=s.obstruction(),pair=[left,right],search=answer)
        if answer['status']=='distinguished':
            cert=witness_certificate(s,left,right,answer['word'])
            (out/(name+'_witness.json')).write_text(json.dumps(cert,ensure_ascii=False,indent=2),encoding='utf-8')
            assert verify_witness(s,cert)['valid']
    (BASE/'verification').mkdir(exist_ok=True)
    (BASE/'verification/examples.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(report,ensure_ascii=False))

if __name__=='__main__':main()
