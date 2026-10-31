"""Fetch the pinned official ARC-AGI-2 dataset for local evaluation only.

Not used by the offline notebook.  The upstream Apache-2.0 license is retained.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import io
import json
from pathlib import Path, PurePosixPath
import urllib.request
import zipfile


COMMIT = "f3283f727488ad98fe575ea6a5ac981e4a188e49"
ARCHIVE_SHA256 = "c3f9f6975d8432133419fd0e1677c42289666517af4e6f83d8a291690e14d49f"
URL = f"https://codeload.github.com/arcprize/ARC-AGI-2/zip/{COMMIT}"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--destination", type=Path, default=Path("data/ARC-AGI-2"))
    args = parser.parse_args()
    destination = args.destination
    if destination.exists() and any(destination.iterdir()):
        raise SystemExit(f"Refusing to overwrite nonempty destination: {destination}")
    request = urllib.request.Request(URL, headers={"User-Agent": "ARC2-candidate-data-fetcher"})
    with urllib.request.urlopen(request, timeout=90) as response:
        archive_bytes = response.read()
    actual_hash = hashlib.sha256(archive_bytes).hexdigest()
    if actual_hash != ARCHIVE_SHA256:
        raise SystemExit(f"Pinned archive SHA256 mismatch: {actual_hash}")
    archive = zipfile.ZipFile(io.BytesIO(archive_bytes))
    planned = []
    for item in archive.infolist():
        parts = PurePosixPath(item.filename).parts[1:]
        if not parts or item.is_dir():
            continue
        if ".." in parts or any(part.startswith("/") for part in parts):
            raise SystemExit("Unsafe path in upstream archive")
        planned.append((item, destination.joinpath(*parts)))
    for item, path in planned:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(archive.read(item))
    counts = {split: len(list((destination / "data" / split).glob("*.json"))) for split in ("training", "evaluation")}
    if counts != {"training": 1000, "evaluation": 120}:
        raise SystemExit(f"Unexpected dataset counts: {counts}")
    provenance = {
        "repository": "https://github.com/arcprize/ARC-AGI-2",
        "commit": COMMIT,
        "archive_sha256": actual_hash,
        "fetched_utc": datetime.now(timezone.utc).isoformat(),
        "task_counts": counts,
        "license": "Apache-2.0; see upstream LICENSE retained in this directory",
    }
    (destination / "FETCH_PROVENANCE.json").write_text(json.dumps(provenance, indent=2) + "\n")
    print(json.dumps(provenance, indent=2))


if __name__ == "__main__":
    main()
