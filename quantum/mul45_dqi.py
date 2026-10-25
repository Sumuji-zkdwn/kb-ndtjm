#!/usr/bin/env python3
"""Replace the 63-Toffoli multipliers in the pinned complete non-Forney DQI.

Only the inner gf_mul is replaced. Every caller, existing product cleanup,
classical record and condition remains untouched. No extra wires or bits.
"""
import argparse
from collections import Counter
import gzip
import json
from pathlib import Path
import struct
import subprocess
import sys

import numpy as np

from dqi_gate import sha
from inverse66_dqi import encode, prefix_counts
from eea_quotient_dqi import rewrite
from wfs_dqi_single_site import KMB

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'research/mul45'))
from probe import compile_ops, decomposition, reference_ops

REFERENCE_SHA = '655e83ab2ee40d65688e01c883a3804765080c1e47ee4e53f9d7b01bb6621177'
OP = {'CX': 0x21, 'CCX': 0x31, 'SWAP': 0x22}


def encoded(operations):
    data = encode([(OP[name], wires) for name, wires in operations])
    return data, {p: np.frombuffer(data[p], dtype='<u4') for p in range(2, 10)}


def find_sites(k):
    p, _ = k.packets[11]
    count = struct.unpack_from('<Q', k.data, p)[0]
    ends = np.frombuffer(k.data, dtype='<u8', count=count, offset=p + 8)
    text = p + 8 + 8 * count
    positions = np.flatnonzero(k.ops == 6)
    assert len(positions) == count
    stack, sites, previous = [], [], 0
    for i, end in enumerate(ends):
        end = int(end)
        tag = k.data[text + previous:text + end].decode()
        previous = end
        if tag.startswith('@enter:'):
            stack.append((tag[7:], int(positions[i]), i))
        elif tag.startswith('@exit:'):
            name, start, first_tag = stack.pop()
            assert name == tag[6:]
            if name == 'gf_mul':
                assert stack[-1][0] == 'c_gf_mul'
                sites.append({'index': len(sites), 'stage': stack[0][0],
                              'start': start + 1, 'stop': int(positions[i]),
                              'tag_start': first_tag + 1, 'tag_stop': i})
    assert not stack
    assert Counter(s['stage'] for s in sites) == {'forward_eea': 16204, 'reverse_eea': 16204}
    return sites, ends, text


def match_arrays(actual_ops, actual_arrays, old_data, old_arrays):
    """Exact opcode and operand equality under an injective 36-wire renaming."""
    assert np.array_equal(actual_ops[actual_ops != 6], np.frombuffer(old_data[1], dtype='u1')), 'opcode mismatch'
    mapping = np.full(36, -1, dtype=np.int64)
    for p in range(2, 10):
        canonical, actual = old_arrays[p], actual_arrays[p]
        assert canonical.shape == actual.shape, 'operand count mismatch'
        for wire in np.unique(canonical):
            first = int(np.flatnonzero(canonical == wire)[0])
            value = int(actual[first])
            assert mapping[wire] in (-1, value), 'inconsistent renaming'
            mapping[wire] = value
    assert np.all(mapping >= 0) and len(set(mapping.tolist())) == 36, 'aliased or missing wire'
    for p in range(2, 10):
        assert np.array_equal(mapping[old_arrays[p]], actual_arrays[p]), 'operand mismatch'
    return mapping.astype('<u4')


def build(reference, directory, number):
    assert sha(reference) == REFERENCE_SHA
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    formal = directory / 'formal'
    subprocess.run([sys.executable, str(ROOT/'research/mul45/probe.py'),
                    '--out', str(formal)], check=True, stdout=subprocess.DEVNULL)
    proof = json.loads((formal/'local-report.json').read_text())
    assert proof['certificate']['status'] == proof['old_certificate']['status'] == 'PASS'
    terms, _ = decomposition()
    old_data, old_arrays = encoded(reference_ops())
    new_data, new_arrays = encoded(compile_ops(terms))
    k = KMB(reference)
    all_sites, tag_ends, tag_text = find_sites(k)
    number = len(all_sites) if number == 'all' else int(number)
    assert 1 <= number <= len(all_sites)
    sites = all_sites[:number]
    boundaries = np.asarray(sorted({p for s in sites for p in (s['start'], s['stop'])}))
    rank = {p: prefix_counts(k.ops, boundaries, p) for p in range(2, 10)}
    original_arrays = {p: k.array(p) for p in range(2, 10)}
    pushes, pops = np.flatnonzero(k.ops == 0x81), np.flatnonzero(k.ops == 1)
    edits = {p: [] for p in range(1, 10)}
    keep = np.ones(len(tag_ends), dtype=bool)
    removed, manifest = [], []
    for site in sites:
        start, stop = site['start'], site['stop']
        assert np.searchsorted(pushes, start) == np.searchsorted(pops, start)
        actual_arrays = {p: original_arrays[p][rank[p][start]:rank[p][stop]] for p in range(2, 10)}
        mapping = match_arrays(k.ops[start:stop], actual_arrays, old_data, old_arrays)
        assert int(mapping.max()) < k.header[1]
        edits[1].append((start, stop, new_data[1]))
        for p in range(2, 10):
            replacement = mapping[new_arrays[p]].tobytes()
            edits[p].append((4*rank[p][start], 4*rank[p][stop], replacement))
        keep[site['tag_start']:site['tag_stop']] = False
        removed.append((int(tag_ends[site['tag_start']-1]), int(tag_ends[site['tag_stop']-1])))
        manifest.append({**site, 'a': mapping[:12].tolist(), 'b': mapping[12:24].tolist(),
                         'arbitrary_xor_target': mapping[24:].tolist(),
                         'old_Toffoli_like': 63, 'new_Toffoli_like': 45})
    c, preserved = rewrite(k, directory/'dqi.kmb', edits, keep, tag_ends, tag_text, removed)
    assert c.header[1:4] == k.header[1:4] == (1893, 49155, 4165)
    assert c.header[5] == 4484694 - number*18
    manifest_text = (json.dumps(manifest, separators=(',', ':')) + '\n').encode()
    (directory/'site-map.json.gz').write_bytes(gzip.compress(manifest_text, mtime=0))
    report = {'status': 'PASS', 'scope': 'complete DQI; existing inverse66 plus 45-Toffoli multiplier',
              'reference_dqi_sha256': REFERENCE_SHA, 'sites_replaced': number,
              'sites_by_stage': dict(Counter(s['stage'] for s in sites)),
              'candidate_sha256': sha(directory/'dqi.kmb'),
              'candidate_bytes': (directory/'dqi.kmb').stat().st_size,
              'qubits': c.header[1], 'bits': c.header[2], 'registers': c.header[3], 'ops': c.header[4],
              'reference_static_Toffoli_like': k.header[5], 'candidate_static_Toffoli_like': c.header[5],
              'static_Toffoli_saved': number*18, 'extra_qubits': 0, 'extra_classical_bits': 0,
              'all_old_instructions_matched_under_injective_renaming': True,
              'named_registers_unchanged': True, 'existing_product_cleanup_unchanged': True,
              'classical_records_unchanged': True, 'outer_conditions_unchanged': True,
              'unchanged_packet_span_bytes_verified': preserved, 'retained_metadata_byte_equal': True,
              'local_certificate': proof['certificate'], 'local_old_certificate': proof['old_certificate'],
              'generator_sha256': sha(__file__), 'probe_sha256': sha(ROOT/'research/mul45/probe.py'),
              'kickmix_full_parse': 'NOT_RUN', 'full_DQI_verifier': 'NOT_RUN',
              'kaggle_submission': 'NOT_RUN'}
    (directory/'integration-report.json').write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps(report, indent=2))


def parse_full(directory):
    import kickmix as km
    directory = Path(directory)
    path = directory/'integration-report.json'
    report = json.loads(path.read_text())
    assert sha(directory/'dqi.kmb') == report['candidate_sha256']
    circuit = km.Circuit.from_file(directory/'dqi.kmb', format='kmb')
    assert circuit.num_qubits == report['qubits'] and circuit.num_bits == report['bits']
    assert circuit.operation_statistics().num_toffoli_like == report['candidate_static_Toffoli_like']
    report['kickmix_full_parse'] = 'PASS'
    path.write_text(json.dumps(report, indent=2) + '\n')
    print('Full mul45 DQI native parse PASS')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--reference')
    parser.add_argument('--output', default='build/mul45')
    parser.add_argument('--sites', default='1')
    parser.add_argument('--parse', action='store_true')
    args = parser.parse_args()
    if args.parse:
        parse_full(args.output)
    else:
        if not args.reference:
            parser.error('--reference is required')
        build(args.reference, args.output, args.sites)
