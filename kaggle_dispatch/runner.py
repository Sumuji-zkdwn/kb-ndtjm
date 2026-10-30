"""One-time synthetic update of a pre-existing, private Kaggle anchor.

Never submits to a competition. A dedicated anchor must first be created and
verified separately. This cannot provide atomic compare-and-swap against other
writers; do not allow another writer to touch the anchor during the pilot.
"""
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent
ANCHOR = "sumuji/dispatch-anchor-20261031-c9fa2c1d"
ANCHOR_TITLE = "dispatch-anchor-20261031-c9fa2c1d"
SENTINEL = ('# Anchor sentinel KA-DISPATCH-ANCHOR-20261031-C9FA2C1D\n'
            'print("Synthetic anchor only; not research data")\n')
NOTEBOOK = ROOT / 'notebooks' / 'synthetic_smoke.ipynb'
REQ_FIELDS = {'id', 'kind', 'source_sha256'}


class PilotError(Exception):
    pass


def validate_request(req):
    if not isinstance(req, dict) or set(req) != REQ_FIELDS:
        raise PilotError('Unexpected request fields')
    if req.get('kind') != 'synthetic-smoke':
        raise PilotError('Only synthetic-smoke is allowed')
    if not isinstance(req.get('id'), str) or not re.fullmatch(r'[a-z0-9][a-z0-9-]{5,29}', req['id']):
        raise PilotError('Invalid job id')
    if not isinstance(req.get('source_sha256'), str) or not re.fullmatch(r'[0-9a-f]{64}', req['source_sha256']):
        raise PilotError('Invalid source digest')
    data = NOTEBOOK.read_bytes()
    if len(data) > 50000 or hashlib.sha256(data).hexdigest() != req['source_sha256']:
        raise PilotError('Synthetic source digest or size mismatch')
    nb = json.loads(data)
    if nb.get('nbformat') != 4 or not isinstance(nb.get('cells'), list):
        raise PilotError('Invalid synthetic notebook')
    return data


def validate_anchor(metadata, notebook):
    if metadata.get('id') != ANCHOR or metadata.get('is_private') is not True:
        raise PilotError('Anchor identity or privacy mismatch')
    anchor_id = metadata.get('id_no')
    if type(anchor_id) is not int or anchor_id <= 0:
        raise PilotError('Anchor numeric identity missing')
    if metadata.get('title') != ANCHOR_TITLE:
        raise PilotError('Anchor title mismatch')
    if metadata.get('language') != 'python' or metadata.get('kernel_type') != 'notebook':
        raise PilotError('Anchor type mismatch')
    for field in ('dataset_sources', 'kernel_sources', 'competition_sources', 'model_sources'):
        if metadata.get(field) != []:
            raise PilotError('Anchor must not have inputs')
    if not isinstance(notebook, dict) or notebook.get('nbformat') != 4:
        raise PilotError('Anchor notebook format mismatch')
    cells = notebook.get('cells')
    if not isinstance(cells, list) or len(cells) != 1 or cells[0].get('cell_type') != 'code':
        raise PilotError('Anchor must contain one sentinel code cell')
    source = cells[0].get('source')
    if isinstance(source, list) and all(isinstance(line, str) for line in source):
        source = ''.join(source)
    if source != SENTINEL:
        raise PilotError('Anchor sentinel missing or changed; no update attempted')
    return anchor_id


def call(args, timeout=120):
    # Never write remote response bodies to logs; they can contain credentials.
    p = subprocess.run([sys.executable, '-m', 'kaggle', *args], capture_output=True,
                       text=True, timeout=timeout, check=False)
    return p.returncode, p.stdout, p.stderr


def status(code, stdout):
    if code != 0:
        return 'unknown'
    data = stdout.lower()
    for value in ('complete', 'error', 'cancelacknowledged', 'cancelled', 'running', 'queued', 'pending'):
        if re.search(r'\b' + value + r'\b', data):
            return value
    return 'unknown'


def pull_anchor():
    with tempfile.TemporaryDirectory(prefix='anchor-read-') as td:
        folder = Path(td)
        code, _, _ = call(['kernels', 'pull', ANCHOR, '-p', str(folder), '-m'])
        if code != 0:
            raise PilotError('Cannot read anchor and metadata')
        meta = json.loads((folder / 'kernel-metadata.json').read_text(encoding='utf-8'))
        code_file = meta.get('code_file')
        if not isinstance(code_file, str) or Path(code_file).name != code_file:
            raise PilotError('Unexpected anchor source name')
        nb = json.loads((folder / code_file).read_text(encoding='utf-8'))
        return validate_anchor(meta, nb)


def main():
    request = json.loads((ROOT / 'request.json').read_text(encoding='utf-8'))
    data = validate_request(request)
    if not os.environ.get('KAGGLE_API_TOKEN'):
        raise PilotError('Kaggle credential unavailable')
    code, out, _ = call(['kernels', 'status', ANCHOR])
    current = status(code, out)
    if current != 'complete':
        raise PilotError('Anchor is not complete or status is unknown')
    anchor_id = pull_anchor()
    print(json.dumps({'anchor': ANCHOR, 'anchor_id': anchor_id, 'status': current,
                      'sentinel_verified': True, 'request_id': request['id']}))
    if os.environ.get('KAGGLE_DIAGNOSTIC_ONLY') == '1':
        print('Diagnostic-only mode: no notebook update attempted')
        return
    # Re-read immediately before push; other writers can still race this check.
    if pull_anchor() != anchor_id:
        raise PilotError('Anchor changed since preflight')
    code, out, _ = call(['kernels', 'status', ANCHOR])
    if status(code, out) != 'complete':
        raise PilotError('Anchor no longer complete')
    meta = {'id': ANCHOR, 'id_no': anchor_id, 'title': ANCHOR_TITLE,
            'code_file': 'job.ipynb', 'language': 'python', 'kernel_type': 'notebook',
            'is_private': True, 'enable_gpu': False, 'enable_internet': False,
            'dataset_sources': [], 'competition_sources': [], 'kernel_sources': [], 'model_sources': []}
    with tempfile.TemporaryDirectory(prefix='anchor-push-') as td:
        folder = Path(td)
        (folder / 'job.ipynb').write_bytes(data)
        (folder / 'kernel-metadata.json').write_text(json.dumps(meta), encoding='utf-8')
        code, push_out, _ = call(['kernels', 'push', '-p', str(folder)])
    if code != 0:
        raise PilotError('Update outcome is uncertain; inspect anchor before any retry')
    # CLI 2.2.5 may print an error while exiting 0. Do not leak raw output.
    match = re.search(r'(?m)^Kernel version ([1-9][0-9]*) successfully pushed\.', push_out)
    if not match:
        raise PilotError('No unambiguous push receipt; inspect anchor before any retry')
    version = int(match.group(1))
    print(json.dumps({'anchor': ANCHOR, 'push': 'accepted', 'version': version,
                      'privacy_requested': True,
                      'remote_run': 'not independently verified; inspect exact Kaggle version'}))


if __name__ == '__main__':
    try:
        main()
    except (PilotError, OSError, subprocess.TimeoutExpired, json.JSONDecodeError, ValueError) as e:
        print('Pilot stopped: ' + str(e), file=sys.stderr)
        sys.exit(1)
