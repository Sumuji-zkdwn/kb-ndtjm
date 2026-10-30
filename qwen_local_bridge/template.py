# Edit only these intentionally selected requests before Save & Run.
# Each record has a unique id and a prompt. Saved notebook versions retain inputs.
BATCH_REQUESTS = [
  {
    "id": "fixture-scope",
    "prompt": "\u67b6\u7a7a\u306e\u7814\u7a76\u3067\u56fa\u5b9a\u30c6\u30b9\u30c810\u4ef6\u304c\u5168\u3066\u901a\u904e\u3057\u307e\u3057\u305f\u3002\u3053\u306e\u7d50\u679c\u306e\u610f\u5473\u3068\u9650\u754c\u3092\u65e5\u672c\u8a9e\u30672\u6587\u3067\u8aac\u660e\u3057\u3066\u304f\u3060\u3055\u3044\u3002"
  },
  {
    "id": "finite-scope",
    "prompt": "\u67b6\u7a7a\u306e\u6570\u5024\u5b9f\u9a13\u306743\u4f8b\u304c\u6b63\u5e38\u7d42\u4e86\u3057\u307e\u3057\u305f\u3002\u4e00\u822c\u8a3c\u660e\u3068\u6df7\u540c\u3057\u306a\u3044\u77ed\u3044\u7814\u7a76\u30e1\u30e2\u3092\u65e5\u672c\u8a9e\u3067\u66f8\u3044\u3066\u304f\u3060\u3055\u3044\u3002"
  }
]


"""Explicit-input Qwen batch for a private Kaggle notebook.

No files or conversations are discovered automatically. Configure INPUT_FILE in
the notebook; attaching data to Kaggle is a separate deliberate user action.
"""
import hashlib
import json
import os
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path

MAX_BYTES = 512_000
MAX_ITEMS = 50
MAX_PROMPT_CHARS = 12_000
MAX_INPUT_TOKENS = 4096
MAX_NEW_TOKENS = 256
ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,63}\Z")
MODEL = Path('/kaggle/input/models/qwen-lm/qwen2.5/transformers/7b-instruct/1')


def load_requests(path):
    with Path(path).open('rb') as source:
        raw = source.read(MAX_BYTES + 1)
    if len(raw) > MAX_BYTES:
        raise ValueError('input exceeds size limit')
    lines = raw.decode('utf-8-sig').splitlines()
    if not 1 <= len(lines) <= MAX_ITEMS:
        raise ValueError('input must contain 1 to 50 records')
    items = []
    ids = set()
    for line in lines:
        row = json.loads(line)
        if not isinstance(row, dict) or set(row) != {'id', 'prompt'}:
            raise ValueError('each record must contain exactly id and prompt')
        identifier, prompt = row['id'], row['prompt']
        if not isinstance(identifier, str) or not ID.fullmatch(identifier) or identifier in ids:
            raise ValueError('invalid or duplicate id')
        if not isinstance(prompt, str) or not prompt.strip() or len(prompt) > MAX_PROMPT_CHARS:
            raise ValueError('invalid prompt')
        ids.add(identifier)
        items.append(row)
    return items, hashlib.sha256(raw).hexdigest()


def run_batch(input_path, output_root, generate, metadata):
    """Process one validated batch; no prompt or answer is printed to logs."""
    items, digest = load_requests(input_path)
    run = Path(output_root) / ('qwen_batch_' + uuid.uuid4().hex)
    run.mkdir(parents=True, exist_ok=False)
    results = run / 'results.jsonl'
    count = 0
    try:
        with results.open('x', encoding='utf-8', newline='\n') as f:
            for row in items:
                answer = generate(row['prompt'])
                if not isinstance(answer, str) or not answer.strip():
                    raise ValueError('empty model response')
                f.write(json.dumps({'id': row['id'], 'answer': answer}, ensure_ascii=False) + '\n')
                f.flush()
                count += 1
        manifest = {'status': 'complete', 'count': count, 'input_sha256': digest,
                    'created_utc': datetime.now(timezone.utc).isoformat(), **metadata}
        (run / 'manifest.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    except Exception:
        # Partial results remain available; a failure never creates a complete manifest.
        (run / 'FAILED').write_text('Batch failed. results.jsonl may be partial.\n', encoding='utf-8')
        raise
    return run


def main(input_file):
    input_path = Path(input_file).resolve(strict=True)
    if not input_path.is_relative_to(Path('/tmp').resolve()) or not input_path.is_file():
        raise ValueError('input must be the temporary selected batch')
    # Validate before loading a large model.
    load_requests(input_path)
    import torch
    import transformers
    from transformers import AutoModelForCausalLM, AutoTokenizer
    if not torch.cuda.is_available():
        raise RuntimeError('GPU unavailable')
    if not (MODEL / 'config.json').is_file() or not (MODEL / 'tokenizer.json').is_file():
        raise RuntimeError('attach the official Qwen2.5 7B Instruct model version 1')
    tokenizer = AutoTokenizer.from_pretrained(str(MODEL), local_files_only=True, trust_remote_code=False)
    model = AutoModelForCausalLM.from_pretrained(str(MODEL), local_files_only=True,
             trust_remote_code=False, torch_dtype=torch.float16, device_map='auto', low_cpu_mem_usage=True)
    model.eval()
    device_map = getattr(model, 'hf_device_map', {})
    if not any(str(d).startswith('cuda') or isinstance(d, int) for d in device_map.values()):
        raise RuntimeError('model did not use GPU')

    def generate(prompt):
        messages = [{'role': 'system', 'content': 'You are a helpful assistant.'},
                    {'role': 'user', 'content': prompt}]
        inputs = tokenizer.apply_chat_template(messages, tokenize=True, add_generation_prompt=True,
                  return_tensors='pt', return_dict=True)
        if inputs['input_ids'].shape[-1] > MAX_INPUT_TOKENS:
            raise ValueError('prompt exceeds token limit')
        inputs = inputs.to(next(model.parameters()).device)
        with torch.inference_mode():
            generated = model.generate(**inputs, max_new_tokens=MAX_NEW_TOKENS, do_sample=False,
                                       pad_token_id=tokenizer.eos_token_id)
        return tokenizer.decode(generated[0, inputs['input_ids'].shape[-1]:], skip_special_tokens=True).strip()

    out = run_batch(input_path, '/kaggle/working', generate,
        {'model': 'qwen-lm/qwen2.5/Transformers/7b-instruct/1', 'torch': torch.__version__,
         'transformers': transformers.__version__, 'gpus': [torch.cuda.get_device_name(i) for i in range(torch.cuda.device_count())],
         'max_input_tokens': MAX_INPUT_TOKENS, 'max_new_tokens': MAX_NEW_TOKENS, 'do_sample': False})
    print('Batch completed; output directory:', out)



import tempfile
if not isinstance(BATCH_REQUESTS, list) or not 1 <= len(BATCH_REQUESTS) <= MAX_ITEMS:
    raise ValueError('BATCH_REQUESTS must contain 1 to 50 records')
with tempfile.TemporaryDirectory(prefix='explicit-qwen-batch-', dir='/tmp') as temp_dir:
    selected = Path(temp_dir) / 'requests.jsonl'
    with selected.open('x', encoding='utf-8', newline='\n') as f:
        for request in BATCH_REQUESTS:
            if not isinstance(request, dict) or set(request) != {'id', 'prompt'}:
                raise ValueError('Each request must contain only id and prompt')
            if not isinstance(request['prompt'], str) or len(request['prompt']) > MAX_PROMPT_CHARS:
                raise ValueError('Invalid prompt')
            if not isinstance(request['id'], str) or not ID.fullmatch(request['id']):
                raise ValueError('Invalid request id')
            f.write(json.dumps(request, ensure_ascii=False, separators=(',', ':')) + '\n')
    main(selected)
