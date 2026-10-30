#!/usr/bin/env python3
"""Prove the next local quotient variant; does not modify the current full DQI."""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import subprocess
import sys

from quotient_probe import ROOT, inverse_anf, parse, verify
from multiply_probe import decomposition, xor_product


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    import kickmix as km
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--out', type=Path, default=Path(__file__).with_name('quotient120-local'))
    args = p.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    reference = args.out/'reference'
    subprocess.run([sys.executable, str(ROOT/'research/eea_boolean/quotient_probe.py'),
                    '--out', str(reference)], check=True, stdout=subprocess.DEVNULL)
    old = parse((reference/'quotient-local.kmx').read_text())
    report = json.loads((reference/'quotient-local-report.json').read_text())
    assert report['certificate']['status'] == 'PASS'
    assert report['local_kmx_sha256'] == '85132c3cdc060f876befe232ddc7dabb6adbcc30e0718d71baabbd4d3920f5dd'
    mapping = list(range(45,57)) + list(range(12,24)) + list(range(57,69))
    builder = km.CircuitBuilder()
    q = builder.create_quantum_register(36, name='external')
    builder.ixor_gf2_mul(q[:12],q[12:24],target=q[24:36],field=km.GF2Field(12))
    template = [(g,[mapping[x] for x in wires],c) for g,wires,c in parse(str(builder.finish_circuit()))]
    indices = [i for i,op in enumerate(old) if op==template[0] and old[i:i+len(template)]==template]
    assert len(indices)==1, 'expected exactly one old pure product in the local quotient'
    start = indices[0]
    terms, archive_sha = decomposition('public42')
    replacement = [(g,[mapping[x] for x in wires],c) for g,wires,c in xor_product(terms,24)]
    assert Counter(g for g,_,_ in replacement)=={'CX':482,'CCX':42}
    operations = old[:start] + replacement + old[start+len(template):]
    ideal = inverse_anf()
    certificate = verify(operations,ideal)
    lines = ['# LOCAL ONLY: quotient120; not included in the multiply42 full DQI candidate.',
             '# Same 82-wire quotient layout as quotient_probe.py; arbitrary target, coherent control.']
    for gate,wires,condition in operations:
        values = [('b' if gate.startswith('BIT_') or (gate=='HMR' and i==1) else 'q')+str(x)
                  for i,x in enumerate(wires)]
        lines.append(' '.join([gate]+values)+('' if condition is None else f' if b{condition}'))
    text = '\n'.join(lines)+'\n'
    circuit = km.Circuit(text)
    assert circuit.num_qubits==82 and circuit.operation_statistics().num_toffoli_like==120
    assert parse(text)==operations
    for label,index in [('phase',next(i for i,(g,_,c) in enumerate(operations) if g=='CZ' and c is not None)),
                        ('product',start+next(i for i,(g,_,_) in enumerate(replacement) if g=='CCX'))]:
        bad = operations[:index]+operations[index+1:]
        try: verify(bad,ideal)
        except AssertionError: pass
        else: raise AssertionError(f'missing {label} gate was accepted')
    (args.out/'quotient120.kmx').write_text(text)
    result = {'scope':'local quotient120 only; NOT included in current multiply42 full candidate',
        'certificate':certificate,'prior_local_certificate':report['certificate'],
        'kickmix_parse':'PASS','local_qubits':82,'local_bits':circuit.num_bits,
        'old_static_toffoli':141,'new_static_toffoli':120,'saved_per_call':21,
        'old_product_span':[start,start+len(template)],'old_to_new_mapping':mapping,
        'negative_missing_phase_and_product_gates':'REJECTED',
        'op_counts':dict(Counter(g for g,_,_ in operations)),
        'kmx_sha256':digest(args.out/'quotient120.kmx'),'source_sha256':digest(Path(__file__)),
        'prior_quotient_source_sha256':digest(Path(__file__).with_name('quotient_probe.py')),
        'multiply_source_sha256':digest(Path(__file__).with_name('multiply_probe.py')),
        'public42_constants_sha256':digest(Path(__file__).with_name('public42-constants.json')),
        'inverse_archive_sha256':archive_sha,
        'attribution':'andigu/uncompute public42 tensor and inverse66; see Apache-2.0 and source provenance',
        'potential_static_saving_if_all_888_callers_are_integrated':18648,
        'full_DQI_generation':'NOT_RUN','full_DQI_verifier':'NOT_RUN','kaggle_submission':'NOT_RUN'}
    (args.out/'report.json').write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps(result,indent=2))


if __name__=='__main__':
    main()
