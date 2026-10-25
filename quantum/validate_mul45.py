#!/usr/bin/env python3
"""Run only the new multiplier candidate; reuse the verified non-Forney cache."""
import argparse
import json
from pathlib import Path

from dqi_gate import candidate, sha, verify
from mul45_dqi import REFERENCE_SHA


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--candidate', required=True)
    parser.add_argument('--integration-report', required=True)
    parser.add_argument('--data-root', required=True)
    parser.add_argument('--reference-checkpoint', required=True)
    parser.add_argument('--out', required=True)
    args = parser.parse_args()
    integration = json.loads(Path(args.integration_report).read_text())
    assert integration['status'] == 'PASS' and integration['kickmix_full_parse'] == 'PASS'
    info = candidate(args.candidate)
    assert info['candidate_sha256'] == integration['candidate_sha256']
    checkpoint = json.loads(Path(args.reference_checkpoint).read_text())
    assert checkpoint['status'] == 'PASS'
    previous = checkpoint['all_site_full_and_cached_comparison']
    cached = previous['full']
    assert previous['status'] == cached['status'] == 'PASS'
    assert cached['candidate_sha256'] == REFERENCE_SHA
    assert cached['verifier_sha256'] == sha(Path(args.data_root)/'verifiers/dqi/verify_submission_dqi.py')
    assert cached['num_shots'] == 102400 and cached['seed'] == 20261025
    assert cached['log2_delta'] == -128 and cached['max_workers'] == 1
    assert cached['value_errors'] == cached['phase_errors'] == 0
    assert info['dqi']['qubits'] == previous['candidate']['dqi']['qubits'] == 1893
    result = {'status': 'RUNNING', 'submits_to_kaggle': False, 'candidate': info,
              'generation_report_before_verification': integration,
              'comparison_reexecuted': False,
              'comparison_source': 'checkpoints/nonforney-20261026.json, local published-verifier validation',
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
        result['measured_incremental_cost_reduction_fraction'] = 1 - full['cost']/cached['cost']
        original = previous['original_baseline_full_cached']
        result['original_baseline_full_cached'] = original
        result['measured_total_cost_reduction_fraction'] = 1 - full['cost']/original['cost']
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
