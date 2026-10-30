"""Explicit, opt-in Kaggle batch bridge; no local-app interception.

The caller chooses a JSONL file. Prompt contents are retained in private Kaggle
notebook versions and outputs; they are never put in GitHub or printed here.
Automatic retry after an attempted push is deliberately prohibited.
"""
import argparse, ast, contextlib, copy, hashlib, io, json, os, re, shutil, sys, tempfile, time, uuid
from pathlib import Path
from urllib.parse import urlsplit

REF = 'sumuji/qwen-explicit-batch-20261031'
KERNEL_ID = 141806208
TITLE = 'qwen-explicit-batch-20261031'
MODEL = 'qwen-lm/qwen2.5/Transformers/7b-instruct/1'
MARKER = 'QWEN-EXPLICIT-BATCH-LEDGER-v1:'
MAX_ITEMS, MAX_CHARS, MAX_BYTES, MAX_HISTORY = 50, 12000, 512000, 128
ID = re.compile(r'[A-Za-z0-9][A-Za-z0-9_-]{0,63}\Z')
RUN_ID = re.compile(r'[a-z0-9][a-z0-9-]{5,39}\Z')
ROOT = Path(__file__).resolve().parent


class Stop(Exception): pass


def request_data(path):
    with Path(path).open('rb') as f:
        raw = f.read(MAX_BYTES + 1)
    if len(raw) > MAX_BYTES: raise Stop('Input is too large')
    try:
        lines = raw.decode('utf-8-sig').splitlines()
        rows = [json.loads(x) for x in lines]
    except (UnicodeError, ValueError):
        raise Stop('Input must be UTF-8 JSONL') from None
    if not 1 <= len(rows) <= MAX_ITEMS: raise Stop('Input must have 1 to 50 records')
    seen = set()
    for row in rows:
        if not isinstance(row, dict) or set(row) != {'id', 'prompt'}: raise Stop('Invalid record fields')
        ident, prompt = row['id'], row['prompt']
        if not isinstance(ident, str) or not ID.fullmatch(ident) or ident in seen: raise Stop('Invalid or duplicate record ID')
        if not isinstance(prompt, str) or not prompt.strip() or len(prompt) > MAX_CHARS: raise Stop('Invalid prompt')
        seen.add(ident)
    # Reproduce bytes emitted by the tested Kaggle batch code.
    wire = ''.join(json.dumps(x, ensure_ascii=False, separators=(',', ':')) + '\n' for x in rows).encode('utf-8')
    if len(wire) > MAX_BYTES: raise Stop('Normalized input is too large')
    return rows, hashlib.sha256(wire).hexdigest()


def text_source(cell):
    s = cell.get('source')
    if isinstance(s, list) and all(isinstance(x, str) for x in s): s = ''.join(s)
    if not isinstance(s, str): raise Stop('Invalid cell source')
    return s.replace('\r\n', '\n')


def split_code(code):
    try: tree = ast.parse(code)
    except SyntaxError: raise Stop('Notebook code is invalid') from None
    candidates = [n for n in tree.body if isinstance(n, ast.Assign) and
                  len(n.targets) == 1 and isinstance(n.targets[0], ast.Name) and n.targets[0].id == 'BATCH_REQUESTS']
    if len(candidates) != 1: raise Stop('Batch input assignment unavailable')
    a = candidates[0]
    if a.col_offset != 0 or a.end_col_offset is None: raise Stop('Unexpected batch input layout')
    try: previous = ast.literal_eval(a.value)
    except (ValueError, TypeError, SyntaxError): raise Stop('Batch input is not literal') from None
    if not isinstance(previous, list): raise Stop('Batch input must be a list')
    lines = code.splitlines(keepends=True)
    before = ''.join(lines[:a.lineno - 1])
    end = lines[a.end_lineno - 1]
    try:
        # CPython AST column offsets count UTF-8 bytes, not Unicode code points.
        suffix = end.encode('utf8')[a.end_col_offset:].decode('utf8')
    except UnicodeError: raise Stop('Invalid input assignment boundary') from None
    after = suffix + ''.join(lines[a.end_lineno:])
    return before, after


def template_hash(code):
    before, after = split_code(code)
    return hashlib.sha256((before + 'BATCH_REQUESTS = <DATA>' + after).encode('utf-8')).hexdigest()


def check_metadata(meta):
    wanted = {'id': REF, 'id_no': KERNEL_ID, 'title': TITLE, 'is_private': True,
              'language': 'python', 'kernel_type': 'notebook', 'enable_gpu': True,
              'enable_internet': False, 'machine_shape': 'NvidiaTeslaT4',
              'dataset_sources': [], 'kernel_sources': [], 'competition_sources': [],
              'model_sources': [MODEL]}
    if any(meta.get(k) != v for k, v in wanted.items()) or meta.get('enable_tpu') not in (False, None):
        raise Stop('Notebook identity, privacy, GPU or input configuration differs')
    if not isinstance(meta.get('keywords'), list): raise Stop('Notebook tags unavailable')


def prepare(nb, rows, run_id, expected_template_hash, previous_id='none'):
    if not RUN_ID.fullmatch(run_id): raise Stop('Invalid run ID')
    result = copy.deepcopy(nb)
    if result.get('nbformat') != 4 or not isinstance(result.get('cells'), list): raise Stop('Invalid notebook')
    cells = result['cells']
    history = []
    if len(cells) == 2 and cells[-1].get('cell_type') == 'markdown':
        marker = text_source(cells.pop())
        if not marker.startswith(MARKER): raise Stop('Unrecognized notebook marker')
        try: history = json.loads(marker[len(MARKER):])
        except ValueError: raise Stop('Invalid notebook marker') from None
        if (not isinstance(history, list) or not history or len(history) >= MAX_HISTORY or
            any(not isinstance(x, str) or not RUN_ID.fullmatch(x) for x in history) or len(set(history)) != len(history)):
            raise Stop('Invalid notebook history')
    if len(cells) != 1 or cells[0].get('cell_type') != 'code': raise Stop('Unexpected notebook structure')
    code = text_source(cells[0])
    if template_hash(code) != expected_template_hash: raise Stop('Notebook program has changed; stop')
    if run_id in history: raise Stop('Request ID already appears in notebook history')
    if previous_id != (history[-1] if history else 'none'): raise Stop('Previous ID does not match notebook history')
    before, after = split_code(code)
    cells[0]['source'] = before + 'BATCH_REQUESTS = ' + json.dumps(rows, ensure_ascii=True, indent=2) + after
    cells[0]['outputs'], cells[0]['execution_count'] = [], None
    history.append(run_id)
    cells.append({'cell_type': 'markdown', 'metadata': {}, 'id': hashlib.sha256(run_id.encode()).hexdigest()[:12],
                  'source': MARKER + json.dumps(history, separators=(',', ':')) + '\n'})
    return result, history


def check_receipt(receipt):
    if receipt is None or getattr(receipt, 'error', None): raise Stop('Ambiguous push response')
    for key in ('invalid_tags','invalid_dataset_sources','invalid_competition_sources','invalid_kernel_sources','invalid_model_sources'):
        if getattr(receipt, key, None) != []: raise Stop('Invalid source diagnostics')
    ref = getattr(receipt, 'ref', None)
    if ref not in {REF, '/code/' + REF, 'https://www.kaggle.com/code/' + REF, 'https://kaggle.com/code/' + REF}:
        raise Stop('Push identity mismatch')
    version = getattr(receipt, 'version_number', None)
    if getattr(receipt, 'kernel_id', None) != KERNEL_ID or type(version) is not int or version < 3:
        raise Stop('Push version mismatch')
    return version


def quiet(fn, *args, **kwargs):
    with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
        return fn(*args, **kwargs)


def pull(api, version=None):
    ref = REF if version is None else f'{REF}/{version}'
    with tempfile.TemporaryDirectory(prefix='qwen-pull-') as td:
        folder = Path(td)
        quiet(api.kernels_pull, ref, str(folder), metadata=True, quiet=True)
        meta = json.loads((folder / 'kernel-metadata.json').read_text(encoding='utf8'))
        check_metadata(meta)
        name = meta.get('code_file')
        if not isinstance(name, str) or Path(name).name != name: raise Stop('Invalid source filename')
        p = folder / name
        if p.stat().st_size > 2_000_000: raise Stop('Notebook exceeds size limit')
        return meta, json.loads(p.read_text(encoding='utf8'))


def state(api, ref):
    result = quiet(api.kernels_status, ref)
    s = getattr(getattr(result, 'status', None), 'name', None)
    if s not in ('QUEUED','RUNNING','COMPLETE','ERROR','CANCEL_REQUESTED','CANCEL_ACKNOWLEDGED','NEW_SCRIPT'):
        raise Stop('Unknown Kaggle state')
    return s


def head(api):
    from kagglesdk.kernels.types.kernels_api_service import ApiGetKernelRequest
    request = ApiGetKernelRequest()
    request.user_name, request.kernel_slug = REF.split('/')
    with api.build_kaggle_client() as client:
        response = quiet(client.kernels.kernels_api_client.get_kernel, request)
    meta = getattr(response, 'metadata', None)
    if (getattr(meta, 'id', None) != KERNEL_ID or getattr(meta, 'ref', None) != REF or
        getattr(meta, 'is_private', None) is not True): raise Stop('Current notebook identity or privacy mismatch')
    version = getattr(meta, 'current_version_number', None)
    if type(version) is not int or version < 2: raise Stop('Current notebook version unavailable')
    return version


def acquire_lock():
    path = ROOT / '.active.lock'
    try: fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except FileExistsError: raise Stop('Another run or unresolved lock exists; inspect before recovery') from None
    with os.fdopen(fd, 'w', encoding='ascii') as f:
        f.write('exclusive local execution\n'); f.flush(); os.fsync(f.fileno())
    return path


def start_journal(output_dir, run_id, digest, previous_id):
    p = output_dir / (run_id + '.attempt.json')
    try: fd = os.open(p, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except FileExistsError: raise Stop('This run ID already has an attempt record; do not retry') from None
    with os.fdopen(fd, 'w', encoding='utf8') as f:
        json.dump({'id': run_id, 'input_sha256': digest, 'previous_id': previous_id,
                   'state': 'push_may_have_been_attempted'}, f)
        f.write('\n'); f.flush(); os.fsync(f.fileno())
    return p


def perform(api, input_path, output_dir, run_id, previous_id, expected_hash, timeout=1200, sleep=time.sleep):
    rows, digest = request_data(input_path)
    output = Path(output_dir).resolve(strict=True)
    if not output.is_dir(): raise Stop('Output must be an existing directory')
    lock = acquire_lock()
    try:
        initial = head(api)
        if state(api, f'{REF}/{initial}') != 'COMPLETE': raise Stop('Current notebook version is not complete')
        meta, nb = pull(api, initial)
        job, history = prepare(nb, rows, run_id, expected_hash, previous_id)
        meta2, nb2 = pull(api, initial)
        job2, history2 = prepare(nb2, rows, run_id, expected_hash, previous_id)
        fields = ('id','id_no','title','is_private','enable_gpu','enable_internet','machine_shape',
                  'dataset_sources','kernel_sources','competition_sources','model_sources','docker_image','keywords')
        if job != job2 or history != history2 or any(meta.get(k) != meta2.get(k) for k in fields) or head(api) != initial:
            raise Stop('Notebook changed during preflight')
        metadata = {'id': REF, 'id_no': KERNEL_ID, 'title': TITLE, 'code_file': 'job.ipynb',
                    'language': 'python', 'kernel_type': 'notebook', 'is_private': True,
                    'enable_gpu': True, 'enable_tpu': False, 'enable_internet': False,
                    'machine_shape': 'NvidiaTeslaT4', 'dataset_sources': [], 'competition_sources': [],
                    'kernel_sources': [], 'model_sources': [MODEL], 'keywords': meta['keywords']}
        if meta.get('docker_image'): metadata['docker_image'] = meta['docker_image']
        with tempfile.TemporaryDirectory(prefix='qwen-send-') as td:
            p = Path(td)
            (p / 'job.ipynb').write_text(json.dumps(job, ensure_ascii=True), encoding='ascii')
            (p / 'kernel-metadata.json').write_text(json.dumps(metadata), encoding='ascii')
            start_journal(output, run_id, digest, previous_id)
            response = quiet(api.kernels_push, str(p))
        version = check_receipt(response)
        if version <= initial: raise Stop('Version did not advance; inspect before retry')
        print(json.dumps({'run_id': run_id, 'accepted_version': version, 'status': 'pending'}), flush=True)
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            status = state(api, f'{REF}/{version}')
            if status == 'COMPLETE': break
            if status in ('ERROR','CANCEL_REQUESTED','CANCEL_ACKNOWLEDGED'): raise Stop('Kaggle execution failed')
            sleep(20)
        else: raise Stop('Kaggle timed out; inspect before retry')
        _, done = pull(api, version)
        done_cells = done.get('cells', [])
        if len(done_cells) != 2 or text_source(done_cells[-1]) != MARKER + json.dumps(history,separators=(',',':')) + '\n':
            raise Stop('Completed notebook request marker mismatch')
        first = text_source(done_cells[0])
        if template_hash(first) != expected_hash: raise Stop('Completed notebook program mismatch')
        tree = ast.parse(first)
        matching = [n for n in tree.body if isinstance(n, ast.Assign) and len(n.targets)==1 and
                    isinstance(n.targets[0], ast.Name) and n.targets[0].id == 'BATCH_REQUESTS']
        if len(matching) != 1 or ast.literal_eval(matching[0].value) != rows: raise Stop('Completed notebook input mismatch')
        with tempfile.TemporaryDirectory(prefix='qwen-output-') as td:
            folder = Path(td)
            quiet(api.kernels_output, f'{REF}/{version}', str(folder), quiet=True)
            m, r = list(folder.rglob('manifest.json')), list(folder.rglob('results.jsonl'))
            if len(m) != 1 or len(r) != 1 or m[0].parent != r[0].parent: raise Stop('Output files missing or ambiguous')
            if m[0].stat().st_size > 100_000 or r[0].stat().st_size > 2_000_000: raise Stop('Output exceeds limits')
            manifest = json.loads(m[0].read_text(encoding='utf8'))
            answers = [json.loads(line) for line in r[0].read_text(encoding='utf8').splitlines()]
            if (manifest.get('status') != 'complete' or manifest.get('count') != len(rows) or
                manifest.get('input_sha256') != digest or manifest.get('model') != MODEL or
                [a.get('id') for a in answers] != [a['id'] for a in rows] or
                any(not isinstance(a.get('answer'),str) or not a['answer'].strip() for a in answers)):
                raise Stop('Output record identity or input hash mismatch')
            dest = output / (run_id + '-results')
            dest.mkdir(exist_ok=False)
            shutil.copyfile(m[0], dest / 'manifest.json')
            shutil.copyfile(r[0], dest / 'results.jsonl')
        print(json.dumps({'run_id':run_id,'version':version,'state':'complete','output':str(dest)}),flush=True)
        return version
    finally:
        lock.unlink(missing_ok=True)


def main():
    parser = argparse.ArgumentParser(description='Run an explicitly selected Qwen batch on a private Kaggle notebook')
    parser.add_argument('--input', required=True); parser.add_argument('--output', required=True)
    parser.add_argument('--previous-id', required=True, help='last ledger ID, or none only for the original version')
    parser.add_argument('--run-id', default=None)
    args = parser.parse_args()
    run_id = args.run_id or ('qwen-' + uuid.uuid4().hex)
    fingerprint = (ROOT / 'verified-template-sha256.txt').read_text(encoding='ascii').strip()
    if not re.fullmatch(r'[0-9a-f]{64}', fingerprint): raise Stop('Verified template fingerprint unavailable')
    from kaggle.api.kaggle_api_extended import KaggleApi
    api = KaggleApi(); quiet(api.authenticate)
    perform(api, args.input, args.output, run_id, args.previous_id, fingerprint)


if __name__ == '__main__':
    try: main()
    except Stop as e:
        print('Stopped:', str(e), file=sys.stderr); sys.exit(1)
    except Exception:
        print('Stopped on a local or remote error. Inspect the notebook and attempt record before any retry.', file=sys.stderr); sys.exit(1)
