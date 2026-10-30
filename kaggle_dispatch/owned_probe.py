"""Read-only diagnostic for two already-owned private Kaggle notebooks.

Does not print source, credentials, notebook outputs, prompts, or metadata values
other than numeric ids, hashes, booleans, and small counts. No push or submit.
"""
import hashlib
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent
TARGETS = {
    'research': {'ref': 'sumuji/dalcia-ideas-43-kaggle', 'gpu': False,
                 'model_sources': []},
    'qwen': {'ref': 'sumuji/qwen25-7b-kaggle-smoke', 'gpu': True,
             'model_sources': ['qwen-lm/qwen2.5/transformers/7b-instruct/1']},
}


class ProbeError(Exception):
    pass


def canonical(notebook):
    if not isinstance(notebook, dict) or notebook.get('nbformat') != 4:
        raise ProbeError('Invalid notebook format')
    cells = notebook.get('cells')
    if not isinstance(cells, list) or len(cells) > 200:
        raise ProbeError('Invalid cell count')
    result = []
    for cell in cells:
        if not isinstance(cell, dict) or cell.get('cell_type') not in ('code', 'markdown', 'raw'):
            raise ProbeError('Invalid cell type')
        source = cell.get('source')
        if isinstance(source, list) and all(isinstance(x, str) for x in source):
            source = ''.join(source)
        if not isinstance(source, str) or len(source) > 1_500_000:
            raise ProbeError('Invalid cell source')
        result.append({'type': cell['cell_type'], 'source': source.replace('\r\n', '\n')})
    blob = json.dumps(result, ensure_ascii=False, separators=(',', ':')).encode('utf-8')
    return hashlib.sha256(blob).hexdigest(), len(result)


def summary(kind, meta, notebook):
    target = TARGETS[kind]
    if not isinstance(meta, dict) or meta.get('id') != target['ref'] or meta.get('is_private') is not True:
        raise ProbeError('Expected target identity or private status not confirmed')
    number = meta.get('id_no')
    if type(number) is not int or number < 1:
        raise ProbeError('Numeric notebook identity unavailable')
    if meta.get('language') != 'python' or meta.get('kernel_type') != 'notebook':
        raise ProbeError('Unexpected notebook type')
    fields = ('dataset_sources', 'competition_sources', 'kernel_sources', 'model_sources')
    if any(not isinstance(meta.get(k), list) for k in fields):
        raise ProbeError('Notebook source lists unavailable')
    digest, cell_count = canonical(notebook)
    return {'kind': kind, 'id_no': number, 'private': True,
            'cell_count': cell_count, 'canonical_cell_sha256': digest,
            'gpu_setting_matches': meta.get('enable_gpu') is target['gpu'],
            'competition_empty': not meta['competition_sources'],
            'dataset_empty': not meta['dataset_sources'],
            'kernel_input_empty': not meta['kernel_sources'],
            'model_sources_match': meta['model_sources'] == target['model_sources'],
            'internet_enabled': meta.get('enable_internet') is True,
            'remote_run_status': 'not tested by this probe'}


def pull(kind):
    with tempfile.TemporaryDirectory(prefix='owned-kaggle-probe-') as tmp:
        folder = Path(tmp)
        args = [sys.executable, '-m', 'kaggle', 'kernels', 'pull', TARGETS[kind]['ref'],
                '-p', str(folder), '-m']
        proc = subprocess.run(args, text=True, capture_output=True, timeout=120, check=False)
        if proc.returncode != 0:
            raise ProbeError('Kaggle pull failed; body suppressed')
        meta = json.loads((folder / 'kernel-metadata.json').read_text(encoding='utf-8'))
        source = meta.get('code_file')
        if not isinstance(source, str) or Path(source).name != source:
            raise ProbeError('Unexpected notebook filename')
        path = folder / source
        if path.stat().st_size > 2_000_000:
            raise ProbeError('Notebook exceeds diagnostic size limit')
        nb = json.loads(path.read_text(encoding='utf-8'))
        return summary(kind, meta, nb)


def main():
    request = json.loads((ROOT / 'request.json').read_text(encoding='utf-8'))
    if request != {'id': 'owned-probe-20261031-d1', 'kind': 'owned-read-only'}:
        raise ProbeError('Unexpected diagnostic request')
    if not os.environ.get('KAGGLE_API_TOKEN'):
        raise ProbeError('Kaggle credential unavailable')
    for kind in TARGETS:
        try:
            print(json.dumps(pull(kind), sort_keys=True))
        except (OSError, ValueError, subprocess.TimeoutExpired, ProbeError):
            print(json.dumps({'kind': kind, 'status': 'probe_failed', 'detail': 'suppressed'}))
            raise ProbeError('At least one read-only probe failed; no mutation attempted')
    print('Read-only probes finished; no Kaggle notebook update attempted')


if __name__ == '__main__':
    try:
        main()
    except (OSError, ValueError, subprocess.TimeoutExpired, ProbeError):
        print('Read-only diagnostic stopped; no mutation attempted', file=sys.stderr)
        sys.exit(1)
