"""Run one pre-verified, owned private research notebook as a new version.

Read original source only from Kaggle, never from this repository. This is an
explicit-request trigger, not automatic interception of local applications.
"""
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path
from owned_probe import canonical

ROOT = Path(__file__).resolve().parent
REF = 'sumuji/dalcia-ideas-43-kaggle'
TITLE = 'dalcia_ideas_43_kaggle'
EXPECTED_ID = 141796740
EXPECTED_BASE_SHA256 = 'b75ee0f50e03854dca11e51f5b6b4bc4f011b1fff41f67d085ca1cf26f0f00f6'
MARKER_PREFIX = 'KAGGLE-DISPATCH-REQUEST-v1:'
ID_PATTERN = re.compile(r'^[a-z0-9][a-z0-9-]{5,39}$')


class RunError(Exception):
    pass


def read_request(req):
    if not isinstance(req, dict) or set(req) != {'id', 'kind', 'previous_id'}:
        raise RunError('Invalid request fields')
    if req.get('kind') != 'ideas-43-rerun':
        raise RunError('Only registered research rerun is allowed')
    if not isinstance(req.get('id'), str) or not ID_PATTERN.fullmatch(req['id']):
        raise RunError('Invalid request id')
    previous = req.get('previous_id')
    if previous != 'none' and (not isinstance(previous, str) or not ID_PATTERN.fullmatch(previous)):
        raise RunError('Invalid previous request id')
    if req['id'] == previous:
        raise RunError('Request ids must differ')
    return req


def check_metadata(meta):
    if (meta.get('id') != REF or meta.get('id_no') != EXPECTED_ID or EXPECTED_ID < 1
        or meta.get('is_private') is not True):
        raise RunError('Notebook identity or privacy mismatch')
    if meta.get('title') != TITLE or meta.get('language') != 'python' or meta.get('kernel_type') != 'notebook':
        raise RunError('Notebook type or title mismatch')
    if meta.get('enable_gpu') is not False:
        raise RunError('Unexpected GPU setting')
    for field in ('dataset_sources', 'kernel_sources', 'competition_sources', 'model_sources'):
        if meta.get(field) != []:
            raise RunError('Unexpected notebook inputs')


def prepare(notebook, req):
    if not isinstance(notebook, dict) or not isinstance(notebook.get('cells'), list):
        raise RunError('Invalid notebook')
    # Deep copy; outputs are removed from the new input version. Existing saved
    # Kaggle versions and outputs are untouched. Original cell sources retained.
    copy = json.loads(json.dumps(notebook))
    cells = copy['cells']
    marker = 'none'
    all_markers = []
    for i, cell in enumerate(cells):
        src = cell.get('source', '')
        if isinstance(src, list) and all(isinstance(x, str) for x in src):
            src = ''.join(src)
        if not isinstance(src, str):
            raise RunError('Invalid source')
        if src.startswith(MARKER_PREFIX):
            all_markers.append((i, src))
        if cell.get('cell_type') == 'code':
            cell['outputs'] = []
            cell['execution_count'] = None
    if all_markers:
        if len(all_markers) != 1 or all_markers[0][0] != len(cells)-1 or cells[-1].get('cell_type') != 'markdown':
            raise RunError('Unexpected dispatch markers')
        marker_text = all_markers[0][1]
        marker = marker_text[len(MARKER_PREFIX):].strip()
        if not ID_PATTERN.fullmatch(marker) or marker_text != MARKER_PREFIX + marker + '\n':
            raise RunError('Invalid dispatch marker')
        cells.pop()
    digest, count = canonical(copy)
    if digest != EXPECTED_BASE_SHA256 or not re.fullmatch(r'[0-9a-f]{64}', EXPECTED_BASE_SHA256):
        raise RunError('Research source fingerprint mismatch')
    if marker == req['id']:
        return None, digest, marker, count
    if marker != req['previous_id']:
        raise RunError('Previous request marker mismatch')
    marker_id = hashlib.sha256(req['id'].encode()).hexdigest()[:12]
    cells.append({'cell_type': 'markdown', 'metadata': {}, 'id': marker_id,
                  'source': MARKER_PREFIX + req['id'] + '\n'})
    return copy, digest, marker, count


def call(args):
    p = subprocess.run([sys.executable, '-m', 'kaggle', *args], capture_output=True,
                       text=True, timeout=120, check=False)
    return p.returncode, p.stdout, p.stderr


def pull():
    with tempfile.TemporaryDirectory(prefix='private-source-') as tmp:
        folder = Path(tmp)
        code, _, _ = call(['kernels', 'pull', REF, '-p', str(folder), '-m'])
        if code:
            raise RunError('Cannot read notebook; response suppressed')
        meta = json.loads((folder / 'kernel-metadata.json').read_text(encoding='utf-8'))
        check_metadata(meta)
        source = meta.get('code_file')
        if not isinstance(source, str) or Path(source).name != source:
            raise RunError('Unexpected source filename')
        p = folder / source
        if p.stat().st_size > 2_000_000:
            raise RunError('Notebook exceeds size bound')
        return meta, json.loads(p.read_text(encoding='utf-8'))


def main():
    req = read_request(json.loads((ROOT / 'request.json').read_text(encoding='utf-8')))
    if not os.environ.get('KAGGLE_API_TOKEN'):
        raise RunError('Kaggle credential unavailable')
    # Do not auto-retry an ambiguous upload on GitHub Actions re-runs.
    if os.environ.get('GITHUB_RUN_ATTEMPT') != '1':
        raise RunError('Automatic retries disabled; inspect Kaggle first')
    code, out, _ = call(['kernels', 'status', REF])
    if code or not re.search(r'\bcomplete\b', out, re.I):
        raise RunError('Current notebook status is not confirmed complete')
    _, notebook = pull()
    prepared, digest, prior, count = prepare(notebook, req)
    if prepared is None:
        print(json.dumps({'request': req['id'], 'result': 'already_present_no_push'}))
        return
    # Independent second pull catches ordinary edits, though it is not atomic.
    _, reloaded = pull()
    _, second_digest, second_prior, second_count = prepare(reloaded, req)
    if (digest, prior, count) != (second_digest, second_prior, second_count):
        raise RunError('Notebook changed during preflight')
    meta = {'id': REF, 'id_no': EXPECTED_ID, 'title': TITLE, 'code_file': 'job.ipynb',
            'language': 'python', 'kernel_type': 'notebook', 'is_private': True,
            'enable_gpu': False, 'enable_internet': False,
            'dataset_sources': [], 'competition_sources': [], 'kernel_sources': [], 'model_sources': []}
    with tempfile.TemporaryDirectory(prefix='private-research-run-') as tmp:
        folder = Path(tmp)
        (folder / 'job.ipynb').write_text(json.dumps(prepared, ensure_ascii=False), encoding='utf-8')
        (folder / 'kernel-metadata.json').write_text(json.dumps(meta), encoding='utf-8')
        code, out, _ = call(['kernels', 'push', '-p', str(folder)])
    receipt = re.search(r'(?m)^Kernel version ([1-9][0-9]*) successfully pushed\.', out)
    if code or not receipt:
        raise RunError('Push result uncertain; inspect Kaggle; no automatic retry')
    print(json.dumps({'request': req['id'], 'kind': req['kind'], 'accepted_version': int(receipt.group(1)),
                      'base_source_sha256': digest, 'private_requested': True,
                      'completion': 'not verified; inspect exact Kaggle version'}))


if __name__ == '__main__':
    try:
        main()
    except (RunError, OSError, ValueError, subprocess.TimeoutExpired) as exc:
        # Only application-generated fixed error messages should reach logs.
        if isinstance(exc, RunError):
            print('Research dispatch stopped: ' + str(exc), file=sys.stderr)
        else:
            print('Research dispatch stopped; details suppressed', file=sys.stderr)
        sys.exit(1)
