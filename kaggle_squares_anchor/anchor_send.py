"""Replace only the dedicated synthetic anchor's current source with one
private Squares diagnostic version. Kaggle retains earlier saved versions.
Refuse ambiguous states and do not retry a push. This is not a new notebook.
"""
import copy,hashlib,json,os,sys,tempfile,time
from pathlib import Path
import router
ROOT=Path(__file__).resolve().parent
TARGET={'ref':'sumuji/dispatch-anchor-20261031-c9fa2c1d','id':141798233,'title':'dispatch-anchor-20261031-c9fa2c1d','hash':'488c5213b6d5b19cdcfc7badc5397ba3064c23ba90081ca3d3f4751fe924501b','gpu':False,'models':[]}
REQ={'id':'squares-diagnostic-20261031-a1','previous_id':'receipt-probe-20261031-d5','kind':'diagnostic'}
EXPECTED_FILE='c20d16112cb1a44668d2999435abf765a67acfa8b3aa052ae09f23b97618ad1c'
EXPECTED_CANONICAL='09e737183d9e560fa989115e927077a3003598eea325d5c261e635c371d12c22'
class Stop(Exception):pass
def local_nb():
    b=(ROOT/'squares_v8_diagnostic.ipynb').read_bytes()
    if len(b)>200000 or hashlib.sha256(b).hexdigest()!=EXPECTED_FILE:raise Stop('local diagnostic bytes mismatch')
    nb=json.loads(b)
    if router.canonical(nb)[0]!=EXPECTED_CANONICAL:raise Stop('diagnostic source mismatch')
    if any(c['cell_type']=='code' and (c.get('outputs')!=[] or c.get('execution_count') is not None) for c in nb['cells']):raise Stop('local notebook contains outputs')
    return nb
def check_settings(meta):
    if meta.get('enable_internet') is not False:raise Stop('anchor internet is not disabled')
    # router.pull has already verified identity, title, privacy, CPU, no inputs.
def prepare_anchor(meta,nb,new):
    check_settings(meta)
    prepared,digest,ledger=router.prepare(nb,REQ,TARGET)
    if prepared is None:raise Stop('request already present; do not push again')
    if digest!=TARGET['hash'] or len(ledger)<2 or ledger[-2:]!=[REQ['previous_id'],REQ['id']]:raise Stop('anchor history mismatch')
    result=copy.deepcopy(new);result['cells'].append(prepared['cells'][-1])
    return result,ledger
def verify_new(meta,nb,ledger):
    check_settings(meta)
    cells=nb.get('cells',[])
    if not cells or cells[-1].get('cell_type')!='markdown':raise Stop('new marker missing')
    s=router.source(cells[-1])
    if s!=router.V2+json.dumps(ledger,separators=(',',':'))+'\n':raise Stop('new ledger mismatch')
    trimmed=copy.deepcopy(nb);trimmed['cells']=cells[:-1]
    if router.canonical(trimmed)[0]!=EXPECTED_CANONICAL:raise Stop('new source mismatch')
def run(api,sleep=time.sleep,timeout=1200):
    if os.environ.get('GITHUB_RUN_ATTEMPT')!='1':raise Stop('retry prohibited')
    req=json.loads((ROOT/'request.json').read_text(encoding='utf-8'))
    if req!=REQ:raise Stop('request mismatch')
    new=local_nb()
    if router.state(api,TARGET['ref'])!='COMPLETE':raise Stop('current anchor is not complete')
    meta1,nb1=router.pull(api,TARGET);job,ledger=prepare_anchor(meta1,nb1,new)
    meta2,nb2=router.pull(api,TARGET);job2,ledger2=prepare_anchor(meta2,nb2,new)
    keys=('id','id_no','title','is_private','enable_gpu','enable_tpu','enable_internet','dataset_sources','competition_sources','kernel_sources','model_sources','machine_shape','docker_image','keywords')
    if ledger!=ledger2 or job!=job2 or any(meta1.get(k)!=meta2.get(k) for k in keys) or router.state(api,TARGET['ref'])!='COMPLETE':raise Stop('anchor changed between checks')
    meta={'id':TARGET['ref'],'id_no':TARGET['id'],'title':TARGET['title'],'code_file':'job.ipynb','language':'python','kernel_type':'notebook','is_private':True,'enable_gpu':False,'enable_tpu':False,'enable_internet':False,'keywords':meta1['keywords'],'dataset_sources':[],'competition_sources':[],'kernel_sources':[],'model_sources':[]}
    if meta1.get('docker_image'):meta['docker_image']=meta1['docker_image']
    with tempfile.TemporaryDirectory(prefix='squares-anchor-') as td:
        p=Path(td);(p/'job.ipynb').write_text(json.dumps(job,ensure_ascii=False),encoding='utf-8');(p/'kernel-metadata.json').write_text(json.dumps(meta),encoding='utf-8')
        response=router.quiet_call(api.kernels_push,str(p))
    version=router.check_receipt(response,TARGET)
    print(json.dumps({'notebook_id':TARGET['id'],'accepted_version':version,'source_hash':EXPECTED_CANONICAL,'status':'pending'}),flush=True)
    meta3,nb3=router.pull(api,TARGET,f"{TARGET['ref']}/{version}");verify_new(meta3,nb3,ledger)
    end=time.monotonic()+timeout
    while time.monotonic()<end:
        status=router.state(api,f"{TARGET['ref']}/{version}")
        if status=='COMPLETE':
            meta4,nb4=router.pull(api,TARGET,f"{TARGET['ref']}/{version}");verify_new(meta4,nb4,ledger)
            print(json.dumps({'version':version,'version_specific_status':'COMPLETE','metadata_source_ledger_verified':True}),flush=True);return version
        if status in ('ERROR','CANCEL_REQUESTED','CANCEL_ACKNOWLEDGED'):raise Stop('Kaggle version failed or cancelled')
        sleep(20)
    raise Stop('timed out; inspect version before any retry')
def main():
    if not os.environ.get('KAGGLE_API_TOKEN'):raise Stop('credential unavailable')
    from kaggle.api.kaggle_api_extended import KaggleApi
    api=KaggleApi();router.quiet_call(api.authenticate);run(api)
if __name__=='__main__':
    try:main()
    except Exception as e:
        print('Anchor diagnostic stopped: '+(str(e) if isinstance(e,(Stop,router.RouterError)) else 'details suppressed; inspect before retry'),file=sys.stderr);sys.exit(1)
