#!/usr/bin/env python3
"""Submit exactly the user-authorized PR7 Actions ZIP; never regenerate it."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import sys
import time

COMPETITION = "google-verifiable-quantum-circuit-compilation"
SOURCE_COMMIT = "240ba77a94e01e4d35bc82d936833ae2fbae783f"
ARTIFACT_ID = 12694318660
RUN_ID = 40414437653
ZIP_SHA256 = "24d4a4f91127227959b01fd073e526ec2a80cd68f68bba59410ae46a01b8c246"
ZIP_BYTES = 83310332
FILENAME = "DQI_PR7_240ba77_24d4a4f9_submission.zip"
MARKER = "DQI-PR7-240ba77-24d4a4f9"
DESCRIPTION = (
    MARKER + ": Conservative BM, qubit reuse, GF(64)/GF(8) Forney trace phase. "
    "Q=2482; T=719881; published-verifier DQI cost=5.282883023272201e12 "
    "(-78.383809% vs v1.0). 102400+1536 checks: zero value/phase errors. "
    "Only DQI changed; other 12 files preserved. Official score pending."
)
EXPECTED = {
    "dfthcsos/angle_k_0.kmb": {
        "sha256": "7bfb3983accc6ff97d6ab41a88deae924f1d1c97cf30e60879d0bff5688a8e25",
        "bytes": 1671932,
        "unchanged_from_v1.0": True
    },
    "dfthcsos/angle_k_1.kmb": {
        "sha256": "a04b6d0d57ce851b123af265066aaab2ab33353ea049d26acd534727466d72b6",
        "bytes": 1662896,
        "unchanged_from_v1.0": True
    },
    "dfthcsos/angle_k_2.kmb": {
        "sha256": "5c1b8987bc3fa1a4b8607e470f8c8f1392c22e7a7dbcb228f0ce9ec986e18058",
        "bytes": 1665821,
        "unchanged_from_v1.0": True
    },
    "dfthcsos/angle_k_3.kmb": {
        "sha256": "16ac67cdcaf3e2c6abdd98c4138ff1ae8a56cfc4ae15622bcdb3d3a3ba1e22cf",
        "bytes": 1666802,
        "unchanged_from_v1.0": True
    },
    "dfthcsos/angle_k_4.kmb": {
        "sha256": "d21cdd4c7e94196654aab15ebcabfe10ce8d343151a5e8dc3672e76684b6628d",
        "bytes": 1954082,
        "unchanged_from_v1.0": True
    },
    "dfthcsos/angle_k_5.kmb": {
        "sha256": "63b8d4cba36955e6098321f3b2ef3e34401dd276fa629b2e490d043b1743880b",
        "bytes": 1948583,
        "unchanged_from_v1.0": True
    },
    "dfthcsos/angle_k_6.kmb": {
        "sha256": "5bf740428e661d035fda860142578f421969e35e0df2e4e024fbf01a7340b378",
        "bytes": 1947980,
        "unchanged_from_v1.0": True
    },
    "dfthcsos/angle_k_7.kmb": {
        "sha256": "606009582111a22bd549b795c8d115ac8bbeb124bc8da24a80380eca6d34163d",
        "bytes": 1968527,
        "unchanged_from_v1.0": True
    },
    "dfthcsos/angle_k_8.kmb": {
        "sha256": "57c7cc51f5922fff6e95d76e1f723d4c2d029a241da643b95684d6322157a8fe",
        "bytes": 1957124,
        "unchanged_from_v1.0": True
    },
    "dfthcsos/angle_k_9.kmb": {
        "sha256": "22cbe2828988ff954fc07fd971a25e6bc04a02c302bf2cc642e4c3535daaad65",
        "bytes": 1953830,
        "unchanged_from_v1.0": True
    },
    "dfthcsos/submission.npz": {
        "sha256": "88722115206ffebe5f79eda60781572e6a6cc182576084c9e1609f2f2587055a",
        "bytes": 4553036,
        "unchanged_from_v1.0": True
    },
    "invsqrt.kmb": {
        "sha256": "e2bf8eb64350a4460a271fc7f1d591ef125b1e276377e9a0f64b96ab3ca321e1",
        "bytes": 579721,
        "unchanged_from_v1.0": True
    },
    "dqi.kmb": {
        "sha256": "a5b128745d2a5bd76ab67faf1f141103de3c0e8c8d54535753bdc7716aaefc06",
        "bytes": 854708677,
        "matches_verified_candidate": True,
        "register_contract": {
            "qubits": 2482,
            "bits": 49142,
            "registers": 4165,
            "ops": 90986115,
            "3q_ops": 719881,
            "2q_ops": 89229974,
            "register_contract": "PASS"
        }
    }
}

def digest(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as f:
        while block := f.read(4 * 1024 * 1024):
            h.update(block)
    return h.hexdigest()

def audit_zip(path):
    import zipfile
    path = Path(path)
    if path.stat().st_size != ZIP_BYTES or digest(path) != ZIP_SHA256:
        raise ValueError("Submission ZIP size/SHA-256 mismatch")
    checked = []
    with zipfile.ZipFile(path) as z:
        infos = z.infolist()
        if len(infos) != 13 or len(set(z.namelist())) != 13 or set(z.namelist()) != set(EXPECTED):
            raise ValueError("Unexpected submission file layout")
        for info in infos:
            h = hashlib.sha256()
            size = 0
            with z.open(info) as member:
                while block := member.read(4 * 1024 * 1024):
                    h.update(block)
                    size += len(block)
            expected = EXPECTED[info.filename]
            if h.hexdigest() != expected["sha256"] or size != expected["bytes"]:
                raise ValueError("Member hash/size mismatch: " + info.filename)
            checked.append({"name": info.filename, "bytes": size, "sha256": h.hexdigest()})
    return checked

def submission_row(s):
    result = {}
    for key in ("ref", "description", "file_name", "date", "public_score", "private_score", "error_description"):
        value = getattr(s, key, None)
        if value is not None:
            result[key] = str(value)
    status = getattr(s, "status", None)
    result["status"] = getattr(status, "name", str(status))
    return result

def matching_submissions(api):
    rows = api.competition_submissions(COMPETITION, page_size=100) or []
    return [s for s in rows if s and (
        MARKER in (getattr(s, "description", None) or "")
        or FILENAME == (getattr(s, "file_name", None) or "")
    )]

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True)
    parser.add_argument("--artifact-metadata")
    parser.add_argument("--submit", action="store_true")
    parser.add_argument("--wait-seconds", type=int, default=900)
    args = parser.parse_args()
    out = Path("build/submission-report")
    out.mkdir(parents=True, exist_ok=True)
    report = {"competition": COMPETITION, "artifact_id": ARTIFACT_ID, "source_run_id": RUN_ID,
              "verified_source_commit": SOURCE_COMMIT, "zip_sha256": ZIP_SHA256,
              "zip_bytes": ZIP_BYTES, "regenerated": False, "repacked": False,
              "description": DESCRIPTION, "submission_attempted": False,
              "official_score": None, "status": "PREFLIGHT"}

    def save():
        (out / "submission-result.json").write_text(json.dumps(report, indent=2) + "\n")

    save()
    try:
        if args.artifact_metadata:
            metadata = json.loads(Path(args.artifact_metadata).read_text())
            if (metadata["id"] != ARTIFACT_ID or metadata.get("expired")
                or metadata["workflow_run"]["id"] != RUN_ID
                or metadata["workflow_run"]["head_sha"] != SOURCE_COMMIT
                or metadata["name"] != "dqi-bm-candidate-for-human-review"):
                raise ValueError("Actions artifact metadata does not match the verified source")
            report["artifact_metadata_checked"] = True
        report["members"] = audit_zip(args.input)
        report["package_audit"] = "PASS"
        if not args.submit:
            report["status"] = "AUDIT_ONLY"
            return 0
        if not args.artifact_metadata:
            raise ValueError("Submitting requires source artifact metadata")
        if not os.environ.get("KAGGLE_API_TOKEN"):
            raise ValueError("KAGGLE_API_TOKEN repository secret unavailable")
        if os.environ.get("GITHUB_RUN_ATTEMPT") != "1":
            raise ValueError("Automatic resubmission on a rerun is disabled")
        from kaggle.api.kaggle_api_extended import KaggleApi
        api = KaggleApi()
        api.authenticate()
        previous = matching_submissions(api)
        if previous:
            report["status"] = "ALREADY_SUBMITTED"
            report["matching_submissions"] = [submission_row(s) for s in previous]
            return 0
        limits = api.competition_get_submission_limits(COMPETITION)
        report["preflight_limits"] = {
            key: getattr(limits, key, None)
            for key in ("num_today", "num_total", "num_allowed_now", "limited_by_total")
        }
        if not limits.num_allowed_now:
            report["status"] = "NO_SUBMISSION_ALLOWANCE"
            return 2
        target = out / FILENAME
        shutil.copyfile(args.input, target)
        if digest(target) != ZIP_SHA256:
            raise ValueError("Copied ZIP hash mismatch")
        report["submission_attempted"] = True
        report["status"] = "SENDING"
        save()
        # Exactly one create-submission call. No automatic retry after any ambiguity.
        response = api.competition_submit(str(target), DESCRIPTION, COMPETITION, quiet=True)
        report["response_message"] = str(response.message)
        ref = getattr(response, "ref", None)
        if not ref:
            matches = matching_submissions(api)
            if len(matches) == 1:
                ref = matches[0].ref
        if not ref:
            report["status"] = "SUBMISSION_OUTCOME_UNCERTAIN"
            return 3
        report["submission_ref"] = int(ref)
        report["status"] = "ACCEPTED_AWAITING_SCORE"
        save()
        print(json.dumps({"status": report["status"], "submission_ref": int(ref)}), flush=True)
        deadline = time.monotonic() + args.wait_seconds
        last_status = None
        while time.monotonic() < deadline:
            try:
                s = api.get_submission(ref)
            except Exception as e:
                # Status reads are reversible; never repeat the submission itself.
                report["status_read_error_type"] = type(e).__name__
                save()
                time.sleep(30)
                continue
            row = submission_row(s)
            report["official_submission"] = row
            report["official_score"] = row.get("public_score")
            report["status"] = row["status"]
            save()
            if report["status"] != last_status:
                print(json.dumps(row), flush=True)
                last_status = report["status"]
            if report["status"] == "COMPLETE":
                return 0
            if report["status"] == "ERROR":
                return 4
            time.sleep(30)
        report["status"] = "ACCEPTED_SCORE_PENDING"
        return 0
    except Exception as e:
        report["status"] = "SUBMISSION_OUTCOME_UNCERTAIN" if report["submission_attempted"] else "PREFLIGHT_FAILED"
        message = str(e)
        for secret_name in ("KAGGLE_API_TOKEN", "GH_TOKEN", "GITHUB_TOKEN"):
            secret = os.environ.get(secret_name)
            if secret:
                message = message.replace(secret, "***")
        report["error"] = message[:3000]
        print(json.dumps({"status": report["status"], "error": report["error"]}), flush=True)
        return 5
    finally:
        save()
        print(json.dumps({key: report.get(key) for key in
                          ("status", "submission_ref", "official_score", "submission_attempted")}), flush=True)

if __name__ == "__main__":
    sys.exit(main())
