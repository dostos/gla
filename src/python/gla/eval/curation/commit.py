from __future__ import annotations
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Any

from gla.eval.curation.coverage_log import CoverageLog, CoverageEntry


def commit_scenario(
    *,
    eval_dir: Path | str,
    scenario_id: str,
    c_source: str,
    md_body: str,
    coverage_log: CoverageLog,
    summary_path: Path | str,
    issue_url: str,
    source_type: str,
    triage_verdict: str,
    fingerprint: Optional[str],
    tier: str,
    predicted_helps: Optional[str],
    observed_helps: Optional[str],
    failure_mode: Optional[str],
    eval_summary: Optional[dict[str, Any]],
) -> None:
    eval_dir = Path(eval_dir)
    eval_dir.mkdir(parents=True, exist_ok=True)
    (eval_dir / f"{scenario_id}.c").write_text(c_source)
    (eval_dir / f"{scenario_id}.md").write_text(md_body)

    coverage_log.append(CoverageEntry(
        issue_url=issue_url,
        reviewed_at=datetime.now(timezone.utc).isoformat(),
        source_type=source_type,
        triage_verdict=triage_verdict,
        root_cause_fingerprint=fingerprint,
        outcome="scenario_committed",
        scenario_id=scenario_id,
        tier=tier,
        rejection_reason=None,
        predicted_helps=predicted_helps,
        observed_helps=observed_helps,
        failure_mode=failure_mode,
        eval_summary=eval_summary,
    ))

    coverage_log.regenerate_summary(summary_path)


def log_rejection(
    *,
    coverage_log: CoverageLog,
    summary_path: Path | str,
    issue_url: str,
    source_type: str,
    triage_verdict: str,
    fingerprint: Optional[str],
    rejection_reason: str,
) -> None:
    coverage_log.append(CoverageEntry(
        issue_url=issue_url,
        reviewed_at=datetime.now(timezone.utc).isoformat(),
        source_type=source_type,
        triage_verdict=triage_verdict,
        root_cause_fingerprint=fingerprint,
        outcome="rejected",
        scenario_id=None,
        tier=None,
        rejection_reason=rejection_reason,
        predicted_helps=None,
        observed_helps=None,
        failure_mode=None,
        eval_summary=None,
    ))
    coverage_log.regenerate_summary(summary_path)
