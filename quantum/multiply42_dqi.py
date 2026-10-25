#!/usr/bin/env python3
"""Replace pure 63-Toffoli products with proved 42-Toffoli products in full DQI.

Only gf_mul bodies immediately inside c_gf_mul are replaced. The surrounding
control, resets, measured uncomputation and all classical packets are retained.
The 36-wire contract is |a,b,t> -> |a,b,t XOR a*b> for arbitrary t over 0x1053.
"""
import argparse
from collections import Counter
import json
from pathlib import Path
import struct
import subprocess
import sys

import numpy as np

from dqi_gate import sha
from eea_quotient_dqi import instructions, match_template, rewrite
from inverse66_dqi import encode, equal_chunks, prefix_counts, read_ops
from wfs_dqi_single_site import KMB

ROOT = Path(__file__).resolve().parents[1]
REFERENCE_SHA = '655e83ab2ee40d65688e01c883a3804765080c1e47ee4e53f9d7b01bb6621177'
LOCAL_SHA = '32b9341a5d2096efb2cf6deb69eb44c9828e19699ad2278a10afe93222105557'


def reference_template():
    import kickmix as km
    builder = km.CircuitBuilder()
    q = builder.create_quantum_register(36, name='external')
    field = km.GF2Field(12)
    assert field.modulus == 0x1053
    builder.ixor_gf2_mul(q[:12], q[12:24], target=q[24:36], field=field)
    circuit = builder.finish_circuit()
    assert circuit.num_qubits == 36 and circuit.num_bits == 0
    result = instructions(str(circuit))
    assert Counter(op for op, _ in result) == {0x21: 481, 0x22: 21, 0x31: 63}
    return result


def match_product(template, actual):
    qmap, bmap = match_template(template, actual)
    if bmap or set(qmap) != set(range(36)):
        raise ValueError('product must have exactly 36 distinct quantum wires and no classical operands')
    if any(op not in (6, 0x21, 0x22, 0x31) for op, _ in actual):
        raise ValueError('product contains an unproved gate or classical condition')
    return [qmap[q] for q in range(36)]


def find_sites(k):
    payload, _ = k.packets[11]
    count = struct.unpack_from('<Q', k.data, payload)[0]
    ends = np.frombuffer(k.data, dtype='<u8', count=count, offset=payload + 8)
    text = payload + 8 + 8 * count
    positions = np.flatnonzero(k.ops == 6)
    assert len(positions) == count
    previous, stack, sites = 0, [], []
    for i, end in enumerate(ends):
        end = int(end)
        tag = k.data[text + previous:text + end].decode()
        previous = end
        if tag.startswith('@enter:'):
            stack.append((tag[7:], int(positions[i]), i))
        elif tag.startswith('@exit:'):
            name, start, first_tag = stack.pop()
            assert name == tag[6:]
            if name == 'gf_mul' and stack and stack[-1][0] == 'c_gf_mul':
                sites.append({'index': len(sites), 'stage': stack[0][0],
                              'start': start + 1, 'stop': int(positions[i]),
                              'tag_start': first_tag + 1, 'tag_stop': i})
    assert not stack
    assert Counter(s['stage'] for s in sites) == {'forward_eea': 16204, 'reverse_eea': 16204}
    assert all(a['stop'] < b['start'] for a, b in zip(sites, sites[1:]))
    return sites, ends, text


def build(reference, directory, number):
    if sha(reference) != REFERENCE_SHA:
        raise ValueError('expected the verified all-Forney plus all-EEA quotient DQI hash')
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    formal = directory / 'formal'
    subprocess.run([sys.executable, str(ROOT/'research/eea_boolean/multiply_probe.py'),
                    '--tensor', 'public42', '--out', str(formal)],
                   check=True, stdout=subprocess.DEVNULL)
    proof = json.loads((formal/'report.json').read_text())
    variant = proof['variants']['xor']
    assert variant['certificate']['status'] == variant['upstream_certificate']['status'] == 'PASS'
    assert variant['negative_control'] == 'REJECTED'
    assert sha(formal/'multiply-xor.kmx') == variant['kmx_sha256'] == LOCAL_SHA
    local = instructions((formal/'multiply-xor.kmx').read_text())
    assert Counter(op for op, _ in local) == {0x21: 482, 0x31: 42}
    template = reference_template()
    k = KMB(reference)
    assert k.header[1:4] == (1893, 49155, 4165) and k.header[5] == 4484694
    all_sites, tag_ends, tag_text = find_sites(k)
    number = len(all_sites) if number == 'all' else int(number)
    if not 1 <= number <= len(all_sites):
        raise ValueError('invalid number of replacement sites')
    sites = all_sites[:number]
    boundaries = np.asarray(sorted({p for s in sites for p in (s['start'], s['stop'])}))
    rank = {p: prefix_counts(k.ops, boundaries, p) for p in range(2, 10)}
    edits = {p: [] for p in range(1, 10)}
    keep = np.ones(len(tag_ends), dtype=bool)
    removed, manifest = [], []
    for site in sites:
        start, stop = site['start'], site['stop']
        mapping = match_product(template, read_ops(k, start, stop, rank))
        new = [(op, [mapping[q] for q in values]) for op, values in local]
        data = encode(new)
        edits[1].append((start, stop, data[1]))
        for p in range(2, 10):
            if p in (8, 9):
                assert rank[p][start] == rank[p][stop] and data[p] == b''
            else:
                edits[p].append((4*rank[p][start], 4*rank[p][stop], data[p]))
        keep[site['tag_start']:site['tag_stop']] = False
        removed.append((int(tag_ends[site['tag_start']-1]), int(tag_ends[site['tag_stop']-1])))
        manifest.append({**site, 'a': mapping[:12], 'b': mapping[12:24], 'target': mapping[24:],
                         'old_static_toffoli': 63, 'new_static_toffoli': 42,
                         'old_ops': stop-start, 'new_ops': len(new),
                         'arbitrary_target_contract': True, 'classical_operands': 0})
    c, preserved = rewrite(k, directory/'dqi.kmb', edits, keep, tag_ends, tag_text, removed)
    assert c.header[1:4] == k.header[1:4] and c.header[5] == 4484694 - 21*number
    for p in (8, 9):
        old, size = k.packets[p]
        new, new_size = c.packets[p]
        assert size == new_size
        equal_chunks(k.data, old, c.data, new, size)
    (directory/'site-map.json').write_text(json.dumps(manifest, indent=2) + '\n')
    report = {'status': 'PASS', 'scope': 'complete DQI; Forney inverse66, EEA quotient and 42-Toffoli products',
              'reference_dqi_sha256': REFERENCE_SHA, 'sites_replaced': number,
              'available_sites': len(all_sites), 'sites_per_stage': dict(Counter(s['stage'] for s in sites)),
              'candidate_sha256': sha(directory/'dqi.kmb'),
              'candidate_bytes': (directory/'dqi.kmb').stat().st_size,
              'qubits': c.header[1], 'bits': c.header[2], 'registers': c.header[3], 'ops': c.header[4],
              'reference_static_Toffoli_like': k.header[5], 'candidate_static_Toffoli_like': c.header[5],
              'static_Toffoli_saved': 21*number, 'named_registers_unchanged': True,
              'classical_target_and_condition_packets_byte_equal': True,
              'outer_control_resets_and_measured_cleanup_unchanged': True,
              'all_old_instructions_matched_under_injective_renaming': True,
              'unchanged_packet_span_bytes_verified': preserved,
              'retained_metadata_byte_equal': True, 'nested_tags_removed': int(np.count_nonzero(~keep)),
              'local_kmx_sha256': LOCAL_SHA, 'local_formal_proof': variant['certificate'],
              'old_local_formal_proof': variant['upstream_certificate'],
              'tensor_attribution': proof['constants_source'], 'constants_sha256': proof['constants_sha256'],
              'generator_sha256': sha(__file__), 'site_map_sha256': sha(directory/'site-map.json'),
              'kickmix_full_parse': 'NOT_RUN', 'official_DQI_verifier': 'NOT_RUN',
              'score_improvement': 'UNCONFIRMED', 'submits_to_kaggle': False}
    (directory/'integration-report.json').write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps(report, indent=2))


def parse_full(directory):
    import kickmix as km
    directory = Path(directory)
    path = directory/'integration-report.json'
    report = json.loads(path.read_text())
    assert sha(directory/'dqi.kmb') == report['candidate_sha256']
    circuit = km.Circuit.from_file(directory/'dqi.kmb', format='kmb')
    assert (circuit.num_qubits, circuit.num_bits) == (report['qubits'], report['bits'])
    assert circuit.operation_statistics().num_toffoli_like == report['candidate_static_Toffoli_like']
    report['kickmix_full_parse'] = 'PASS'
    path.write_text(json.dumps(report, indent=2) + '\n')
    print('Complete multiply42 candidate Kickmix parse PASS')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--reference', help='Verified EEA-inverse66 full dqi.kmb')
    parser.add_argument('--output', default='build/multiply42')
    parser.add_argument('--sites', default='all')
    parser.add_argument('--parse', action='store_true')
    args = parser.parse_args()
    if args.parse:
        parse_full(args.output)
    elif not args.reference:
        parser.error('--reference is required')
    else:
        build(args.reference, args.output, args.sites)
