"""Read an owned research notebook's metadata and source fingerprint only."""
import contextlib
import hashlib
import io
import json
import os
import sys
import tempfile
from pathlib import Path

REF = 'sumuji/research-phase-needle-20261031'
TITLE = 'research-phase-needle-20261031'

def quiet(fn, *args, **kwargs):
    with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
        return fn(*args, **kwargs)

def canonical(nb):
    if not isinstance(nb, dict) or nb.get('nbformat') != 4 or not isinstance(nb.get('cells'), list):
        raise ValueError('Invalid notebook')
    out=[]
    for c in nb['cells']:
        source=c.get('source')
        if isinstance(source,list) and all(isinstance(x,str) for x in source):source=''.join(source)
        if c.get('cell_type') not in ('markdown','code','raw') or not isinstance(source,str):
            raise ValueError('Invalid cell')
        out.append({'type':c['cell_type'],'source':source.replace('\r\n','\n')})
    return hashlib.sha256(json.dumps(out,ensure_ascii=False,separators=(',',':')).encode()).hexdigest(),len(out)

def main():
    if not os.environ.get('KAGGLE_API_TOKEN'):raise RuntimeError('Credential missing')
    from kaggle.api.kaggle_api_extended import KaggleApi
    api=KaggleApi();quiet(api.authenticate)
    with tempfile.TemporaryDirectory(prefix='phase-needle-probe-') as td:
        quiet(api.kernels_pull,REF+'/1',td,metadata=True,quiet=True)
        p=Path(td);meta=json.loads((p/'kernel-metadata.json').read_text(encoding='utf8'))
        name=meta.get('code_file')
        if not isinstance(name,str) or Path(name).name!=name:raise ValueError('Invalid source name')
        nb=json.loads((p/name).read_text(encoding='utf8'))
        digest,count=canonical(nb)
        state=quiet(api.kernels_status,REF+'/1')
        status=getattr(getattr(state,'status',None),'name',None)
        result={'ref_matches':meta.get('id')==REF,'title_matches':meta.get('title')==TITLE,
                'id_no':meta.get('id_no'),'private':meta.get('is_private') is True,
                'language':meta.get('language'),'kernel_type':meta.get('kernel_type'),
                'gpu':meta.get('enable_gpu'),'internet':meta.get('enable_internet'),
                'machine_shape':meta.get('machine_shape'),'source_sha256':digest,
                'cell_count':count,'version_specific_status':status}
        for key in ('dataset_sources','kernel_sources','competition_sources','model_sources'):
            val=meta.get(key);result[key+'_count']=len(val) if isinstance(val,list) else None
        print(json.dumps(result),flush=True)
        print('Read only; no source, output, or credentials printed.',flush=True)

if __name__=='__main__':
    try:main()
    except Exception:
        print('Probe failed; details suppressed',file=sys.stderr);sys.exit(1)
