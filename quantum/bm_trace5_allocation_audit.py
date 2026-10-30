"""Compare every allocation event against preserved PR7, except op offsets."""
import argparse
import gzip
import json
from pathlib import Path
from dqi_gate import sha, BM_TRACE3_CHECKPOINT_SHA


def audit(candidate, generation):
    root = Path(__file__).resolve().parents[1]
    checkpoint = root / 'checkpoints/bm-tracephase3-20261027.json'
    assert sha(checkpoint) == BM_TRACE3_CHECKPOINT_SHA
    old = json.loads(gzip.decompress((root / 'checkpoints/bm-tracephase3-allocations-20261027.json.gz').read_bytes()))
    new = json.loads(Path(candidate).read_text())
    strip = lambda events: [{k:v for k,v in event.items() if k != 'op_index'} for event in events]
    assert strip(old) == strip(new), 'allocation, ownership, lifetime or peak changed'
    report = json.loads(Path(generation).read_text())
    assert report['qubits'] == report['peak_live'] == 2482
    assert report['forney_phase_method'] == 'scalar_trace_5'
    assert report['static_Toffoli'] == 715786
    return {'status': 'PASS', 'events': len(new), 'all_events_equal_except_op_index': True,
            'peak_live': 2482, 'candidate_sha256': report['candidate_sha256'],
            'reference_allocation_sha256': sha(root / 'checkpoints/bm-tracephase3-allocations-20261027.json.gz')}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--candidate', type=Path, required=True)
    parser.add_argument('--generation', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    result = audit(args.candidate, args.generation)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps(result, indent=2))
