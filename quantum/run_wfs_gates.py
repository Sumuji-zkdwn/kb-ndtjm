#!/usr/bin/env python3
"""Run existing candidate -> smoke -> full-package gates, never submit."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys


def run(args):
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    summary = {"submits_to_kaggle": False, "requested_stage": args.stage, "gates": {}}

    def record(stage, status, reason):
        row = {"stage": stage, "status": status, "reason": reason, "submits_to_kaggle": False}
        dest = out / stage
        dest.mkdir(parents=True, exist_ok=True)
        (dest / "report.json").write_text(json.dumps(row, indent=2)+"\n")
        summary["gates"][stage] = row

    def gate(stage):
        command = [sys.executable, str(Path(__file__).with_name("dqi_gate.py")),
                   "--stage", stage, "--baseline", args.baseline,
                   "--candidate", args.candidate, "--out", str(out/stage)]
        if stage in ("smoke", "full-package"):
            command += ["--data-root", args.data_root]
        if args.comparison:
            command += ["--comparison", args.comparison]
        code = subprocess.run(command).returncode
        report = out/stage/"report.json"
        if report.is_file():
            summary["gates"][stage] = json.loads(report.read_text())
        else:
            record(stage, "FAIL", f"gate process exited {code} without report")
        return code == 0 and summary["gates"][stage]["status"] == "PASS"

    requested = ["candidate"]
    if args.stage in ("smoke", "full-package"):
        requested += ["smoke"]
    if args.stage == "full-package":
        requested += ["full-package"]
    try:
        if not gate("candidate"):
            for stage in requested[1:]:
                record(stage, "NOT_RUN", "candidate gate failed")
            return 1
        if args.stage == "candidate":
            return 0
        data = Path(args.data_root)
        verifier = data / "verifiers/dqi/verify_submission_dqi.py"
        reason = "published official DQI verifier files unavailable"
        if not verifier.is_file() and args.fetch_official:
            if not os.environ.get("KAGGLE_API_TOKEN"):
                reason = "KAGGLE_API_TOKEN unavailable; official files not downloaded"
            else:
                install = subprocess.run([sys.executable, "-m", "pip", "install", "--disable-pip-version-check", "kaggle"])
                data.mkdir(parents=True, exist_ok=True)
                if install.returncode == 0:
                    result = subprocess.run(["kaggle", "competitions", "download",
                        "google-verifiable-quantum-circuit-compilation", "-p", str(data), "--unzip"])
                    reason = f"official asset download exit {result.returncode}; required verifier absent"
                else:
                    reason = "Kaggle client installation failed; official files unavailable"
        if not verifier.is_file():
            for stage in requested[1:]:
                record(stage, "NOT_RUN", reason)
            return 0  # candidate PASS; NOT_RUN is explicit and is never presented as verifier PASS
        if not gate("smoke"):
            if args.stage == "full-package":
                record("full-package", "NOT_RUN", "smoke failed")
            return 1
        if args.stage == "full-package" and not gate("full-package"):
            return 1
        return 0
    finally:
        summary["all_requested_gates_passed"] = all(
            summary["gates"].get(stage, {}).get("status") == "PASS" for stage in requested)
        (out/"stages.json").write_text(json.dumps(summary, indent=2)+"\n")
        print(json.dumps({"all_requested_gates_passed": summary["all_requested_gates_passed"],
                          "gates": {k:v["status"] for k,v in summary["gates"].items()}}, indent=2))


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--stage", choices=["candidate", "smoke", "full-package"], default="full-package")
    p.add_argument("--baseline", required=True)
    p.add_argument("--candidate", required=True)
    p.add_argument("--comparison", help="Optional prior full DQI to verify and compare at full-package")
    p.add_argument("--data-root", default="build/kaggle")
    p.add_argument("--out", default="build/report")
    p.add_argument("--fetch-official", action="store_true")
    sys.exit(run(p.parse_args()))
