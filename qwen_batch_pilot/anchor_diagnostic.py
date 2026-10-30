"""Read-only metadata fingerprint for the newly created private GPU-batch anchor."""
import contextlib
import hashlib
import io
import json
import os
import sys
import tempfile
from pathlib import Path

REF = 'sumuji/qwen-explicit-batch-20261031'


def quiet(fn, *args, **kwargs):
    with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
        return fn(*args, **kwargs)


def canonical(nb):
    if not isinstance(nb, dict) or nb.get('nbformat') != 4 or not isinstance(nb.get('cells'), list):
        raise ValueError('Invalid notebook')
    cells = []
    for cell in nb['cells']:
        source = cell.get('source')
        if isinstance(source, list) and all(isinstance(x, str) for x in source):
            source = ''.join(source)
        if cell.get('cell_type') not in ('code', 'markdown', 'raw') or not isinstance(source, str):
            raise ValueError('Invalid notebook cell')
        cells.append({'type': cell['cell_type'], 'source': source.replace('\r\n', '\n')})
    data = json.dumps(cells, ensure_ascii=False, separators=(',', ':')).encode()
    return hashlib.sha256(data).hexdigest(), len(cells)


def main():
    if not os.environ.get('KAGGLE_API_TOKEN'):
        raise RuntimeError('Missing credential')
    from kaggle.api.kaggle_api_extended import KaggleApi
    from kagglesdk.kernels.types.kernels_api_service import ApiGetKernelRequest
    api = KaggleApi()
    quiet(api.authenticate)
    request = ApiGetKernelRequest()
    request.user_name, request.kernel_slug = REF.split('/')
    with api.build_kaggle_client() as client:
        current = quiet(client.kernels.kernels_api_client.get_kernel, request)
    remote = getattr(current, 'metadata', None)
    with tempfile.TemporaryDirectory(prefix='qwen-anchor-readonly-') as td:
        path = Path(td)
        quiet(api.kernels_pull, REF + '/1', str(path), metadata=True, quiet=True)
        meta = json.loads((path / 'kernel-metadata.json').read_text(encoding='utf-8'))
        filename = meta.get('code_file')
        if not isinstance(filename, str) or Path(filename).name != filename:
            raise ValueError('Unexpected filename')
        nb = json.loads((path / filename).read_text(encoding='utf-8'))
        digest, count = canonical(nb)
        status = quiet(api.kernels_status, REF + '/1')
        state = getattr(getattr(status, 'status', None), 'name', None)
        output = {'ref_matches': meta.get('id') == REF, 'id_no': meta.get('id_no'),
                  'title_matches': meta.get('title') == 'qwen-explicit-batch-20261031',
                  'private': meta.get('is_private') is True,
                  'language': meta.get('language'), 'kernel_type': meta.get('kernel_type'),
                  'gpu': meta.get('enable_gpu'), 'internet': meta.get('enable_internet'),
                  'machine_shape': meta.get('machine_shape'), 'source_sha256': digest,
                  'cell_count': count, 'status': state,
                  'current_version': getattr(remote, 'current_version_number', None),
                  'current_id_matches': getattr(remote, 'id', None) == meta.get('id_no')}
        for key in ('dataset_sources', 'kernel_sources', 'competition_sources', 'model_sources'):
            value = meta.get(key)
            output[key + '_count'] = len(value) if isinstance(value, list) else None
        print(json.dumps(output), flush=True)
        print('Read-only; no source, questions, output, or credentials printed.', flush=True)


if __name__ == '__main__':
    try:
        main()
    except Exception as exc:
        name = type(exc).__name__
        if name not in {'HTTPError', 'ValueError', 'RuntimeError', 'OSError'}:
            name = 'other'
        status = getattr(getattr(exc, 'response', None), 'status_code', None)
        if type(status) is not int or not 100 <= status <= 599:
            status = None
        print(json.dumps({'outcome': 'error', 'exception_class': name, 'http_status': status}), file=sys.stderr)
        sys.exit(1)
