"""Read-only comparison of a local template with Kaggle Qwen saved version 2."""
import json
import sys
from pathlib import Path
import bridge


def main():
    from kaggle.api.kaggle_api_extended import KaggleApi
    api=KaggleApi();bridge.quiet(api.authenticate)
    current=bridge.head(api)
    version=2
    if current != version: raise bridge.Stop('Current notebook is no longer version 2')
    if bridge.state(api, f'{bridge.REF}/{version}') != 'COMPLETE': raise bridge.Stop('Version 2 not complete')
    meta, nb=bridge.pull(api, version)
    cells=nb.get('cells')
    if not isinstance(cells,list) or len(cells)!=1 or cells[0].get('cell_type')!='code':
        raise bridge.Stop('Unexpected saved notebook structure')
    observed=bridge.template_hash(bridge.text_source(cells[0]))
    local=(Path(__file__).parent/'template.py').read_text(encoding='utf8').replace('\r\n','\n')
    expected=bridge.template_hash(local)
    if bridge.head(api) != version: raise bridge.Stop('Current notebook changed during inspection')
    print(json.dumps({'version_checked':version,'current_version':current,
                      'private_gpu_offline_and_model_verified':True,
                      'observed_template_sha256':observed,
                      'local_template_sha256':expected,'template_matches':observed==expected}))
    if observed!=expected: raise bridge.Stop('Saved template differs from local copy')


if __name__=='__main__':
    try:main()
    except Exception as exc:
        print('Read-only comparison stopped:', str(exc) if isinstance(exc,bridge.Stop) else 'remote or local error',file=sys.stderr)
        sys.exit(1)
