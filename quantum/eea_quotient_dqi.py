#!/usr/bin/env python3
"""Replace verified EEA quotient blocks in the full Forney-inverse66 DQI.

Pins the input hash. Matches every old instruction to the public generator under
an injective operand renaming. Proves old temporary measurement bits dead at each
exit. Preserves register packets, outer conditions and every unedited KMB span.
"""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import struct
import subprocess
import sys

import numpy as np

from dqi_gate import sha
from inverse66_dqi import encode, equal_chunks, prefix_counts, read_ops
from wfs_dqi_single_site import KMB, stream_copy, targets

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'research/eea_boolean'))
from quotient_probe import parse as parse_local

REFERENCE_SHA = 'ea0d6717e7b37fb386a0d99730eebf150c0e78de1cc8547f0727c2f6845a99bc'
OPS = {'CX': 0x21, 'CCX': 0x31, 'CZ': 0x20, 'Z': 0x10, 'SWAP': 0x22,
       'R': 0x12, 'HMR': 0x50, 'BIT_STORE0': 0x40, 'BIT_INVERT': 0x42}
PRIVATE_START, PRIVATE_STOP = 49140, 49153


def instructions(text):
    return [(OPS[gate] | (128 if condition is not None else 0),
             operands + ([] if condition is None else [condition]))
            for gate, operands, condition in parse_local(text)]


def reference_template():
    import kickmix as km
    builder = km.CircuitBuilder()
    a = builder.create_quantum_register(12, name='numerator')
    b = builder.create_quantum_register(12, name='denominator')
    t = builder.create_quantum_register(12, name='target')
    c = builder.create_quantum_register(1, name='control')[0]
    field = km.GF2Field(12)
    assert field.modulus == 0x1053
    ratio, scaffold = builder.init_gf2_div_with_scaffold(a, b, field=field)
    builder.gf2_iadd(ratio, target=t, field=field, control=c)
    builder.del_gf2_div_with_scaffold(a, b, target=ratio, scaffold=scaffold, field=field)
    builder.free(scaffold + ratio)
    circuit = builder.finish_circuit()
    assert circuit.num_qubits == 109 and circuit.num_bits == 13
    return instructions(str(circuit))


def match_template(template, actual):
    """Reject missing/changed instructions, aliases and inconsistent renamings."""
    actual = [(op, values) for op, values in actual if op != 6]
    if len(actual) != len(template):
        raise ValueError('template instruction count differs')
    qmap, bmap = {}, {}
    qreverse, breverse = {}, {}
    for (op, expected), (got, values) in zip(template, actual):
        if op != got or len(expected) != len(values):
            raise ValueError('template opcode or arity differs')
        nq = (op >> 4) & 3
        for i, (old, new) in enumerate(zip(expected, values)):
            mapping, reverse = (qmap, qreverse) if i < nq else (bmap, breverse)
            if mapping.get(old, new) != new or reverse.get(new, old) != old:
                raise ValueError('template operand renaming is inconsistent or aliased')
            mapping[old], reverse[new] = new, old
    return qmap, bmap


def template_variants(template):
    """The only optional instruction initializes the fresh/reused parity bit."""
    first = next(i for i, (op, values) in enumerate(template)
                 if (op & 64 and values[(op >> 4) & 3] == 12)
                 or (op & 128 and values[-1] == 12))
    assert template[first][0] == 0xc2 and template[first][1][0] == 12
    return [('fresh_parity', template),
            ('reused_parity', template[:first] + [(0x40, [12])] + template[first:])]


def match_variants(variants, actual):
    errors = []
    for name, template in variants:
        try:
            qmap, bmap = match_template(template, actual)
            return name, qmap, bmap
        except ValueError as error:
            errors.append(str(error))
    raise ValueError('neither proved reference variant matches: ' + '; '.join(errors))


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
            if name == 'quotient_div':
                sites.append({'index': len(sites), 'stage': stack[0][0],
                              'start': start + 1, 'stop': int(positions[i]),
                              'tag_start': first_tag + 1, 'tag_stop': i})
    assert not stack and Counter(s['stage'] for s in sites) == {'forward_eea': 444, 'reverse_eea': 444}
    return sites, ends, text


def bit_mask(bit):
    return 1 << (bit - PRIVATE_START) if bit is not None and PRIVATE_START <= bit < PRIVATE_STOP else 0


def backward_live_step(op, target, condition, live, stack):
    """Conservative may-liveness, including the skipped path of each condition."""
    if op == 0x01:  # POP_CONDITION: remember the branch's skipped path.
        stack.append(live)
    elif op == 0x81:  # PUSH_CONDITION: join skipped and executed paths.
        if not stack:
            raise ValueError('unbalanced condition stack')
        live |= stack.pop()
    elif op & 64:
        base = op & 127
        if base in (0x40, 0x41, 0x50):
            if not op & 128:
                live &= ~bit_mask(target)
        elif base == 0x42:
            live |= bit_mask(target)
        else:
            raise ValueError(f'unsupported classical write {op:#x}')
    if op & 128:
        live |= bit_mask(condition)
    return live


def audit_liveness(k, sites):
    # All classical reads/writes and POPs, without scanning irrelevant quantum gates in Python.
    events = np.flatnonzero(((k.ops & 192) != 0) | (k.ops == 1))
    wanted = {}
    for s in sites:
        wanted.setdefault(int(np.searchsorted(events, s['stop'])), []).append(s['index'])
    target_pos, condition_pos = len(k.array(8)), len(k.array(9))
    live, stack, result = 0, [], {}
    for index in wanted.get(len(events), []):
        result[index] = 0
    for i in range(len(events) - 1, -1, -1):
        op = int(k.ops[events[i]])
        target = condition = None
        if op & 64:
            target_pos -= 1
            target = int(k.array(8)[target_pos])
        if op & 128:
            condition_pos -= 1
            condition = int(k.array(9)[condition_pos])
        live = backward_live_step(op, target, condition, live, stack)
        for index in wanted.get(i, []):
            result[index] = live
    assert not stack and target_pos == condition_pos == 0 and len(result) == len(sites)
    return result


def rewrite(k, output, edits, kept_tags, tag_ends, tag_text, removed_ranges):
    head = bytearray(k.data[:104])
    for index, (packet, width) in enumerate([(1, 1), (2, 4), (5, 4), (7, 4), (8, 4), (9, 4)]):
        delta = sum(len(v) - (b-a) for a, b, v in edits[packet]) // width
        struct.pack_into('<Q', head, 32 + 8 * index, k.header[4 + index] + delta)
    lengths = np.diff(np.r_[np.uint64(0), tag_ends])
    new_ends = np.cumsum(lengths[kept_tags], dtype='<u8')
    new_chars = int(new_ends[-1])
    struct.pack_into('<Q', head, 88, len(new_ends))
    struct.pack_into('<Q', head, 96, new_chars)
    with output.open('wb') as dst:
        dst.write(head)
        stream_copy(dst, k.data, 104, k.packets[1][0] - 16)
        for p in range(1, 12):
            original, size = k.packets[p]
            if p == 11:
                dst.write(struct.pack('<QQQ', 11, 8 + 8 * len(new_ends) + new_chars, len(new_ends)))
                dst.write(new_ends.tobytes())
                cursor = 0
                for a, b in removed_ranges:
                    stream_copy(dst, k.data, tag_text + cursor, tag_text + a)
                    cursor = b
                stream_copy(dst, k.data, tag_text + cursor, tag_text + int(tag_ends[-1]))
                continue
            changes = edits.get(p, [])
            dst.write(struct.pack('<QQ', p, size + sum(len(v)-(b-a) for a, b, v in changes)))
            cursor = 0
            for a, b, value in changes:
                assert cursor <= a <= b <= size
                stream_copy(dst, k.data, original + cursor, original + a)
                dst.write(value)
                cursor = b
            stream_copy(dst, k.data, original + cursor, original + size)

    c = KMB(output)
    assert c.registers == k.registers and c.header[:4] == k.header[:4]
    equal_chunks(k.data, 104, c.data, 104, k.packets[1][0] - 16 - 104)
    preserved = 0
    for p in range(1, 11):
        old, size = k.packets[p]
        new, new_size = c.packets[p]
        old_cursor = new_cursor = 0
        for a, b, value in edits.get(p, []):
            length = a - old_cursor
            equal_chunks(k.data, old + old_cursor, c.data, new + new_cursor, length)
            preserved += length
            new_cursor += length
            assert c.data[new + new_cursor:new + new_cursor + len(value)] == value
            new_cursor += len(value)
            old_cursor = b
        equal_chunks(k.data, old + old_cursor, c.data, new + new_cursor, size - old_cursor)
        preserved += size - old_cursor
        assert new_cursor + size - old_cursor == new_size
    # Compare every retained metadata string as well as opcode/operand spans.
    cp, _ = c.packets[11]
    actual_count = struct.unpack_from('<Q', c.data, cp)[0]
    assert actual_count == len(new_ends)
    actual_ends = np.frombuffer(c.data, dtype='<u8', count=actual_count, offset=cp + 8)
    assert np.array_equal(actual_ends, new_ends)
    ct = cp + 8 + 8 * actual_count
    previous = cprevious = ci = 0
    for keep, end in zip(kept_tags, tag_ends):
        end = int(end)
        if keep:
            cend = int(actual_ends[ci])
            assert k.data[tag_text+previous:tag_text+end] == c.data[ct+cprevious:ct+cend]
            cprevious, ci = cend, ci + 1
        previous = end
    return c, preserved


def build(reference, directory, number):
    if sha(reference) != REFERENCE_SHA:
        raise ValueError('expected the verified all-Forney inverse66 DQI hash')
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    formal = directory / 'formal'
    subprocess.run([sys.executable, str(ROOT/'research/eea_boolean/quotient_probe.py'),
                    '--out', str(formal)], check=True, stdout=subprocess.DEVNULL)
    proof = json.loads((formal/'quotient-local-report.json').read_text())
    assert proof['certificate']['status'] == proof['baseline_certificate']['status'] == 'PASS'
    assert proof['baseline_reused_parity_certificate']['status'] == 'PASS'
    local = instructions((formal/'quotient-local.kmx').read_text())
    template = reference_template()
    variants = template_variants(template)
    k = KMB(reference)
    all_sites, tag_ends, tag_text = find_sites(k)
    number = len(all_sites) if number == 'all' else int(number)
    assert 1 <= number <= len(all_sites)
    sites = all_sites[:number]
    live = audit_liveness(k, sites)
    boundaries = np.asarray(sorted({p for s in sites for p in (s['start'], s['stop'])}))
    rank = {p: prefix_counts(k.ops, boundaries, p) for p in range(2, 10)}
    pushes, pops = np.flatnonzero(k.ops == 0x81), np.flatnonzero(k.ops == 0x01)
    edits = {p: [] for p in range(1, 10)}
    keep = np.ones(len(tag_ends), dtype=bool)
    removed, manifest = [], []
    for site in sites:
        start, stop = site['start'], site['stop']
        assert np.searchsorted(pushes, start) == np.searchsorted(pops, start)
        assert not np.any((k.ops[start:stop] == 0x81) | (k.ops[start:stop] == 0x01))
        actual = read_ops(k, start, stop, rank)
        variant, qmap, bmap = match_variants(variants, actual)
        assert set(qmap) == set(range(109)) and set(bmap) == set(range(13))
        assert set(bmap.values()) == set(range(PRIVATE_START, PRIVATE_STOP))
        assert live[site['index']] == 0, 'old measurement record remains live after quotient'
        # The old 72 entry resets are preserved, including the unused 27 scaffold wires.
        assert template[:72] == [(0x12, [q]) for q in range(37, 109)]
        mapping = ([qmap[i] for i in range(12, 24)] + [qmap[i] for i in range(49, 61)]
                   + [qmap[i] for i in range(61, 82)] + [qmap[i] for i in range(12)]
                   + [qmap[i] for i in range(37, 49)] + [qmap[i] for i in range(24, 36)]
                   + [qmap[36]])
        assert len(mapping) == len(set(mapping)) == 82
        new = [(0x12, [qmap[q]]) for q in range(37, 109)]
        for op, values in local:
            nq = (op >> 4) & 3
            new.append((op, [mapping[v] if i < nq else bmap[v] for i, v in enumerate(values)]))
        assert sum(((op >> 4) & 3) == 3 for op, _ in new) == 141
        assert sum(((op >> 4) & 3) == 3 for op, _ in actual) == 390
        data = encode(new)
        edits[1].append((start, stop, data[1]))
        for p in range(2, 10):
            edits[p].append((4*rank[p][start], 4*rank[p][stop], data[p]))
        keep[site['tag_start']:site['tag_stop']] = False
        removed.append((int(tag_ends[site['tag_start']-1]), int(tag_ends[site['tag_stop']-1])))
        manifest.append({**site, 'reference_template': variant,
                         'canonical_old_qubit_map': qmap, 'temporary_bit_map': bmap,
                         'new_local_qubit_map': mapping, 'old_measurement_bits_live_on_exit': [],
                         'old_static_toffoli': 390, 'new_static_toffoli': 141,
                         'preserved_entry_resets': 72, 'old_ops': stop-start, 'new_ops': len(new)})
    c, preserved = rewrite(k, directory/'dqi.kmb', edits, keep, tag_ends, tag_text, removed)
    assert c.header[1:4] == (1893, 49155, 4165)
    assert c.header[5] == 4705806 - 249*number
    (directory/'site-map.json').write_text(json.dumps(manifest, indent=2) + '\n')
    report = {'status': 'PASS', 'scope': 'complete DQI; Forney inverse66 plus EEA quotient replacements',
              'reference_dqi_sha256': REFERENCE_SHA, 'sites_replaced': number,
              'candidate_sha256': sha(directory/'dqi.kmb'),
              'candidate_bytes': (directory/'dqi.kmb').stat().st_size,
              'qubits': c.header[1], 'bits': c.header[2], 'registers': c.header[3], 'ops': c.header[4],
              'reference_static_Toffoli_like': k.header[5], 'candidate_static_Toffoli_like': c.header[5],
              'static_Toffoli_saved': 249*number, 'named_registers_unchanged': True,
              'outer_classical_conditions_preserved': True,
              'all_old_instructions_matched_under_injective_renaming': True,
              'matched_reference_variants': dict(Counter(s['reference_template'] for s in manifest)),
              'old_measurement_record_liveness': 'PASS',
              'unchanged_packet_span_bytes_verified': preserved,
              'retained_metadata_byte_equal': True, 'nested_tags_removed': int(np.count_nonzero(~keep)),
              'local_formal_proof': proof['certificate'], 'old_local_formal_proof': proof['baseline_certificate'],
              'old_reused_parity_formal_proof': proof['baseline_reused_parity_certificate'],
              'generator_sha256': sha(__file__),
              'kickmix_full_parse': 'NOT_RUN', 'official_DQI_verifier': 'NOT_RUN',
              'score_improvement': 'UNCONFIRMED', 'submits_to_kaggle': False}
    (directory/'integration-report.json').write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps(report, indent=2))


def parse_full(directory):
    import kickmix as km
    directory = Path(directory)
    report_path = directory/'integration-report.json'
    report = json.loads(report_path.read_text())
    assert sha(directory/'dqi.kmb') == report['candidate_sha256']
    circuit = km.Circuit.from_file(directory/'dqi.kmb', format='kmb')
    assert circuit.num_qubits == report['qubits'] and circuit.num_bits == report['bits']
    assert circuit.operation_statistics().num_toffoli_like == report['candidate_static_Toffoli_like']
    report['kickmix_full_parse'] = 'PASS'
    report_path.write_text(json.dumps(report, indent=2) + '\n')
    print('Complete EEA quotient candidate Kickmix parse PASS')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--reference', help='Verified Forney-inverse66 dqi.kmb')
    parser.add_argument('--output', default='build/eea-quotient')
    parser.add_argument('--sites', default='all')
    parser.add_argument('--parse', action='store_true')
    args = parser.parse_args()
    if args.parse:
        parse_full(args.output)
    elif not args.reference:
        parser.error('--reference is required')
    else:
        build(args.reference, args.output, args.sites)
