"""Read-only Kaggle account/slug diagnostic; emits categories, never source."""
import contextlib,hashlib,io,json,os,sys,tempfile
from pathlib import Path
REF='sumuji/squares-v8-diagnostic-20261031-f93a2d'
ANCHOR='sumuji/dispatch-anchor-20261031-c9fa2c1d'
ANCHOR_ID=141798233
BASE_HASH='488c5213b6d5b19cdcfc7badc5397ba3064c23ba90081ca3d3f4751fe924501b'
def quiet(fn,*a,**kw):
    with contextlib.redirect_stdout(io.StringIO()),contextlib.redirect_stderr(io.StringIO()): return fn(*a,**kw)
def canonical(nb):
    cells=nb['cells']; items=[]
    for c in cells:
        s=c['source'];s=''.join(s) if isinstance(s,list) else s
        if s.startswith(('KAGGLE-DISPATCH-LEDGER-v2:','KAGGLE-DISPATCH-REQUEST-v1:')):continue
        items.append({'type':c['cell_type'],'source':s.replace('\r\n','\n')})
    return hashlib.sha256(json.dumps(items,ensure_ascii=False,separators=(',',':')).encode()).hexdigest()
def listings(api,mode):
    kw={'mine':True} if mode=='mine' else {'mine':True,'user':'sumuji'} if mode=='mine-user' else {'user':'sumuji'}
    token=None;seen=set();n=0;anchor_id=anchor_ref=anchor_suffix=target_id=target_ref=target_slug=0;pages=0
    for _ in range(100):
        response=quiet(api.kernels_list_with_response,page_size=100,page_token=token,**kw);items=response.kernels;t=response.next_page_token
        if not isinstance(items,list) or not isinstance(t,str):raise ValueError('unavailable listing')
        pages+=1
        for x in items:
            n+=1;ident=getattr(x,'id',None);ref=getattr(x,'ref','');slug=getattr(x,'slug','')
            anchor_id+=ident==ANCHOR_ID;anchor_ref+=ref==ANCHOR
            anchor_suffix+=isinstance(ref,str) and ref.rstrip('/').endswith('/'+ANCHOR)
            target_id+=ident==ANCHOR_ID and slug==REF.split('/')[-1]
            target_ref+=ref==REF or isinstance(ref,str) and ref.rstrip('/').endswith('/'+REF)
            target_slug+=slug==REF.split('/')[-1]
        if not t:return {'mode':mode,'pages':pages,'count':n,'known_anchor_id_matches':anchor_id,'known_anchor_ref_matches':anchor_ref,'known_anchor_ref_suffix_matches':anchor_suffix,'target_ref_matches':target_ref,'target_slug_matches':target_slug,'target_id_slug_matches':target_id}
        if t in seen:raise ValueError('pagination repeated')
        seen.add(t);token=t
    raise ValueError('pagination limit')
def pull(api,ref):
    with tempfile.TemporaryDirectory() as td:
        try:quiet(api.kernels_pull,ref,td,metadata=True,quiet=True)
        except Exception as e:
            r=getattr(e,'response',None);code=getattr(r,'status_code',None)
            return {'outcome':'http_error' if type(code) is int else 'error_suppressed','http_status':code if type(code) is int else None}
        p=Path(td);meta=json.loads((p/'kernel-metadata.json').read_text(encoding='utf-8'));name=meta.get('code_file')
        if not isinstance(name,str) or Path(name).name!=name:raise ValueError('unexpected source')
        nb=json.loads((p/name).read_text(encoding='utf-8'))
        return {'outcome':'readable','known_ref':meta.get('id')==ANCHOR,'known_id':meta.get('id_no')==ANCHOR_ID,
                'private':meta.get('is_private') is True,'cpu':meta.get('enable_gpu') is False,
                'internet_off':meta.get('enable_internet') is False,'no_inputs':all(meta.get(k)==[] for k in ('dataset_sources','competition_sources','kernel_sources','model_sources')),
                'known_base_hash_match':canonical(nb)==BASE_HASH,'cell_count':len(nb.get('cells',[]))}
def main():
    if not os.environ.get('KAGGLE_API_TOKEN'):raise ValueError('missing credential')
    from kaggle.api.kaggle_api_extended import KaggleApi
    api=KaggleApi();quiet(api.authenticate)
    for mode in ('mine','mine-user','user'):
        try:print(json.dumps(listings(api,mode)))
        except Exception:print(json.dumps({'mode':mode,'outcome':'unavailable'}))
    for label,ref in (('known_anchor',ANCHOR),('target',REF)):
        print(json.dumps({'target':label,**pull(api,ref)}))
    print('read-only probe complete')
if __name__=='__main__':
    try:main()
    except Exception:print('probe stopped; details suppressed',file=sys.stderr);sys.exit(1)
