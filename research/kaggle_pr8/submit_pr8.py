"""One authorized submission of the immutable PR8 package; observe its official score.

Authorization: the user explicitly requested PR8 submission and comparison with PR7
on 2026-10-27. No circuit is regenerated or changed by this script. A dry run is the
default. Only the existing repository Kaggle credential is used, never exported.
"""

import argparse
from datetime import datetime, timezone
from decimal import Decimal
import hashlib
import json
import os
from pathlib import Path
import shutil
import time
import zipfile


COMPETITION = "google-verifiable-quantum-circuit-compilation"
EXPECTED_SHA256 = "147d53a469b87f40c6a7bdba1a75526bc136d6d8eea2096e49f5772a60297b01"
EXPECTED_BYTES = 83360676
MARKER = "DQI-PR8-b3f6373-147d53a4"
BASELINE_MARKER = "DQI-PR7-240ba77-24d4a4f9"
DESCRIPTION = (
    MARKER + ": Blind-cooperation scalar phase lowering. Q=2482; T=715786; "
    "published-verifier DQI cost=5.252831659254676e12 (-0.568844% vs PR7). "
    "102400 shots: zero value/phase errors. Only DQI changed; other 12 files "
    "byte-identical to scored PR7. Frozen package from Actions run 40447516741."
)


def now():
    return datetime.now(timezone.utc).isoformat()


def save(out, name, value):
    (out / name).write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def preflight(package):
    with package.open("rb") as stream:
        digest = hashlib.file_digest(stream, "sha256").hexdigest()
    if digest != EXPECTED_SHA256 or package.stat().st_size != EXPECTED_BYTES:
        raise ValueError("Refusing submission: package does not match frozen PR8")
    with zipfile.ZipFile(package) as archive:
        names = archive.namelist()
        if len(names) != 13 or "dqi.kmb" not in names or archive.testzip() is not None:
            raise ValueError("Refusing submission: PR8 ZIP integrity check failed")
    return {"status": "PASS", "observed_utc": now(), "sha256": digest,
            "bytes": package.stat().st_size, "members": names,
            "source_run": 40447516741,
            "source_commit": "b3f6373d10bfec8b4c7a102f774399d2563bfe8f"}


def record(submission):
    return {"observed_utc": now(), "ref": submission.ref,
            "date": submission.date.isoformat() if submission.date else None,
            "description": submission.description, "file_name": submission.file_name,
            "total_bytes": submission.total_bytes, "status": submission.status.name,
            "public_score": submission.public_score, "private_score": submission.private_score,
            "error_description": submission.error_description}


def identify(submissions):
    baseline = [s for s in submissions if s and (s.description or "").startswith(BASELINE_MARKER)]
    matches = [s for s in submissions if s and (s.description or "").startswith(MARKER)]
    if len(baseline) != 1 or len(matches) > 1:
        raise ValueError("Refusing submission: baseline identity or duplicate PR8 is ambiguous")
    baseline = baseline[0]
    if baseline.status.name != "COMPLETE" or round(Decimal(baseline.public_score), 5) != Decimal("1.66633"):
        raise ValueError("Refusing submission: authenticated account lacks the expected scored PR7")
    if baseline.total_bytes != 83310332:
        raise ValueError("Refusing submission: PR7 package size differs from the verified baseline")
    return baseline, matches[0] if matches else None


def execute(api, package, out):
    baseline, existing = identify(api.competition_submissions(COMPETITION, page_size=100) or [])
    save(out, "pr7-official-api.json", record(baseline))
    if existing:
        submission_ref = existing.ref
        save(out, "receipt.json", {"observed_utc": now(), "ref": submission_ref,
                                  "action": "observe_existing_PR8_without_resubmission"})
    else:
        if os.environ.get("GITHUB_RUN_ATTEMPT", "1") != "1":
            raise ValueError("A workflow rerun cannot make a new submission; inspect the first receipt")
        upload = out.parent / "upload" / "submission.zip"
        upload.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(package, upload)
        preflight(upload)
        save(out, "submission-intent.json", {"observed_utc": now(), "marker": MARKER,
             "competition": COMPETITION, "sha256": EXPECTED_SHA256,
             "user_authorized_on": "2026-10-27", "maximum_submit_calls": 1})
        # Deliberately no automatic retry of this mutation, even on a timeout.
        receipt = api.competition_submit(str(upload), DESCRIPTION, COMPETITION, quiet=True)
        submission_ref = receipt.ref
        save(out, "receipt.json", {"observed_utc": now(), "ref": submission_ref,
                                  "message": receipt.message, "action": "submitted_once"})
        if not submission_ref:
            raise RuntimeError("Kaggle did not return a submission ref; inspect receipt without resubmitting")
    print(f"Kaggle submission ref: {submission_ref}", flush=True)
    deadline = time.monotonic() + 4800
    while True:
        submission = api.get_submission(submission_ref)
        evidence = record(submission)
        with (out / "status-history.jsonl").open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(evidence, ensure_ascii=False) + "\n")
        save(out, "pr8-official-api.json", evidence)
        print(json.dumps({k: evidence[k] for k in ("observed_utc", "ref", "status", "public_score", "error_description")}), flush=True)
        if not (submission.description or "").startswith(MARKER):
            raise RuntimeError("Submission identity changed")
        if submission.total_bytes != EXPECTED_BYTES:
            raise RuntimeError("Kaggle submission size does not match frozen PR8")
        if submission.status.name == "ERROR":
            raise RuntimeError("Kaggle official scoring failed; see pr8-official-api.json")
        if submission.status.name == "COMPLETE" and submission.public_score:
            old, new = Decimal(baseline.public_score), Decimal(submission.public_score)
            save(out, "official-comparison.json", {
                "observed_utc": now(), "competition": COMPETITION,
                "pr7_ref": baseline.ref, "pr8_ref": submission_ref,
                "pr7_public_score": str(old), "pr8_public_score": str(new),
                "absolute_score_change": str(new - old),
                "relative_score_change_percent": str((new / old - 1) * 100),
                "higher_score_is_better": True,
                "claim_scope": "One sequential PR7-to-PR8 artifact comparison, not an isolated causal test of the collaboration method",
                "pr8_package_sha256": EXPECTED_SHA256})
            return
        if time.monotonic() >= deadline:
            raise TimeoutError("Scoring remains pending; continue observing this submission ref without resubmission")
        time.sleep(30)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--package", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--submit-authorized-pr8", action="store_true")
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    save(args.out, "preflight.json", preflight(args.package))
    if not args.submit_authorized_pr8:
        print("Frozen PR8 package verified; dry run made no API calls")
        return
    from kaggle.api.kaggle_api_extended import KaggleApi
    api = KaggleApi()
    api.authenticate()
    execute(api, args.package, args.out)


if __name__ == "__main__":
    main()
