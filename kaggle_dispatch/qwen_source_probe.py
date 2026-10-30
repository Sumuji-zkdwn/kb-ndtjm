"""Read-only categorization of Qwen model source metadata.
Prints only public model references from a fixed allowlist and bounded categories.
Never prints source, credentials, prompts, outputs, or server error bodies.
"""
import hashlib
import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path

REFS = ['sumuji/qwen25-7b-kaggle-smoke', 'sumuji/qwen25-7b-kaggle-smoke/3']
EXPECTED = 'qwen-lm/qwen2.5/transformers/7b-instruct/1'
MODEL = re.compile(r'^(?:/?(?:kaggle/input/)?models/)?qwen-lm/qwen2\.5/transformers/7b-instruct(?:/1)?/?$', re.IGNORECASE)


def classify(value):
    if not isinstance(value, str):
        return {'type': type(value).__name__, 'kind': 'non_string'}
    result = {'type': 'str', 'length': len(value), 'sha256': hashlib.sha256(value.encode()).hexdigest()}
    if value == EXPECTED:
        result.update(kind='exact', public_model_ref=EXPECTED)
    elif MODEL.fullmatch(value):
        result.update(kind='recognized_public_model_variant', public_model_ref=value)
    else:
        result.update(kind='other_suppressed')
    return result


def run(ref):
    with tempfile.TemporaryDirectory(prefix='qwen-meta-probe-') as tmp:
        cmd=[sys.executable,'-m','kaggle','kernels','pull',ref,'-p',tmp,'-m']
        r=subprocess.run(cmd,capture_output=True,text=True,timeout=120,check=False)
        if r.returncode:
            return {'ref':ref,'status':'pull_failed','return_code':r.returncode}
        p=Path(tmp)/'kernel-metadata.json'
        if not p.is_file():
            return {'ref':ref,'status':'metadata_missing'}
        m=json.loads(p.read_text(encoding='utf-8'))
        sources=m.get('model_sources')
        if not isinstance(sources,list):
            return {'ref':ref,'status':'model_sources_not_list','type':type(sources).__name__}
        machine=m.get('machine_shape')
        machine_category=machine if machine in ('NvidiaTeslaT4','NvidiaTeslaT4x2','NvidiaTeslaT4X2','NvidiaTeslaP100','NvidiaTeslaP100x1','NvidiaTeslaP100X1','Unspecified','') else 'other_or_missing'
        return {'ref':ref,'status':'ok','identity_matches':m.get('id')=='sumuji/qwen25-7b-kaggle-smoke',
                'is_private':m.get('is_private') is True,'gpu':m.get('enable_gpu') is True,
                'model_count':len(sources),'sources':[classify(s) for s in sources],
                'dataset_count':len(m.get('dataset_sources',[])), 'competition_count':len(m.get('competition_sources',[])),
                'kernel_count':len(m.get('kernel_sources',[])), 'machine':machine_category}

def status(ref):
    cmd = [sys.executable, '-m', 'kaggle', 'kernels', 'status', ref]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=120, check=False)
    except (OSError, subprocess.TimeoutExpired):
        return 'unknown'
    if result.returncode:
        return 'unknown'
    line = next((line for line in result.stdout.splitlines() if 'has status' in line), '')
    match = re.search(r'has status [\"\']([a-zA-Z_]+)[\"\']', line)
    if not match:
        return 'unknown'
    state = match.group(1).lower()
    if state in {'complete', 'error', 'cancelled', 'running', 'queued', 'pending', 'cancelacknowledged'}:
        return state
    return 'unknown'


if __name__ == '__main__':
    for ref in ('sumuji/qwen25-7b-kaggle-smoke/2', 'sumuji/qwen25-7b-kaggle-smoke/3', 'sumuji/qwen25-7b-kaggle-smoke'):
        print(json.dumps({'status_query': ref, 'normalized_status': status(ref), 'version_status_not_independently_verified': True}), flush=True)
    for ref in REFS:
        try:
            print(json.dumps(run(ref), sort_keys=True), flush=True)
        except (OSError, ValueError, subprocess.TimeoutExpired, json.JSONDecodeError):
            print(json.dumps({'ref':ref,'status':'probe_error_suppressed'}), flush=True)
            sys.exit(1)
