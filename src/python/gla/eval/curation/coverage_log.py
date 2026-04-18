from __future__ import annotations
import json
from collections import Counter
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Any


@dataclass
class CoverageEntry:
    issue_url: str
    reviewed_at: str                           # ISO-8601
    source_type: str                           # "issue" | "fix_commit" | "stackoverflow"
    triage_verdict: str                        # "in_scope" | "out_of_scope" | "ambiguous"
    root_cause_fingerprint: Optional[str]
    outcome: str                               # "scenario_committed" | "rejected"
    scenario_id: Optional[str]
    tier: Optional[str]
    rejection_reason: Optional[str]
    predicted_helps: Optional[str]
    observed_helps: Optional[str]
    failure_mode: Optional[str]
    eval_summary: Optional[dict[str, Any]]


class CoverageLog:
    def __init__(self, path: Path | str):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def append(self, entry: CoverageEntry) -> None:
        with self.path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(asdict(entry)) + "\n")

    def read_all(self) -> list[CoverageEntry]:
        if not self.path.exists():
            return []
        out: list[CoverageEntry] = []
        with self.path.open(encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                out.append(CoverageEntry(**json.loads(line)))
        return out

    def contains_url(self, url: str) -> bool:
        return any(e.issue_url == url for e in self.read_all())

    def contains_fingerprint(self, fingerprint: str) -> bool:
        return any(
            e.root_cause_fingerprint == fingerprint
            and e.outcome == "scenario_committed"
            for e in self.read_all()
        )

    def regenerate_summary(self, out_path: Path | str) -> None:
        out_path = Path(out_path)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        entries = self.read_all()

        committed = [e for e in entries if e.outcome == "scenario_committed"]
        rejected = [e for e in entries if e.outcome == "rejected"]

        failure_modes = Counter(
            e.failure_mode for e in committed
            if e.observed_helps == "no" and e.failure_mode
        )
        rejection_reasons = Counter(
            e.rejection_reason for e in rejected if e.rejection_reason
        )

        observed = Counter(
            e.observed_helps for e in committed if e.observed_helps
        )

        lines: list[str] = []
        lines.append("# OpenGPA Coverage Gaps")
        lines.append("")
        lines.append(f"*Regenerated: {datetime.now(timezone.utc).isoformat()}*")
        lines.append("")
        lines.append("## Summary")
        lines.append(f"- Issues reviewed: {len(entries)}")
        lines.append(f"- Scenarios committed: {len(committed)}")
        lines.append(f"- Rejected: {len(rejected)}")
        lines.append("")

        lines.append("## Helpfulness Distribution")
        for verdict in ("yes", "no", "ambiguous"):
            lines.append(f"- observed_helps={verdict}: {observed.get(verdict, 0)}")
        lines.append("")

        if failure_modes:
            lines.append("## Failure Modes (observed_helps=no)")
            for mode, count in failure_modes.most_common():
                example_ids = [e.scenario_id for e in committed
                               if e.failure_mode == mode and e.scenario_id][:3]
                lines.append(f"### {mode} (count: {count})")
                if example_ids:
                    lines.append(f"Example scenarios: {', '.join(example_ids)}")
                lines.append("")

        if rejection_reasons:
            lines.append("## Rejection Breakdown")
            for reason, count in rejection_reasons.most_common():
                lines.append(f"- {reason}: {count}")

        out_path.write_text("\n".join(lines) + "\n")
