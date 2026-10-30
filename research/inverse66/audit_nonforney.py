#!/usr/bin/env python3
"""Strict nested-tag partition and actual-operand audit. Never submits to Kaggle."""
import argparse
from collections import Counter, defaultdict
import gzip
import json
from pathlib import Path
import struct
import sys

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'quantum'))
from dqi_gate import sha
from wfs_dqi_single_site import BASE_DQI_SHA, KMB
from inverse66_dqi import prefix_counts, read_ops
from eea_quotient_dqi import (REFERENCE_SHA, audit_liveness, find_sites,
                             match_variants, reference_template, template_variants)


def nested(circuit):
    p, size = circuit.packets[11]
    count = struct.unpack_from('<Q', circuit.data, p)[0]
    ends = np.frombuffer(circuit.data, dtype='<u8', count=count, offset=p + 8)
    text = p + 8 + 8 * count
    assert size == 8 + 8 * count + int(ends[-1])
    positions = np.flatnonzero(circuit.ops == 6)
    assert len(positions) == count
    triple_positions = np.flatnonzero(((circuit.ops >> 4) & 3) == 3)
    ranks = np.searchsorted(triple_positions, positions)
    stack, regions, paths = [], [], Counter()
    previous = max_depth = 0
    names = {'gf_inverse_chain', 'gf_uninverse_chain', 'forney_step', 'quotient_div'}
    for i, end in enumerate(ends):
        end = int(end)
        tag = circuit.data[text + previous:text + end].decode()
        previous = end
        if tag.startswith('@enter:'):
            stack.append((tag[7:], int(positions[i]), int(ranks[i])))
            max_depth = max(max_depth, len(stack))
        elif tag.startswith('@exit:'):
            assert stack, 'exit without enter'
            name, start, cost_start = stack.pop()
            assert name == tag[6:], 'mismatched nested INFO_TAG'
            if name in names:
                ancestry = [x[0] for x in stack]
                owner = next(((n, s) for n, s, _ in reversed(stack)
                              if n in ('forney_step', 'quotient_div')), None)
                regions.append({'name': name, 'start': start, 'stop': int(positions[i]) + 1,
                                'toffoli_like': int(ranks[i]) - cost_start,
                                'ancestry': ancestry, 'owner': owner})
                if name == 'gf_inverse_chain':
                    paths[tuple(ancestry)] += 1
    assert not stack
    return regions, {'tags': count, 'max_depth': max_depth, 'balanced': True,
                     'inverse_ancestry_counts': [{'path': list(k), 'count': v}
                                                 for k, v in sorted(paths.items())]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--baseline', required=True)
    parser.add_argument('--reference', required=True)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    assert sha(args.baseline) == BASE_DQI_SHA
    assert sha(args.reference) == REFERENCE_SHA
    baseline, reference = KMB(args.baseline), KMB(args.reference)
    regions, tree = nested(baseline)
    by_owner = defaultdict(dict)
    containers = {}
    for r in regions:
        if r['name'] in ('forney_step', 'quotient_div'):
            containers[(r['name'], r['start'])] = r
        else:
            assert r['owner'] is not None
            key = tuple(r['owner'])
            assert r['name'] not in by_owner[key]
            by_owner[key][r['name']] = r
    partition = Counter()
    inventory = []
    for key, pair in sorted(by_owner.items(), key=lambda item: item[0][1]):
        assert set(pair) == {'gf_inverse_chain', 'gf_uninverse_chain'}
        forward, erase = pair['gf_inverse_chain'], pair['gf_uninverse_chain']
        container = containers[key]
        assert container['start'] < forward['start'] < forward['stop'] <= erase['start'] < erase['stop'] < container['stop']
        assert forward['toffoli_like'] == 315 and erase['toffoli_like'] == 0
        partition[key[0]] += 1
        inventory.append({'owner': key[0], 'stage': container['ancestry'][0],
                          'container': [container['start'], container['stop']],
                          'inverse': [forward['start'], forward['stop']],
                          'erase': [erase['start'], erase['stop']]})
    assert partition == {'forney_step': 4095, 'quotient_div': 888}
    assert sum(r['name'] == 'gf_inverse_chain' for r in regions) == 4983
    assert Counter(x['stage'] for x in inventory if x['owner'] == 'quotient_div') == {'forward_eea': 444, 'reverse_eea': 444}
    reference_regions, reference_tree = nested(reference)
    assert Counter(r['name'] for r in reference_regions) == {
        'forney_step': 4095, 'quotient_div': 888,
        'gf_inverse_chain': 4983, 'gf_uninverse_chain': 4983}
    assert Counter((r['owner'][0], r['toffoli_like']) for r in reference_regions
                   if r['name'] == 'gf_inverse_chain') == {
                       ('forney_step', 66): 4095, ('quotient_div', 315): 888}
    sites, _, _ = find_sites(reference)
    live = audit_liveness(reference, sites)
    boundaries = np.asarray(sorted({p for s in sites for p in (s['start'], s['stop'])}))
    rank = {p: prefix_counts(reference.ops, boundaries, p) for p in range(2, 10)}
    variants = template_variants(reference_template())
    details, variants_count = [], Counter()
    pushes = np.flatnonzero(reference.ops == 0x81)
    pops = np.flatnonzero(reference.ops == 0x01)
    for s in sites:
        actual = read_ops(reference, s['start'], s['stop'], rank)
        variant, qm, bm = match_variants(variants, actual)
        assert len(qm) == len(set(qm.values())) == 109
        assert len(bm) == len(set(bm.values())) == 13
        assert live[s['index']] == 0
        assert not any(op in (0x81, 0x01) for op, _ in actual)
        assert np.searchsorted(pushes, s['start']) == np.searchsorted(pops, s['start'])
        # Extract the original caller between inverse compute and inverse erase.
        pair = next(r for r in reference_regions if r['name'] == 'quotient_div' and r['start'] == s['start'] - 1)
        inner = [r for r in reference_regions if r['owner'] == ('quotient_div', pair['start'])]
        f = next(r for r in inner if r['name'] == 'gf_inverse_chain')
        e = next(r for r in inner if r['name'] == 'gf_uninverse_chain')
        middle = actual[f['stop'] - s['start']:e['start'] - s['start']]
        touched = {q for op, vals in middle for q in vals[:(op >> 4) & 3]}
        dirty = sorted(touched & {qm[i] for i in range(61, 109)})
        writes = []
        for op, vals in middle:
            nq, base = (op >> 4) & 3, op & 127
            if nq == 3 and base == 0x31:
                writes.extend(vals[2:3])
            elif nq == 2 and base == 0x21:
                writes.extend(vals[1:2])
            elif nq == 2 and base == 0x22:
                writes.extend(vals[:2])
            elif nq == 1 and base in (0x11, 0x12, 0x50):
                writes.extend(vals[:1])
        inverse_writes = sum(q in {qm[i] for i in range(49, 61)} for q in writes)
        assert not dirty and inverse_writes == 84
        assert not (touched & {qm[i] for i in range(12, 24)})
        variants_count[variant] += 1
        details.append({'index': s['index'], 'stage': s['stage'],
                        'reference_interval': [s['start'], s['stop']],
                        'numerator': [qm[i] for i in range(12)],
                        'denominator': [qm[i] for i in range(12, 24)],
                        'xor_target': [qm[i] for i in range(24, 36)],
                        'coherent_control': qm[36],
                        'product': [qm[i] for i in range(37, 49)],
                        'inverse_output': [qm[i] for i in range(49, 61)],
                        'old_inverse_scaffold': [qm[i] for i in range(61, 109)],
                        'old_caller_scaffold_wires_accessed': dirty,
                        'old_caller_inverse_output_write_operations': inverse_writes,
                        'temporary_bits': [bm[i] for i in range(13)],
                        'old_measurement_bits_live_on_exit': [],
                        'template': variant,
                        'classification': '66+0 after rebuilding entire quotient caller; isolated swap not certified'})
    report = {'status': 'PASS', 'baseline_sha256': BASE_DQI_SHA,
              'forney_reference_sha256': REFERENCE_SHA,
              'baseline_nested_tags': tree, 'reference_nested_tags': reference_tree,
              'inverse_partition': dict(partition),
              'paired_forward_erase_regions': 4983,
              'nonforney_by_stage': {'forward_eea': 444, 'reverse_eea': 444},
              'all_888_actual_operand_templates': 'PASS',
              'template_variants': dict(variants_count),
              'all_888_measurement_liveness': 'PASS',
              'old_caller_scaffold_access_count_histogram': dict(Counter(len(x['old_caller_scaffold_wires_accessed']) for x in details)),
              'classification_counts': {'retained_66_plus_0_with_rebuilt_quotient': 888,
                                        'requires_66_plus_66': 0, 'unsupported': 0},
              'isolated_inverse_only_drop_in': 'NOT_CERTIFIED by phase-only Forney contract: caller temporarily writes inverse output 84 times. Dirty scaffold is offered by source but no scaffold wire is accessed in these 888 actual callers. Composite quotient proof is used.',
              'complete_quotient_toffoli': {'old': 390, 'retained': 141,
                                           'clean_twice_alternative_unimplemented': 207},
              'static_additional_saving': 221112,
              'all_site_static_toffoli': 4484694,
              'kaggle_submission': 'NOT_RUN'}
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / 'nested-inverse-inventory.json').write_text(json.dumps(inventory, separators=(',', ':')) + '\n')
    (args.out / 'nonforney-site-map.json').write_text(json.dumps(details, separators=(',', ':')) + '\n')
    (args.out / 'nonforney-audit.json').write_text(json.dumps(report, indent=2) + '\n')
    for name in ('nested-inverse-inventory.json', 'nonforney-site-map.json'):
        path = args.out / name
        path.with_suffix('.json.gz').write_bytes(gzip.compress(path.read_bytes(), mtime=0))
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
