"""One-time, explicit, synthetic bridge test; never automatically rerun."""
import json, os, sys
from pathlib import Path
import bridge

EXPECTED = '738b2b39e14f67b7955364a8688c60a87084e5d62182577ec7041e2df0c6c906'
RUN_ID = 'qwen-bridge-synthetic-20261031-1'

def main():
    if os.environ.get('GITHUB_RUN_ATTEMPT') != '1': raise bridge.Stop('Re-run disabled')
    root=Path(__file__).resolve().parent
    path=root/'synthetic-input.jsonl'
    rows=[{'id':'fictional-1','prompt':'Synthetic fixed tests passed. Explain their limited scope in two sentences.'},
          {'id':'fictional-2','prompt':'Explain why a finite numerical test is not a general proof.'}]
    path.write_text(''.join(json.dumps(r,ensure_ascii=True)+'\n' for r in rows),encoding='ascii')
    out=root/'synthetic-output';out.mkdir(exist_ok=False)
    from kaggle.api.kaggle_api_extended import KaggleApi
    api=KaggleApi();bridge.quiet(api.authenticate)
    if bridge.head(api)!=2: raise bridge.Stop('Expected original version 2; inspect before retry')
    bridge.perform(api,path,out,RUN_ID,'none',EXPECTED)

if __name__=='__main__':
    try:main()
    except Exception as exc:
        print('Synthetic test stopped:',str(exc) if isinstance(exc,bridge.Stop) else 'remote/local error',file=sys.stderr)
        sys.exit(1)
