#!/usr/bin/env python3
"""Audit the actual pinned caller against the retained-scaffold certificate.

No simulation or submission. Checks every Forney caller's real KMB operands,
including linearity in the inverse output and temporary classical-bit liveness.
"""
import argparse
from collections import Counter
import json
from pathlib import Path
import sys

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[2]/'quantum'))
from inverse66_dqi import find_sites, prefix_counts, read_ops
from wfs_dqi_single_site import BASE_DQI_SHA, KMB
from dqi_gate import sha


def audit(baseline):
    assert sha(baseline) == BASE_DQI_SHA
    k = KMB(baseline)
    sites, _, _ = find_sites(k)
    boundaries = sorted({p for s in sites for p in
                         (s['forward']['start']+1, s['forward']['stop'], s['erase']['start'])})
    rank = {p: prefix_counts(k.ops, np.asarray(boundaries), p) for p in range(2, 10)}
    counts = Counter()
    for site in sites:
        offset = rank[6][site['forward']['start']+1]
        outputs = set(map(int, k.array(6)[offset:offset+12]))
        written = set()
        for op, values in read_ops(k, site['forward']['stop'], site['erase']['start'], rank):
            nq = (op >> 4) & 3
            inverse_operands = outputs.intersection(values[:nq])
            if inverse_operands:
                # Exactly one y variable per phase term: Phi_z is linear in y.
                assert op in (0x10, 0x90, 0x20, 0xa0, 0x30, 0xb0)
                assert len(inverse_operands) == 1
                counts['linear_inverse_phase_operations'] += 1
            if op & 128:
                condition = values[-1]
                if condition >= 49140:
                    # No inverse-measurement outcome may leak into the caller.
                    assert condition in written
            if op & 64:
                target = values[nq]
                assert target >= 49140 and target != 49153
                if op == 0xc2:  # BIT_INVERT_IF reads its target before writing.
                    assert target in written
                elif op not in (0x40, 0x41, 0x50):
                    raise AssertionError(f'unsupported classical write {op:#x}')
                if not op & 128:
                    written.add(target)
            counts[f'op_{op:02x}'] += 1
    return {'status': 'PASS', 'baseline_dqi_sha256': BASE_DQI_SHA,
            'sites_audited': len(sites),
            'inverse_output_phase_degree': 1,
            'reads_of_old_inverse_temporary_records': 0,
            'caller_writes_to_mask_or_guard': 0,
            'counts': dict(counts),
            'scope': 'actual pinned caller operands; complements local ANF and integration checks',
            'submits_to_kaggle': False}


def audit_metadata(baseline, candidate):
    assert sha(baseline) == BASE_DQI_SHA
    checksum = sha(candidate)
    assert checksum == 'ea0d6717e7b37fb386a0d99730eebf150c0e78de1cc8547f0727c2f6845a99bc'
    base, cand = KMB(baseline), KMB(candidate)
    sites, ends, text = find_sites(base)
    csites, cends, ctext = find_sites(cand)
    keep = np.ones(len(ends), dtype=bool)
    for site in sites:
        for kind in ('forward', 'erase'):
            region = site[kind]
            keep[region['tag_start']:region['tag_stop']] = False
    cursor = candidate_cursor = ci = 0
    for i, end in enumerate(ends):
        end = int(end)
        if keep[i]:
            cend = int(cends[ci])
            assert base.data[text+cursor:text+end] == cand.data[ctext+candidate_cursor:ctext+cend]
            candidate_cursor = cend
            ci += 1
        cursor = end
    assert ci == len(cends)
    return {'status': 'PASS', 'candidate_sha256': checksum,
            'forney_pairs': len(csites), 'balanced_outer_INFO_tags': True,
            'retained_INFO_tags_byte_equal': int(ci),
            'removed_nested_INFO_tags': int(len(ends)-ci)}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('baseline_dqi')
    parser.add_argument('--out', required=True)
    parser.add_argument('--candidate', help='Optional all-site candidate for exact metadata audit')
    args = parser.parse_args()
    result = audit(args.baseline_dqi)
    Path(args.out).write_text(json.dumps(result, indent=2)+'\n')
    if args.candidate:
        metadata = audit_metadata(args.baseline_dqi, args.candidate)
        Path(args.out).with_name('metadata-audit.json').write_text(json.dumps(metadata, indent=2)+'\n')
    print(json.dumps(result, indent=2))
