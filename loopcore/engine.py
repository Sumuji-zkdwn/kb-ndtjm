"""Bounded generate -> domain-check -> hash-seal -> re-enter controller.

No model calls, network access, Kaggle submissions or external programs.
An adapter only verifies its declared mathematical scope; the existing
Lean proof/audit gate remains authoritative for primitive-lean.
"""
from __future__ import annotations

import hashlib
import importlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path
import shutil
import tempfile

SCHEMA = 1
VALID_DOMAINS = frozenset({"finite", "wfs"})


def canonical(obj):
    return (json.dumps(obj, sort_keys=True, ensure_ascii=False, separators=(",", ":")) + "\n").encode("utf-8")


def sha(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def load_adapter(domain: str):
    if domain not in VALID_DOMAINS:
        raise ValueError(f"unknown domain: {domain!r}")
    return importlib.import_module(f"loopcore.adapters.{domain}")


def read_ledger(root: Path, domain: str):
    path = root / "ledger.json"
    if not path.exists():
        return {"schema_version": SCHEMA, "domain": domain, "cycles": []}
    doc = json.loads(path.read_text(encoding="utf-8"))
    if doc.get("schema_version") != SCHEMA or doc.get("domain") != domain:
        raise ValueError("ledger schema/domain mismatch")
    if not isinstance(doc.get("cycles"), list):
        raise ValueError("invalid ledger")
    return doc


def record_hash(record: dict) -> str:
    return sha(canonical({k: v for k, v in record.items() if k != "record_sha256"}))


def safe_filename(name) -> bool:
    return isinstance(name, str) and name not in ("", ".", "..") and name == Path(name).name and "\\" not in name


def audit(root: Path, domain: str, rerun_checks: bool = False):
    adapter = load_adapter(domain)
    ledger = read_ledger(root, domain)
    previous, models = None, set()
    for index, record in enumerate(ledger["cycles"], 1):
        if record.get("cycle") != index or record.get("previous_sha256") != previous:
            raise ValueError(f"broken cycle sequence at {index}")
        if record_hash(record) != record.get("record_sha256"):
            raise ValueError(f"record hash mismatch at {index}")
        model = record.get("model")
        if not isinstance(model, dict):
            raise ValueError(f"invalid model at {index}")
        model_key = canonical(model)
        if model_key in models:
            raise ValueError(f"duplicate model at {index}")
        models.add(model_key)
        cycle_path = root / "cycles" / f"{index:05d}"
        files = {}
        for filename, expected_hash in record.get("artifacts", {}).items():
            if not safe_filename(filename):
                raise ValueError(f"unsafe artifact filename at {index}")
            data = (cycle_path / filename).read_bytes()
            if sha(data) != expected_hash:
                raise ValueError(f"artifact hash mismatch at {index}/{filename}")
            files[filename] = data
        report_data = (cycle_path / "report.json").read_bytes()
        if sha(report_data) != record.get("report_sha256"):
            raise ValueError(f"report hash mismatch at {index}")
        report = json.loads(report_data)
        if report.get("passed") is not True:
            raise ValueError(f"non-passing report at {index}")
        if rerun_checks and adapter.check(model, files, index) != report:
            raise ValueError(f"recomputed check differs at {index}")
        previous = record["record_sha256"]
    return {"passed": True, "domain": domain, "cycles": len(ledger["cycles"]),
            "recomputed_domain_checks": bool(rerun_checks),
            "last_record_sha256": previous}


class Lock:
    def __init__(self, path: Path):
        self.path = path
        self.fd = None

    def __enter__(self):
        try:
            self.fd = os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        except FileExistsError as exc:
            raise RuntimeError("workspace locked; inspect a stale .lock before removal") from exc
        os.write(self.fd, f"{os.getpid()}\n".encode())
        return self

    def __exit__(self, exc_type, exc, tb):
        if self.fd is not None:
            os.close(self.fd)
            self.path.unlink(missing_ok=True)


def run_one(root: Path, domain: str):
    root = root.resolve()
    adapter = load_adapter(domain)
    root.mkdir(parents=True, exist_ok=True)
    with Lock(root / ".lock"):
        audit(root, domain)
        ledger = read_ledger(root, domain)
        seen = {canonical(row["model"]) for row in ledger["cycles"]}
        model = next((x for x in adapter.candidates() if canonical(x) not in seen), None)
        if model is None:
            return {"status": "exhausted", "domain": domain, "cycles": len(ledger["cycles"])}
        cycle = len(ledger["cycles"]) + 1
        parent = root / "cycles"
        parent.mkdir(exist_ok=True)
        dest = parent / f"{cycle:05d}"
        if dest.exists():
            raise FileExistsError(f"untracked cycle target: {dest}")
        pending = Path(tempfile.mkdtemp(prefix=".pending-", dir=parent))
        try:
            files = adapter.build(model, cycle)
            if not isinstance(files, dict) or not files or not all(
                    safe_filename(name) and isinstance(data, bytes)
                    for name, data in files.items()):
                raise ValueError("adapter outputs must be a basename -> bytes dictionary")
            for name, data in files.items():
                (pending / name).write_bytes(data)
            report = adapter.check(model, files, cycle)
            if not isinstance(report, dict) or report.get("passed") is not True:
                raise ValueError(f"fail closed: domain validation failed: {report}")
            report_data = json.dumps(report, ensure_ascii=False, sort_keys=True, indent=2).encode() + b"\n"
            (pending / "report.json").write_bytes(report_data)
            record = {
                "cycle": cycle, "domain": domain, "model": model,
                "status": "verified_by_" + str(report["method"]),
                "artifacts": {name: sha(data) for name, data in sorted(files.items())},
                "report_sha256": sha(report_data),
                "previous_sha256": ledger["cycles"][-1]["record_sha256"] if ledger["cycles"] else None,
                "verified_utc": datetime.now(timezone.utc).isoformat(),
            }
            record["record_sha256"] = record_hash(record)
            os.replace(pending, dest)
            ledger["cycles"].append(record)
            path = root / "ledger.json"
            with tempfile.NamedTemporaryFile(mode="wb", dir=root, prefix=".writing-", delete=False) as tmp:
                tmp.write(json.dumps(ledger, ensure_ascii=False, sort_keys=True, indent=2).encode() + b"\n")
                tmp.flush()
                os.fsync(tmp.fileno())
                staged = tmp.name
            os.replace(staged, path)
            return {"status": "verified", "domain": domain, "cycle": cycle,
                    "model": model, "record_sha256": record["record_sha256"], "report": report}
        finally:
            if pending.exists():
                shutil.rmtree(pending)
