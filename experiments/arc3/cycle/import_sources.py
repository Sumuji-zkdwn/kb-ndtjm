"""Import preserved notebooks from the existing ARC deadline project, read-only."""
import argparse
from pathlib import Path
import shutil
import cycle


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, required=True)
    args = parser.parse_args()
    sources = {
        "cpu-c8b": ("submission_c8b/submission.ipynb", "d474b369ce24f4853e61d50352d7f5768548d5659ddd8e1973faf8e636538761"),
        "gpu-baseline": ("public_baseline_franzen_v3/arc-agi-3-milestone-2-solution.ipynb", "589eaf393f416effe925c6830fc00fcdc0d6da91193b29ff0029282cbd6ee96e"),
        "gpu-memory": ("franzen_evidence_memory_v1/arc3-franzen-evidence-memory-v1.ipynb", None),
    }
    inventory = {}
    for profile, (relative, expected) in sources.items():
        source = args.source / relative
        raw = source.read_bytes()
        if expected and cycle.digest(raw) != expected:
            raise ValueError("Preserved source changed: " + relative)
        original = cycle.read(source)
        clean = cycle.clean_notebook(original)
        cycle.validate_notebook(clean)
        target = cycle.HERE / "notebooks" / (profile + ".ipynb")
        cycle.save(target, clean, exclusive=True)
        assert cycle.code_hash(original) == cycle.code_hash(clean)
        inventory[profile] = {"source": relative, "original_sha256": cycle.digest(raw),
                              "imported_sha256": cycle.digest(target.read_bytes()),
                              "code_sha256": cycle.code_hash(clean), "code_sources_preserved": True,
                              "historical_outputs_removed": True}
    notices = cycle.HERE / "licenses"
    notices.mkdir(exist_ok=False)
    shutil.copyfile(args.source / "franzen_evidence_memory_v1/LICENSE.source.txt", notices / "Franzen-Apache-2.0.txt")
    shutil.copyfile(args.source / "submission_c8b/framework/LICENSE", notices / "ARC-Prize-MIT.txt")
    cycle.save(cycle.HERE / "SOURCES.json", inventory, exclusive=True)
    print("Imported three notebooks with identical code cell sources; originals untouched")


if __name__ == "__main__":
    main()
