"""Verify the unchanged, attributed upstream files before generating a circuit."""
import hashlib
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent

def check():
    data = json.loads((HERE / 'provenance.json').read_text())
    for row in data['files']:
        digest = hashlib.sha256((HERE / row['local_path']).read_bytes()).hexdigest()
        if digest != row['sha256']:
            raise ValueError(f"attributed source changed: {row['local_path']}")
    print(f"PASS: {len(data['files'])} attributed source files")

if __name__ == '__main__':
    check()
