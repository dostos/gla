#!/usr/bin/env python3
"""Reclassify R5-R8 scored.json files with the solved/timeout/wrong/infra
verdict.

Usage (from repo root):

    PYTHONPATH=src/python python3 scripts/reclassify_rounds.py

For each round (5, 6, 7, 8):
  - reads ``docs/superpowers/eval/round<N>/scored.json``
  - adds a ``verdict`` field to each run (preserves every other field)
  - writes the file back in place
  - prints a per-round breakdown table

The script is idempotent: running it twice produces identical files (the
``verdict`` field is always re-computed from the source of truth).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

# Support running from the repo root without installing the package.
_REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO_ROOT / "src" / "python"))

from gpa.eval.telemetry import classify_verdict  # noqa: E402


_ROUNDS = (5, 6, 7, 8)
_BUDGET = 40  # R5-R8 all used --max-turns 40.
_VERDICTS = ("solved", "timeout", "wrong", "infra")


def _round_path(round_num: int) -> Path:
    return _REPO_ROOT / "docs" / "superpowers" / "eval" / f"round{round_num}" / "scored.json"


def _reclassify_one(round_num: int) -> tuple[int, dict[str, int], dict[tuple[str, str], dict[str, int]]]:
    path = _round_path(round_num)
    with path.open("r", encoding="utf-8") as fh:
        runs = json.load(fh)

    overall: dict[str, int] = {v: 0 for v in _VERDICTS}
    by_cell: dict[tuple[str, str], dict[str, int]] = {}

    for run in runs:
        verdict = classify_verdict(run, max_turns_budget=_BUDGET)
        run["verdict"] = verdict
        overall[verdict] += 1
        cell = (run.get("mode", "?"), run.get("model", "?"))
        cell_counts = by_cell.setdefault(cell, {v: 0 for v in _VERDICTS})
        cell_counts[verdict] += 1

    # Write back with stable 2-space indent, preserving field order as much
    # as python's dicts allow (insertion-ordered — `verdict` ends up last,
    # which is what we want for diff readability).
    with path.open("w", encoding="utf-8") as fh:
        json.dump(runs, fh, indent=2)
        fh.write("\n")

    return len(runs), overall, by_cell


def _print_breakdown(round_num: int, total: int, overall: dict[str, int]) -> None:
    print(f"Round {round_num} ({total} runs):")
    for v in _VERDICTS:
        n = overall[v]
        pct = (100.0 * n / total) if total else 0.0
        print(f"  {v:<10} {n:4}  ({pct:4.1f}%)")
    print()


def main() -> int:
    for r in _ROUNDS:
        total, overall, _by_cell = _reclassify_one(r)
        _print_breakdown(r, total, overall)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
