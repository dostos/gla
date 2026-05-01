"""Auto-rollup of journey.jsonl into summary.md.

Counts by terminal_reason, taxonomy_cell histogram, total tokens. No
LLM, no external commands -- pure read-aggregate-write.
"""
from __future__ import annotations

import json
from collections import Counter
from pathlib import Path


def write_summary(*, journey_path: Path, summary_path: Path) -> None:
    """Read ``journey_path`` (JSONL) and write a roll-up Markdown ``summary_path``.

    Aggregates:
    - total candidates (rows in journey.jsonl)
    - total tokens spent (sum of ``tokens.total`` across rows)
    - histogram by ``terminal_reason``
    - histogram by ``select.taxonomy_cell`` (rows without a cell are skipped
      from the histogram but still counted in the total)
    """
    rows = [
        json.loads(line)
        for line in journey_path.read_text().splitlines()
        if line.strip()
    ]
    by_reason: Counter[str] = Counter(
        r.get("terminal_reason", "unknown") for r in rows
    )
    by_cell: Counter[str] = Counter()
    for r in rows:
        cell = (r.get("select") or {}).get("taxonomy_cell")
        if cell:
            by_cell[cell] += 1
    total_tokens = sum((r.get("tokens") or {}).get("total", 0) for r in rows)

    lines: list[str] = []
    lines.append("# Mining run summary")
    lines.append("")
    lines.append(f"- Total candidates: {len(rows)}")
    lines.append(f"- Total tokens spent: {total_tokens}")
    lines.append("")
    lines.append("## By terminal_reason")
    for reason, count in by_reason.most_common():
        lines.append(f"- {reason}: {count}")
    lines.append("")
    lines.append("## By taxonomy_cell")
    for cell, count in by_cell.most_common():
        lines.append(f"- {cell}: {count}")
    lines.append("")
    summary_path.write_text("\n".join(lines), encoding="utf-8")
