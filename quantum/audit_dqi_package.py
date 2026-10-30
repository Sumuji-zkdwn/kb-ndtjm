#!/usr/bin/env python3
"""Audit an already-produced DQI ZIP without changing it or submitting it."""
import argparse
import hashlib
import json
from pathlib import Path
import zipfile

from dqi_gate import BASE_SHA, inspect_kmb, sha


def audit(baseline, package, expected_dqi_sha256):
    if sha(baseline) != BASE_SHA:
        raise ValueError('unexpected v1.0 baseline ZIP')
    with zipfile.ZipFile(baseline) as old, zipfile.ZipFile(package) as new:
        names = new.namelist()
        if len(names) != len(set(names)) or len(names) != 13 or set(names) != set(old.namelist()):
            raise ValueError('package member names/count differ from v1.0')
        records = {}
        for name in names:
            digest, size = hashlib.sha256(), 0
            if name == 'dqi.kmb':
                with new.open(name) as stream:
                    layout = inspect_kmb(stream)
                with new.open(name) as stream:
                    while chunk := stream.read(1 << 22):
                        digest.update(chunk)
                        size += len(chunk)
                if digest.hexdigest() != expected_dqi_sha256:
                    raise ValueError('packaged DQI differs from the verified candidate hash')
                records[name] = {'sha256': digest.hexdigest(), 'bytes': size,
                                 'matches_verified_candidate': True, 'register_contract': layout}
            else:
                with old.open(name) as reference, new.open(name) as stream:
                    while True:
                        before, after = reference.read(1 << 22), stream.read(1 << 22)
                        if before != after:
                            raise ValueError(f'non-DQI member changed: {name}')
                        if not after:
                            break
                        digest.update(after)
                        size += len(after)
                records[name] = {'sha256': digest.hexdigest(), 'bytes': size,
                                 'unchanged_from_v1.0': True}
    return {'status': 'PASS', 'baseline_zip_sha256': BASE_SHA,
            'zip_sha256': sha(package), 'zip_bytes': Path(package).stat().st_size,
            'members': 13, 'non_DQI_members_byte_identical': 12,
            'all_member_CRC_checked_by_complete_stream_reads': True,
            'member_hashes': records, 'submits_to_kaggle': False}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--baseline', required=True)
    parser.add_argument('--package', required=True)
    parser.add_argument('--expected-dqi-sha256', required=True)
    parser.add_argument('--out', required=True, type=Path)
    args = parser.parse_args()
    result = audit(args.baseline, args.package, args.expected_dqi_sha256)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps({k: v for k, v in result.items() if k != 'member_hashes'}, indent=2))
