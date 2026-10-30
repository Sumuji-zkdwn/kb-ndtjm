"""One-shot creation of a private, offline Squares diagnostic notebook.

Never rerun a failed or ambiguous push. No competition submission. The Kaggle
preflight is not atomic with creation; concurrent manual writers are prohibited.
"""
import contextlib,hashlib,io,json,os,sys,tempfile,time
from pathlib import Path
from urllib.parse import urlsplit

ROOT=Path(__file__).resolve().parent
REF='sumuji/squares-v8-diagnostic-20261031-f93a2d'
TITLE='squares-v8-diagnostic-20261031-f93a2d'
ANCHOR='sumuji/dispatch-anchor-20261031-c9fa2c1d'
ANCHOR_ID=141798233
NOTEBOOK=ROOT/'squares_v8_diagnostic.ipynb'
EXPECTED_BYTES='c20d16112cb1a44668d2999435abf765a67acfa8b3aa052ae09f23b97618ad1c'
EXPECTED_CANONICAL='09e737183d9e560fa989115e927077a3003598eea325d5c261e635c371d12c22'
FIELDS=('invalid_tags','invalid_dataset_sources','invalid_competition_sources','invalid_kernel_sources','invalid_model_sources')
class Stop(Exception):pass

def quiet(fn,*args,**kwargs):
    with contextlib.redirect_stdout(io.StringIO()),contextlib.redirect_stderr(io.StringIO()):return fn(*args,**kwargs)

def canonical(nb):
    if not isinstance(nb,dict) or nb.get('nbformat')!=4 or not isinstance(nb.get('cells'),list):raise Stop('invalid notebook')
    result=[]
    for c in nb['cells']:
        source=c.get('source')
        if isinstance(source,list) and all(isinstance(x,str) for x in source):source=''.join(source)
        if c.get('cell_type') not in ('code','markdown','raw') or not isinstance(source,str):raise Stop('invalid cell')
        result.append({'type':c['cell_type'],'source':source.replace('\r\n','\n')})
    return hashlib.sha256(json.dumps(result,ensure_ascii=False,separators=(',',':')).encode()).hexdigest()

def validate_local():
    data=NOTEBOOK.read_bytes()
    if len(data)>200000 or hashlib.sha256(data).hexdigest()!=EXPECTED_BYTES:raise Stop('notebook bytes mismatch')
    nb=json.loads(data)
    if canonical(nb)!=EXPECTED_CANONICAL:raise Stop('notebook source mismatch')
    for c in nb['cells']:
        if c['cell_type']=='code' and (c.get('outputs')!=[] or c.get('execution_count') is not None):raise Stop('notebook has prior outputs')
    return data

def absence(api):
    # Exhaust authenticated profile pages, requiring an independently known
    # notebook identity to prove that the expected user's profile is visible.
    token=None;seen=set(); anchor=False
    for _ in range(100):
        result=quiet(api.kernels_list_with_response,mine=True,page_size=100,page_token=token)
        kernels=getattr(result,'kernels',None);next_token=getattr(result,'next_page_token',None)
        if not isinstance(kernels,list) or not isinstance(next_token,str):raise Stop('profile listing unavailable')
        for item in kernels:
            ref=getattr(item,'ref',None);slug=getattr(item,'slug',None);ident=getattr(item,'id',None)
            if not isinstance(ref,str) or not isinstance(slug,str) or type(ident) is not int:raise Stop('profile identity unavailable')
            if ref==REF or slug==TITLE:raise Stop('notebook name already exists')
            if ref==ANCHOR and ident==ANCHOR_ID:anchor=True
        if not next_token:
            if not anchor:raise Stop('expected account anchor absent from profile listing')
            return
        if next_token in seen:raise Stop('profile pagination repeated')
        seen.add(next_token);token=next_token
    raise Stop('profile pagination limit')

def trusted_ref(ref):
    if ref in {REF,'/code/'+REF}:return True
    if not isinstance(ref,str):return False
    p=urlsplit(ref)
    return p.scheme=='https' and p.netloc in ('www.kaggle.com','kaggle.com') and not p.query and not p.fragment and p.path in ('/'+REF,'/code/'+REF)

def receipt(r):
    if not r or getattr(r,'error',None):raise Stop('push response ambiguous')
    if any(not isinstance(getattr(r,f,None),list) or getattr(r,f) for f in FIELDS):raise Stop('push response input errors')
    ident=getattr(r,'kernel_id',None);version=getattr(r,'version_number',None)
    if not trusted_ref(getattr(r,'ref',None)) or type(ident) is not int or ident<1 or version!=1:raise Stop('push receipt identity or version ambiguous')
    return ident,version

def state(api,ref):
    s=quiet(api.kernels_status,ref)
    name=getattr(getattr(s,'status',None),'name',None)
    if name not in ('QUEUED','RUNNING','COMPLETE','ERROR','CANCEL_REQUESTED','CANCEL_ACKNOWLEDGED','NEW_SCRIPT'):raise Stop('unknown execution state')
    return name

def pull_verify(api,ident,version):
    with tempfile.TemporaryDirectory(prefix='squares-read-') as td:
        quiet(api.kernels_pull,f'{REF}/{version}',td,metadata=True,quiet=True)
        folder=Path(td);meta=json.loads((folder/'kernel-metadata.json').read_text(encoding='utf-8'))
        if (meta.get('id')!=REF or meta.get('id_no')!=ident or meta.get('title')!=TITLE or
            meta.get('is_private') is not True or meta.get('language')!='python' or meta.get('kernel_type')!='notebook' or
            meta.get('enable_gpu') is not False or meta.get('enable_tpu') not in (False,None) or meta.get('enable_internet') is not False):raise Stop('saved notebook metadata mismatch')
        if any(meta.get(k)!=[] for k in ('dataset_sources','kernel_sources','competition_sources','model_sources')):raise Stop('saved notebook has unexpected inputs')
        name=meta.get('code_file')
        if not isinstance(name,str) or Path(name).name!=name:raise Stop('source name invalid')
        nb=json.loads((folder/name).read_text(encoding='utf-8'))
        if canonical(nb)!=EXPECTED_CANONICAL:raise Stop('saved notebook source mismatch')

def run(api,sleep=time.sleep,timeout=1200):
    if os.environ.get('GITHUB_RUN_ATTEMPT')!='1':raise Stop('retry prohibited')
    request=json.loads((ROOT/'request.json').read_text(encoding='utf-8'))
    if request!={'id':'squares-v8-20261031-create-f93a2d','kind':'one-shot-create'}:raise Stop('unexpected request')
    data=validate_local();absence(api);absence(api)
    meta={'id':REF,'title':TITLE,'code_file':'job.ipynb','language':'python','kernel_type':'notebook','is_private':True,'enable_gpu':False,'enable_tpu':False,'enable_internet':False,'dataset_sources':[],'competition_sources':[],'kernel_sources':[],'model_sources':[]}
    with tempfile.TemporaryDirectory(prefix='squares-create-') as td:
        p=Path(td);(p/'job.ipynb').write_bytes(data);(p/'kernel-metadata.json').write_text(json.dumps(meta),encoding='utf-8')
        response=quiet(api.kernels_push,str(p))
    ident,version=receipt(response)
    print(json.dumps({'accepted_version':version,'notebook_id':ident,'source_hash':EXPECTED_CANONICAL,'status':'pending'}),flush=True)
    # Do not wait for code execution to complete before checking requested privacy.
    pull_verify(api,ident,version)
    end=time.monotonic()+timeout
    while time.monotonic()<end:
        status=state(api,f'{REF}/{version}')
        if status=='COMPLETE':
            pull_verify(api,ident,version)
            print(json.dumps({'version':version,'version_specific_status':status,'source_verified':True,'metadata_verified':True}),flush=True);return ident,version
        if status in ('ERROR','CANCEL_REQUESTED','CANCEL_ACKNOWLEDGED'):raise Stop('Kaggle version did not complete')
        sleep(20)
    raise Stop('timed out; inspect before retry')

def main():
    if not os.environ.get('KAGGLE_API_TOKEN'):raise Stop('credential unavailable')
    from kaggle.api.kaggle_api_extended import KaggleApi
    api=KaggleApi();quiet(api.authenticate);run(api)
if __name__=='__main__':
    try:main()
    except Exception as e:
        print('Creation stopped: '+(str(e) if isinstance(e,Stop) else 'details suppressed; inspect before retry'),file=sys.stderr);sys.exit(1)
