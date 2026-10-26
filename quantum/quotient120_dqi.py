#!/usr/bin/env python3
"""Upgrade 141-Toffoli quotient blocks in the pinned multiply42 complete DQI.

Match the entire old block, then change only its pure product. Every reset,
coherent XOR, measurement, phase correction and classical instruction survives.
"""
import argparse
from collections import Counter
import json
from pathlib import Path
import subprocess
import sys
import time

import numpy as np

from dqi_gate import sha
from eea_quotient_dqi import instructions, match_template, rewrite, find_sites
from inverse66_dqi import encode, equal_chunks, prefix_counts, read_ops
from multiply42_dqi import parse_full
from wfs_dqi_single_site import KMB

ROOT = Path(__file__).resolve().parents[1]
REFERENCE_SHA = '252b41714f6147723e44082e4a4f75d84b34b5aa4b23e8c47ce096667caa75e9'
OLD_LOCAL_SHA = '85132c3cdc060f876befe232ddc7dabb6adbcc30e0718d71baabbd4d3920f5dd'
NEW_LOCAL_SHA = '331248213b410308e6691decf12c0dca21886e500e4895dab571a42c439b0876'


def match_quotient(template, actual):
    qmap, bmap = match_template(template, actual)
    if set(qmap) != set(range(109)) or set(bmap) != set(range(13)):
        raise ValueError('quotient must contain 109 distinct quantum and 13 classical wires')
    if set(bmap.values()) != set(range(49140, 49153)):
        raise ValueError('unexpected temporary classical registers')
    return qmap, bmap


def build(reference, directory, number):
    started = time.monotonic()
    if sha(reference) != REFERENCE_SHA:
        raise ValueError('expected the validated all-multiply42 complete DQI')
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    formal = directory/'formal'
    subprocess.run([sys.executable, str(ROOT/'research/eea_boolean/quotient120_probe.py'),
                    '--out', str(formal)], check=True, stdout=subprocess.DEVNULL)
    proof = json.loads((formal/'report.json').read_text())
    assert proof['certificate']['status'] == proof['prior_local_certificate']['status'] == 'PASS'
    assert sha(formal/'reference/quotient-local.kmx') == OLD_LOCAL_SHA
    assert sha(formal/'quotient120.kmx') == NEW_LOCAL_SHA
    old = instructions((formal/'reference/quotient-local.kmx').read_text())
    new = instructions((formal/'quotient120.kmx').read_text())
    start, stop = proof['old_product_span']
    replacement_length = len(new) - (len(old) - (stop-start))
    end = start + replacement_length
    assert old[:start] == new[:start] and old[stop:] == new[end:]
    assert Counter(op for op, _ in old[start:stop]) == {0x21:481, 0x22:21, 0x31:63}
    assert Counter(op for op, _ in new[start:end]) == {0x21:482, 0x31:42}
    # Canonical 82-wire layout, extended by the old 27 unused scaffold wires.
    resets = [(0x12, [q]) for q in
              list(range(57,69))+list(range(12,45))+list(range(82,109))]
    assert len(resets) == 72
    template = resets + old
    k = KMB(reference)
    assert k.header[1:4] == (1893, 49155, 4165) and k.header[5] == 3804126
    sites, tag_ends, tag_text = find_sites(k)
    available = len(sites)
    number = available if number == 'all' else int(number)
    if not 1 <= number <= available:
        raise ValueError('invalid site count')
    selected = sites[:number]
    boundaries = np.asarray(sorted({p for s in sites for p in (s['start'],s['stop'])}))
    ranks = {p:prefix_counts(k.ops, boundaries, p) for p in range(2,10)}
    pushes, pops = np.flatnonzero(k.ops == 0x81), np.flatnonzero(k.ops == 0x01)
    edits = {p:[] for p in range(1,10)}
    manifest = []
    # Audit every caller even for the one-site candidate. Only selected sites change.
    for site in sites:
        a,b = site['start'],site['stop']
        assert np.searchsorted(pushes,a) == np.searchsorted(pops,a), 'outer classical condition'
        assert not np.any((k.ops[a:b] == 0x81) | (k.ops[a:b] == 0x01))
        actual = read_ops(k,a,b,ranks)
        qmap,bmap = match_quotient(template,actual)
        # The prior integration removed all inner tags; reject unexpected metadata.
        assert len(actual) == len(template) and site['tag_start'] == site['tag_stop']
        assert sum(((op>>4)&3)==3 for op,_ in actual) == 141
        if site['index'] >= number:
            continue
        pstart,pstop = a+len(resets)+start,a+len(resets)+stop
        new_product = [(op,[qmap[q] for q in values]) for op,values in new[start:end]]
        data = encode(new_product)
        # Counts at the two inner boundaries, computed within this small block.
        for p in range(2,10):
            local_ops = k.ops[a:b]
            nq = (local_ops>>4)&3
            mask = (nq==3) if p in (2,3,4) else ((nq==2) if p in (5,6) else
                   ((nq==1) if p==7 else ((local_ops&64)!=0 if p==8 else (local_ops&128)!=0)))
            values = np.flatnonzero(mask)
            lo = ranks[p][a] + int(np.searchsorted(values,pstart-a))
            hi = ranks[p][a] + int(np.searchsorted(values,pstop-a))
            if p in (8,9):
                assert lo == hi and data[p] == b''
            else:
                edits[p].append((4*lo,4*hi,data[p]))
        edits[1].append((pstart,pstop,data[1]))
        manifest.append({**site,'product_start':pstart,'product_stop':pstop,
            'denominator':[qmap[i] for i in range(12)],
            'numerator':[qmap[i] for i in range(45,57)],
            'target':[qmap[i] for i in range(69,81)],'coherent_control':qmap[81],
            'inverse':[qmap[i] for i in range(12,24)],
            'product':[qmap[i] for i in range(57,69)],
            'canonical_qubit_map':qmap,'temporary_bit_map':bmap,
            'old_static_toffoli':141,'new_static_toffoli':120})
    keep = np.ones(len(tag_ends),dtype=bool)
    c,preserved = rewrite(k,directory/'dqi.kmb',edits,keep,tag_ends,tag_text,[])
    assert c.header[1:4] == k.header[1:4] and c.header[5] == 3804126-21*number
    for p in (8,9,11):
        old_offset,size = k.packets[p]
        new_offset,new_size = c.packets[p]
        assert size == new_size
        equal_chunks(k.data,old_offset,c.data,new_offset,size)
    (directory/'site-map.json').write_text(json.dumps(manifest,indent=2)+'\n')
    report = {'status':'PASS','scope':'complete DQI; multiply42 plus quotient120',
        'reference_dqi_sha256':REFERENCE_SHA,'candidate_sha256':sha(directory/'dqi.kmb'),
        'candidate_bytes':(directory/'dqi.kmb').stat().st_size,
        'qubits':c.header[1],'bits':c.header[2],'registers':c.header[3],'ops':c.header[4],
        'reference_static_Toffoli_like':3804126,'candidate_static_Toffoli_like':c.header[5],
        'static_Toffoli_saved':21*number,'sites_replaced':number,'available_sites':available,
        'sites_per_stage':dict(Counter(s['stage'] for s in selected)),
        'all_888_full_141_blocks_matched_injectively':True,
        'only_pure_product_changed':True,'all_resets_controls_measurement_cleanup_preserved':True,
        'classical_target_condition_and_metadata_packets_byte_equal':True,
        'unchanged_packet_span_bytes_verified':preserved,'named_registers_unchanged':True,
        'local_formal_proof':proof['certificate'],'old_local_formal_proof':proof['prior_local_certificate'],
        'local_kmx_sha256':NEW_LOCAL_SHA,'generator_sha256':sha(__file__),
        'site_map_sha256':sha(directory/'site-map.json'),
        'generation_elapsed_seconds':round(time.monotonic()-started,2),
        'kickmix_full_parse':'NOT_RUN','official_DQI_verifier':'NOT_RUN',
        'score_improvement':'UNCONFIRMED','submits_to_kaggle':False}
    (directory/'integration-report.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(report,indent=2))


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--reference')
    p.add_argument('--output',default='build/quotient120')
    p.add_argument('--sites',default='1')
    p.add_argument('--parse',action='store_true')
    args = p.parse_args()
    if args.parse:
        parse_full(args.output)
    elif not args.reference:
        p.error('--reference is required')
    else:
        build(args.reference,args.output,args.sites)
