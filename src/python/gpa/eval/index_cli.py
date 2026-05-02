"""Read-only reporter for the eval scenario index."""
from __future__ import annotations

import argparse
import sys
from collections import Counter
from pathlib import Path

from gpa.eval.scenario_metadata import iter_scenarios


def build_taxonomy_table(root: Path) -> str:
    counts: Counter = Counter()
    for s in iter_scenarios(root):
        counts[(s.taxonomy.category, s.taxonomy.framework)] += 1
    rows = sorted(counts.items())
    lines = ["| category | framework | count |", "|---|---|---|"]
    for (cat, fw), n in rows:
        lines.append(f"| {cat} | {fw} | {n} |")
    return "\n".join(lines)


def build_backend_table(root: Path) -> str:
    counts: Counter = Counter()
    for s in iter_scenarios(root):
        counts[(s.backend.api, s.backend.status)] += 1
    rows = sorted(counts.items())
    lines = ["| api | status | count |", "|---|---|---|"]
    for (api, st), n in rows:
        lines.append(f"| {api} | {st} | {n} |")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="gpa-eval")
    sub = p.add_subparsers(dest="cmd", required=True)
    px = sub.add_parser("index")
    px.add_argument("--by", choices=["taxonomy", "backend"], default="taxonomy")
    px.add_argument("--root", type=Path, default=Path("tests/eval"))
    args = p.parse_args(argv)
    if args.cmd == "index" and args.by == "taxonomy":
        print(build_taxonomy_table(args.root))
    elif args.cmd == "index" and args.by == "backend":
        print(build_backend_table(args.root))
    return 0


if __name__ == "__main__":
    sys.exit(main())
