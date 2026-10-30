"""One-time synthetic pilot. Refuses to overwrite existing Kaggle objects.

No prompts, answers, raw API responses or credentials are printed. A failure may
leave a created private dataset/notebook; inspect before attempting recovery.
"""
import contextlib
import hashlib
import io
import json
import os
import shutil
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DATASET = 'sumuji/qwen-batch-synthetic-20261031'
KERNEL = 'sumuji/qwen-batch-private-pilot-20261031'
MODEL = 'qwen-lm/qwen2.5/Transformers/7b-instruct/1'
INPUT_HASH = '5e4b578056dbe80f626a82c1581c9d6b4bfb5e044ed7d375b52206ff01d8b3f0'
CODE_HASH = 'b3611038038da721610d9f919f98cf9b732e8c8724b125f204b5e2fda56d231d'


class PilotError(Exception):
    pass


def canonical(nb):
    if nb.get('nbformat') != 4 or len(nb.get('cells', [])) != 2:
        raise PilotError('Unexpected notebook structure')
    cells = []
    for c in nb['cells']:
        s = c.get('source')
        if isinstance(s, list) and all(isinstance(x, str) for x in s):
            s = ''.join(s)
        if c.get('cell_type') not in ('code', 'markdown') or not isinstance(s, str):
            raise PilotError('Unexpected cell')
        cells.append({'type': c['cell_type'], 'source': s.replace('\r\n', '\n')})
    return hashlib.sha256(json.dumps(cells, ensure_ascii=False, separators=(',', ':')).encode()).hexdigest()


def quiet(fn, *args, **kwargs):
    with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
        return fn(*args, **kwargs)


def is_missing(getter):
    from requests.exceptions import HTTPError
    try:
        getter()
    except HTTPError as exc:
        if exc.response is not None and exc.response.status_code == 404:
            return True
        raise PilotError('Object existence is ambiguous') from None
    return False


def get_dataset(api):
    from kagglesdk.datasets.types.dataset_api_service import ApiGetDatasetRequest
    req = ApiGetDatasetRequest()
    req.owner_slug, req.dataset_slug = DATASET.split('/')
    with api.build_kaggle_client() as client:
        return client.datasets.dataset_api_client.get_dataset(req)


def get_kernel(api):
    from kagglesdk.kernels.types.kernels_api_service import ApiGetKernelRequest
    req = ApiGetKernelRequest()
    req.user_name, req.kernel_slug = KERNEL.split('/')
    with api.build_kaggle_client() as client:
        return client.kernels.kernels_api_client.get_kernel(req)


def validate_assets():
    request = json.loads((ROOT / 'once.json').read_text(encoding='utf-8'))
    if request != {'purpose': 'one-time synthetic Qwen batch pilot', 'input_sha256': INPUT_HASH}:
        raise PilotError('Unexpected pilot request')
    dataset_dir, kernel_dir = ROOT / 'pilot/dataset', ROOT / 'pilot/kernel'
    data = (dataset_dir / 'requests.jsonl').read_bytes()
    if hashlib.sha256(data).hexdigest() != INPUT_HASH or set(p.name for p in dataset_dir.iterdir()) != {'requests.jsonl', 'dataset-metadata.json'}:
        raise PilotError('Synthetic data changed or dataset folder has extra files')
    meta = json.loads((dataset_dir / 'dataset-metadata.json').read_text(encoding='utf-8'))
    if meta.get('id') != DATASET:
        raise PilotError('Dataset reference mismatch')
    kmeta = json.loads((kernel_dir / 'kernel-metadata.json').read_text(encoding='utf-8'))
    expected = {'id': KERNEL, 'is_private': True, 'enable_gpu': True,
                'enable_internet': False, 'machine_shape': 'NvidiaTeslaT4',
                'dataset_sources': [DATASET + '/1'], 'competition_sources': [],
                'kernel_sources': [], 'model_sources': [MODEL]}
    if any(kmeta.get(k) != v for k, v in expected.items()):
        raise PilotError('Pilot notebook configuration mismatch')
    name = kmeta.get('code_file')
    if not isinstance(name, str) or Path(name).name != name:
        raise PilotError('Unexpected notebook filename')
    nb = json.loads((kernel_dir / name).read_text(encoding='utf-8'))
    if canonical(nb) != CODE_HASH:
        raise PilotError('Notebook code hash mismatch')
    return dataset_dir, kernel_dir


def check_dataset(ds):
    if (ds is None or getattr(ds, 'ref', None) != DATASET or getattr(ds, 'is_private', None) is not True
            or type(getattr(ds, 'id', None)) is not int or ds.id <= 0
            or getattr(ds, 'current_version_number', None) != 1):
        raise PilotError('Dataset identity, privacy or version mismatch')
    return ds.id


def check_kernel(meta, notebook, kernel_id):
    expected = {'id': KERNEL, 'id_no': kernel_id, 'is_private': True, 'enable_gpu': True,
                'enable_internet': False, 'machine_shape': 'NvidiaTeslaT4',
                'dataset_sources': [DATASET + '/1'], 'competition_sources': [],
                'kernel_sources': [], 'model_sources': [MODEL], 'language': 'python', 'kernel_type': 'notebook'}
    if any(meta.get(k) != v for k, v in expected.items()) or canonical(notebook) != CODE_HASH:
        raise PilotError('Remote notebook identity, privacy, source, or configuration mismatch')


def check_receipt(receipt):
    if not receipt or getattr(receipt, 'error', None):
        raise PilotError('Notebook creation failed or receipt is ambiguous')
    for name in ('invalid_tags', 'invalid_dataset_sources', 'invalid_competition_sources', 'invalid_kernel_sources', 'invalid_model_sources'):
        if getattr(receipt, name, None) != []:
            raise PilotError('Notebook receipt has invalid or missing source diagnostics')
    ref = getattr(receipt, 'ref', None)
    allowed = {KERNEL, '/code/' + KERNEL, 'https://www.kaggle.com/code/' + KERNEL,
               'https://kaggle.com/code/' + KERNEL}
    ident = getattr(receipt, 'kernel_id', None)
    if ref not in allowed or type(ident) is not int or ident < 1 or getattr(receipt, 'version_number', None) != 1:
        raise PilotError('Notebook receipt identity/version mismatch')
    return ident


def main():
    if not os.environ.get('KAGGLE_API_TOKEN'):
        raise PilotError('Missing Kaggle credential')
    dataset_dir, kernel_dir = validate_assets()
    from kaggle.api.kaggle_api_extended import KaggleApi
    api = KaggleApi()
    quiet(api.authenticate)
    # Both checks happen before either mutation. Errors and non-404 statuses stop.
    if not is_missing(lambda: get_dataset(api)) or not is_missing(lambda: get_kernel(api)):
        raise PilotError('An object name already exists; no overwrite attempted')
    response = quiet(api.dataset_create_new, str(dataset_dir), public=False, quiet=True, convert_to_csv=False)
    if response is None or getattr(response, 'error', None) or getattr(response, 'invalid_tags', None) != []:
        raise PilotError('Dataset creation response failed or ambiguous')
    print('Synthetic dataset requested; verifying identity and privacy', flush=True)
    for _ in range(30):
        try:
            ds = quiet(get_dataset, api)
            check_dataset(ds)
            if quiet(api.dataset_status, DATASET) == 'ready':
                break
        except Exception:
            pass
        time.sleep(10)
    else:
        raise PilotError('Dataset readiness/privacy/version not confirmed; stop')
    print(json.dumps({'dataset_id': ds.id, 'dataset_version': 1, 'private': True, 'input_sha256': INPUT_HASH}), flush=True)
    receipt = quiet(api.kernels_push, str(kernel_dir))
    kernel_id = check_receipt(receipt)
    print(json.dumps({'kernel_id': kernel_id, 'accepted_version': 1}), flush=True)
    with tempfile.TemporaryDirectory(prefix='qwen-batch-pilot-') as tmp:
        pull = Path(tmp) / 'pull'
        quiet(api.kernels_pull, KERNEL + '/1', str(pull), metadata=True, quiet=True)
        meta = json.loads((pull / 'kernel-metadata.json').read_text(encoding='utf-8'))
        name = meta.get('code_file')
        if not isinstance(name, str) or Path(name).name != name:
            raise PilotError('Unexpected pulled notebook filename')
        check_kernel(meta, json.loads((pull / name).read_text(encoding='utf-8')), kernel_id)
        for _ in range(90):
            result = quiet(api.kernels_status, KERNEL + '/1')
            state = getattr(getattr(result, 'status', None), 'name', None)
            if state == 'COMPLETE':
                break
            if state not in {'QUEUED', 'RUNNING', 'NEW_SCRIPT'}:
                raise PilotError('Notebook did not complete')
            time.sleep(10)
        else:
            raise PilotError('Notebook status timed out')
        # Retrieve only the requested saved version. Ignore the automatic log.
        output = Path(tmp) / 'output'
        quiet(api.kernels_output, KERNEL + '/1', str(output), quiet=True)
        manifests = list(output.rglob('manifest.json'))
        results = list(output.rglob('results.jsonl'))
        if len(manifests) != 1 or len(results) != 1 or manifests[0].parent != results[0].parent:
            raise PilotError('Expected output files missing or ambiguous')
        manifest = json.loads(manifests[0].read_text(encoding='utf-8'))
        rows = [json.loads(x) for x in results[0].read_text(encoding='utf-8').splitlines()]
        if (manifest.get('status') != 'complete' or manifest.get('count') != 2
                or manifest.get('input_sha256') != INPUT_HASH or manifest.get('model') != MODEL
                or [x.get('id') for x in rows] != ['fixture-scope', 'finite-scope']
                or any(not isinstance(x.get('answer'), str) or not x['answer'].strip() for x in rows)):
            raise PilotError('Result shape or provenance mismatch')
        deliver = ROOT / 'pilot-output'
        deliver.mkdir(exist_ok=False)
        shutil.copyfile(manifests[0], deliver / 'manifest.json')
        shutil.copyfile(results[0], deliver / 'results.jsonl')
        print(json.dumps({'version_specific_status': 'COMPLETE', 'results': len(rows),
                          'input_hash_verified': True, 'output_retrieved': True}), flush=True)


if __name__ == '__main__':
    try:
        main()
    except PilotError as exc:
        print('Pilot stopped:', str(exc), 'Check created private objects before any retry.', file=sys.stderr)
        sys.exit(1)
    except Exception:
        # Third-party error details may contain credentials, user data, or URLs.
        print('Pilot stopped. Check which private objects were created before any retry.', file=sys.stderr)
        sys.exit(1)
