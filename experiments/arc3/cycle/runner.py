"""One short workflow stage; a later run restores the previous run's artifact."""
import argparse
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time
import cycle


def configuration():
    request = cycle.read(cycle.HERE / "request.json")
    if os.environ.get("GITHUB_EVENT_NAME") == "workflow_dispatch":
        for key in ("stage", "profile", "label", "hypothesis", "source_run_id", "connection_run_id", "version", "baseline_label", "candidate_label"):
            if os.environ.get("CYCLE_" + key.upper()):
                request[key] = os.environ["CYCLE_" + key.upper()]
    if request["stage"] not in ("prepare", "public-smoke", "start", "observe", "collect", "submit", "adopt-kernel", "reconcile-submission", "gpu-pair", "cpu-pair"):
        raise ValueError("Unknown cycle stage")
    if request["profile"] not in (*cycle.profiles(), "all"):
        raise ValueError("Unknown cycle profile")
    if request["profile"] == "all" and request["stage"] != "prepare":
        raise ValueError("Run one candidate at a time; all is available only for offline preparation")
    if request.get("source_run_id") and not re.fullmatch(r"[1-9][0-9]*", str(request["source_run_id"])):
        raise ValueError("source_run_id must be a positive Actions run ID")
    if request.get("connection_run_id") and not re.fullmatch(r"[1-9][0-9]*", str(request["connection_run_id"])):
        raise ValueError("connection_run_id must be a positive Actions run ID")
    if request["stage"] in ("public-smoke", "observe", "collect", "submit", "adopt-kernel", "reconcile-submission") and not request.get("source_run_id"):
        raise ValueError("This stage must restore an exact previous source_run_id")
    if not re.fullmatch(r"[a-z0-9-]{1,36}", request["label"]):
        raise ValueError("Invalid candidate label")
    if not re.fullmatch(r"[a-z0-9-]{1,36}", request.get("baseline_label", "baseline-20261029")):
        raise ValueError("Invalid baseline label")
    if not isinstance(request["hypothesis"], str) or not request["hypothesis"].strip():
        raise ValueError("An explicit experiment hypothesis is required")
    if request["stage"] == "gpu-pair" and (request["profile"] != "gpu-baseline" or len(request["label"]) > 29):
        raise ValueError("gpu-pair requires gpu-baseline and a label of at most 29 characters")
    if request["stage"] == "cpu-pair" and (request["profile"] != "cpu-c8b" or not request.get("source_run_id")
            or not re.fullmatch(r"[a-z0-9-]{1,36}", request.get("candidate_label", ""))):
        raise ValueError("cpu-pair needs a restored CPU baseline and an explicit existing candidate label")
    return request


def summary(root):
    lines = ["# ARC3 improvement cycle", "",
             "CPU and GPU are separate experiment lines. Notebook completion and official scoring are separate stages.", "",
             "| Profile | Candidate | Notebook / version | Notebook status | Submission ref | Official status | Public score |",
             "|---|---|---|---|---|---|---|"]
    for manifest_path in sorted(root.glob("*/*/manifest.json")):
        bundle = manifest_path.parent
        manifest = cycle.verify(bundle)
        profile = manifest["identity"]["profile"] + "/" + manifest["identity"]["label"]
        values = {}
        for name in ("kernel-status.json", "submission-receipt.json", "official-score.json", "kernel-receipt.json"):
            path = bundle / "evidence" / name
            values[name] = cycle.receipt(bundle, name) if path.exists() else {}
        status, sub, score = (values[name] for name in ("kernel-status.json", "submission-receipt.json", "official-score.json"))
        kernel = values["kernel-receipt.json"]
        url = "https://www.kaggle.com/code/" + manifest["kernel"]
        link = f"[Notebook]({url}) / {kernel.get('version', 'not started')}"
        lines.append(f"| {profile} | {manifest['candidate_id'][:12]} | {link} | {status.get('status', 'not observed')} | "
                     f"{sub.get('ref', '')} | {score.get('status', 'not submitted / not observed')} | {score.get('public_score', '')} |")
    lines.extend(["", "The next iteration must state one concrete change and retain its baseline.",
                  "Inspect notebook outputs and failures before spending another official submission.",
                  "No local result or test is an official score."])
    text = "\n".join(lines) + "\n"
    (root / "REPORT.md").write_text(text, encoding="utf-8")
    if os.environ.get("GITHUB_STEP_SUMMARY"):
        with open(os.environ["GITHUB_STEP_SUMMARY"], "a", encoding="utf-8") as stream:
            stream.write(text)


def wait_gpu_terminal(api, bundle, timeout_s=5400):
    deadline = time.monotonic() + timeout_s
    while True:
        status = cycle.observe_kernel(api, bundle)
        print(json.dumps(status), flush=True)
        if status["status"] == "COMPLETE":
            cycle.collect_output(api, bundle)
            return cycle.require_gpu_validation(bundle)
        if status["status"] in ("ERROR", "CANCEL_ACKNOWLEDGED"):
            cycle.collect_output(api, bundle)
            raise ValueError("GPU Notebook failed; keep diagnostics and stop the pair")
        if time.monotonic() >= deadline:
            raise TimeoutError("GPU pair observation deadline; keep the existing notebook, do not relaunch")
        time.sleep(60)


def run_gpu_pair(request, root):
    """One bounded baseline/memory pair; no official submissions or adoption."""
    api = cycle.api_client()
    for profile, label in (("gpu-baseline", request["label"]), ("gpu-memory", request["label"] + "-memory")):
        step = {**request, "stage": "start", "profile": profile, "label": label,
                "baseline_label": request["label"]}
        run(step, root)
        wait_gpu_terminal(api, root / profile / label)
        summary(root)


def wait_official_score(api, bundle, timeout_s=5400):
    deadline = time.monotonic() + timeout_s
    while True:
        value = cycle.observe_score(api, bundle)
        print(json.dumps(value), flush=True)
        if value["status"] == "COMPLETE" and value["public_score"] not in (None, ""):
            return value
        if value["status"] not in ("PENDING", "RUNNING"):
            raise ValueError("Official evaluation ended without a usable public score; inspect official-score.json")
        if time.monotonic() >= deadline:
            raise TimeoutError("Official score observation deadline; retain the same submission ref")
        time.sleep(60)


def run_cpu_pair(request, root):
    """Continue the existing CPU pair once; do not create a new notebook."""
    baseline = root / "cpu-c8b" / request["label"]
    candidate = root / "cpu-c8b-probe64" / request["candidate_label"]
    manifests = [cycle.verify(p, launch=True) for p in (baseline, candidate)]
    if any(m["identity"]["line"] != "cpu" for m in manifests):
        raise ValueError("CPU pair cannot mix experiment lines")
    for key in ("runtime", "session_timeout_seconds"):
        if manifests[0]["identity"][key] != manifests[1]["identity"][key]:
            raise ValueError("CPU pair execution conditions differ: " + key)
    for path in (baseline, candidate):
        cycle.require_connection_check(path)
    api = cycle.api_client()
    wait_official_score(api, baseline)
    if not (candidate / "evidence/submission-receipt.json").exists():
        if (candidate / "evidence/submission-intent.json").exists():
            cycle.authorize_rejected_submission_retry(api, candidate,
                cycle.HERE / "baseline-evidence/cpu-probe64-submit-http400.json")
        result = cycle.submit(api, candidate)
        print(json.dumps(result), flush=True)
        if not result.get("ref"):
            raise ValueError("CPU candidate is deferred; retain evidence without another mutation")
    wait_official_score(api, candidate)
    result = cycle.compare(baseline, candidate)
    cycle.save(root / "cpu-comparison.json", result)
    print(json.dumps(result), flush=True)


def run(request, root):
    root.mkdir(parents=True, exist_ok=True)
    if request["stage"] == "gpu-pair":
        return run_gpu_pair(request, root)
    if request["stage"] == "cpu-pair":
        return run_cpu_pair(request, root)
    selected = list(cycle.profiles()) if request["profile"] == "all" else [request["profile"]]
    api = None
    if request["stage"] not in ("prepare", "public-smoke"):
        api = cycle.api_client()
    for profile in selected:
        bundle = root / profile / request["label"]
        if request["stage"] == "start" and profile == "gpu-memory":
            baseline = root / "gpu-baseline" / request.get("baseline_label", "baseline-20261029")
            if not (baseline / "manifest.json").exists():
                raise ValueError("GPU memory must restore its baseline artifact, including gpu-environment.json")
            if cycle.observe_kernel(api, baseline)["status"] != "COMPLETE":
                raise ValueError("Finish the GPU baseline before starting its memory comparison")
            cycle.collect_output(api, baseline)
            cycle.require_gpu_validation(baseline)
        if request["stage"] in ("prepare", "start"):
            env_path = root / "gpu-environment.json"
            if request["stage"] == "start" and profile.startswith("gpu-") and not env_path.exists():
                cycle.environment(api, env_path)
            if not (bundle / "manifest.json").exists():
                cycle.prepare(profile, bundle, request["label"], request["hypothesis"],
                              environment_path=env_path if env_path.exists() else None)
            cycle.verify(bundle)
            if profile == "cpu-c8b" and not (bundle / "evidence" / "public-smoke.json").exists():
                try:
                    cycle.reuse_cpu_baseline_evidence(bundle)
                except ValueError:
                    if request["stage"] == "start":
                        raise
        connection = Path("build/connection-import/connection-report/report.json")
        if connection.exists():
            cycle.attach_connection_check(bundle, connection)
            measured = Path("build/connection-import/cpu-candidate")
            if cycle.verify(bundle)["identity"]["line"] == "cpu" and (measured / "manifest.json").exists():
                cycle.import_cpu_smoke(bundle, measured)
        if request["stage"] == "start":
            print(json.dumps(cycle.start(api, bundle)), flush=True)
            print(json.dumps(cycle.observe_kernel(api, bundle)), flush=True)
        elif request["stage"] == "public-smoke":
            if not profile.startswith("cpu-"):
                raise ValueError("The offline public-smoke runner is for CPU candidates")
            subprocess.run([sys.executable, str(cycle.HERE / "cpu_smoke.py"), "--bundle", str(bundle),
                            "--environments", os.environ["ARC3_ENVIRONMENTS"],
                            "--official-zip", os.environ["ARC3_OFFICIAL_ZIP"]], check=True)
        elif request["stage"] == "observe":
            print(json.dumps(cycle.observe_kernel(api, bundle)), flush=True)
            if (bundle / "evidence" / "submission-receipt.json").exists():
                cycle.observe_score(api, bundle)
        elif request["stage"] == "collect":
            print(json.dumps(cycle.collect_output(api, bundle)), flush=True)
        elif request["stage"] == "submit":
            result = cycle.submit(api, bundle)
            print(json.dumps(result), flush=True)
            if result.get("ref"):
                cycle.observe_score(api, bundle)
        elif request["stage"] == "adopt-kernel":
            cycle.adopt(api, bundle, int(request["version"]))
        elif request["stage"] == "reconcile-submission":
            cycle.reconcile_submission(api, bundle)
            cycle.observe_score(api, bundle)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path("build/arc3-cycle"))
    parser.add_argument("--config-only", action="store_true")
    parser.add_argument("--offline-all", action="store_true")
    args = parser.parse_args()
    request = ({"stage": "prepare", "profile": "all", "label": "contract-test",
                "hypothesis": "Offline source validation only", "source_run_id": ""}
               if args.offline_all else configuration())
    if args.config_only:
        print(json.dumps(request))
        if os.environ.get("GITHUB_OUTPUT"):
            with open(os.environ["GITHUB_OUTPUT"], "a", encoding="utf-8") as stream:
                request["connection_profile"] = request["profile"] if request["profile"].startswith("cpu-") else "cpu-c8b"
                for key in ("stage", "profile", "source_run_id", "connection_run_id", "connection_profile"):
                    stream.write(f"{key}={request.get(key, '')}\n")
        return
    try:
        run(request, args.root)
    finally:
        args.root.mkdir(parents=True, exist_ok=True)
        summary(args.root)


if __name__ == "__main__":
    main()
