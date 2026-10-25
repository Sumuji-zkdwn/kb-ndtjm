#!/usr/bin/env python3
"""Join and verify submission.zip.partNN in the same directory."""
from pathlib import Path
import hashlib
import json

root = Path(__file__).resolve().parent
manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
out = root / manifest["file"]
whole = hashlib.sha256()

with out.open("wb") as target:
    for item in manifest["parts"]:
        part = root / item["name"]
        payload = part.read_bytes()
        assert len(payload) == item["bytes"], f"Incorrect size: {part.name}"
        assert hashlib.sha256(payload).hexdigest() == item["sha256"], f"Corrupted: {part.name}"
        whole.update(payload)
        target.write(payload)

assert out.stat().st_size == manifest["bytes"], "Incorrect reconstructed size"
assert whole.hexdigest() == manifest["sha256"], "Wrong reconstructed archive hash"
print(f"OK: {out} ({manifest['bytes']} bytes)")
