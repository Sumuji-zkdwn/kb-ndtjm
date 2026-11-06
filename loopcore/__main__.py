"""CLI: python -m loopcore run|audit|status --domain finite|wfs --root PATH."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

from .engine import audit, load_adapter, read_ledger, run_one


def main(argv=None):
    parser = argparse.ArgumentParser(description="Bounded verified operator loop")
    sub = parser.add_subparsers(dest="command", required=True)
    for cmd in ("run", "audit", "status"):
        p = sub.add_parser(cmd)
        p.add_argument("--domain", choices=("finite", "wfs"), required=True)
        p.add_argument("--root", type=Path, required=True)
        if cmd == "audit":
            p.add_argument("--recheck", action="store_true")
    args = parser.parse_args(argv)
    try:
        if args.command == "run":
            result = run_one(args.root, args.domain)
        elif args.command == "audit":
            result = audit(args.root, args.domain, rerun_checks=args.recheck)
        else:
            ledger = read_ledger(args.root, args.domain)
            used = {tuple(sorted(r["model"].items())) for r in ledger["cycles"]}
            remaining = sum(tuple(sorted(x.items())) not in used for x in load_adapter(args.domain).candidates())
            result = {"domain": args.domain, "cycles": len(ledger["cycles"]), "remaining": remaining}
    except Exception as exc:
        print(json.dumps({"passed": False, "error": f"{type(exc).__name__}: {exc}"}), file=sys.stderr)
        return 1
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
