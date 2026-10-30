#!/usr/bin/env python3
"""Verify only the NEW candidate; reuse pinned completed Forney measurements."""
import argparse
import json
from pathlib import Path

from dqi_gate import candidate, sha, verify
from eea_quotient_dqi import REFERENCE_SHA


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--candidate', required=True)
    p.add_argument('--integration-report', required=True)
    p.add_argument('--data-root', required=True)
    p.add_argument('--reference-checkpoint', required=True)
    p.add_argument('--out', required=True)
    args = p.parse_args()
    integration = json.loads(Path(args.integration_report).read_text())
    assert integration['status'] == 'PASS' and integration['kickmix_full_parse'] == 'PASS'
    info = candidate(args.candidate)
    assert info['candidate_sha256'] == integration['candidate_sha256']
    checkpoint = json.loads(Path(args.reference_checkpoint).read_text())
    cached_gate = checkpoint['all_site_gates']['gates']['full-package']
    assert cached_gate['status'] == 'PASS'
    cached = cached_gate['full']
    assert cached['candidate_sha256'] == REFERENCE_SHA
    verifier_path = Path(args.data_root) / 'verifiers/dqi/verify_submission_dqi.py'
    assert cached['verifier_sha256'] == sha(verifier_path)
    assert cached['num_shots'] == 102400 and cached['seed'] == 20261025
    assert cached['log2_delta'] == -128 and cached['max_workers'] == 1
    assert cached['value_errors'] == cached['phase_errors'] == 0
    assert info['dqi']['qubits'] == cached_gate['candidate']['dqi']['qubits'] == 1893
    result = {'status': 'RUNNING', 'submits_to_kaggle': False,
              'candidate': info, 'generation_report_before_verification': integration,
              'comparison_reexecuted': False,
              'comparison_source': checkpoint['actions_run'],
              'reference_checkpoint_sha256': sha(args.reference_checkpoint),
              'comparison_full_cached': cached,
              'kaggle_official_evaluation': 'NOT_RUN'}
    output = Path(args.out)
    output.parent.mkdir(parents=True, exist_ok=True)
    try:
        output.write_text(json.dumps(result, indent=2) + '\n')
        full = verify(args.candidate, args.data_root, cached['num_shots'],
                      'wfs-dqi-public-local-seed-20261025')
        result['full'] = full
        assert full['value_errors'] == full['phase_errors'] == 0
        assert full['effective_error_rate'] == cached['effective_error_rate']
        assert full['cost'] < cached['cost']
        result['candidate']['quantum_correctness'] = 'PASS: published verifier, 102400 shots, zero value/phase errors'
        result['measured_additional_Toffoli_saved'] = cached['toffoli_count'] - full['toffoli_count']
        result['measured_incremental_cost_reduction_fraction'] = 1 - full['cost'] / cached['cost']
        original = cached_gate['baseline_full']
        result['original_baseline_full_cached'] = original
        result['measured_total_cost_reduction_fraction'] = 1 - full['cost'] / original['cost']
        result['status'] = 'PASS'
    except Exception as error:
        result['status'] = 'FAIL'
        result['error'] = f'{type(error).__name__}: {error}'
        raise
    finally:
        output.write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
