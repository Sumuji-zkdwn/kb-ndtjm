#!/usr/bin/env python3
"""Reserve reaction_depth's existing vector once; no computation changes.

For an 86M-op DQI, geometric vector growth briefly retains old+new buffers
and exceeds 8 GiB. Exact reservation removes that transient duplication.
The official verifier, recurrence, operations and results are unmodified.
"""
import argparse
import hashlib
import json
from pathlib import Path

OLD = 'size_t Circuit::reaction_depth() const {\n    std::vector<Op> ops;\n    iter_ops'
NEW = 'size_t Circuit::reaction_depth() const {\n    std::vector<Op> ops;\n    ops.reserve(num_ops);\n    iter_ops'


def patch(root, report):
    path = Path(root)/'src/kickmix/circuit/circuit.cc'
    original = path.read_bytes()
    if hashlib.sha256(original).hexdigest() != '9bbd58129d8646c5d684c2c6f55bbe73181b0826061ffd41e36a782f55a2d3e4':
        raise ValueError('pinned upstream circuit.cc hash mismatch')
    text = original.decode()
    if text.count(OLD) != 1:
        raise ValueError('unexpected pinned Kickmix reaction_depth source')
    patched = text.replace(OLD,NEW).encode()
    path.write_bytes(patched)
    result = {'upstream_commit':'638777fac4379bc62e2a1e4a52cf1a1753895d48',
              'path':'src/kickmix/circuit/circuit.cc',
              'change':'ops.reserve(num_ops) before the unchanged reaction_depth loop',
              'original_sha256':hashlib.sha256(original).hexdigest(),
              'patched_sha256':hashlib.sha256(patched).hexdigest(),
              'official_verifier_modified':False,'arithmetic_or_gate_semantics_changed':False}
    dest = Path(report); dest.parent.mkdir(parents=True,exist_ok=True)
    dest.write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps(result,indent=2))


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('root')
    p.add_argument('--report',default='build/report/kickmix-memory-patch.json')
    a=p.parse_args();patch(a.root,a.report)
