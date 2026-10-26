"""Load the frozen vendor contract; prohibit its fixed-mask entry point."""
import json
from pathlib import Path

def load_contract(filename):
    return json.loads(Path(filename).with_name('contract.json').read_text())

def assert_metrics(*args, **kwargs):
    raise RuntimeError('Use the explicit Kaggle adapter, not the fixed-mask upstream build()')

def emit_and_report(*args, **kwargs):
    raise RuntimeError('Use the explicit Kaggle adapter')
