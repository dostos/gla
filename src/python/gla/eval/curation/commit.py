from __future__ import annotations
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Any

from gla.eval.curation.coverage_log import CoverageLog, CoverageEntry


def _append_to_build_bazel(eval_dir: Path, scenario_id: str) -> None:
    """No-op shim kept for backward compatibility.

    Scenario directories are now auto-discovered by a ``glob()`` in
    ``tests/eval/BUILD.bazel``, so there is no hardcoded list to maintain.
    This helper is kept (as a no-op) so any callers that still reference
    it continue to work.
    """
    return


def commit_scenario(
    *,
    eval_dir: Path | str,
    scenario_id: str,
    files: Optional[dict[str, str]] = None,
    c_source: Optional[str] = None,   # deprecated: use files
    md_body: Optional[str] = None,    # deprecated: use files
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
    # Backward-compat: if files is None, build from c_source + md_body.
    if files is None:
        if c_source is None or md_body is None:
            raise ValueError(
                "commit_scenario requires either `files` or both `c_source` and `md_body`"
            )
        files = {"main.c": c_source, "scenario.md": md_body}

    eval_dir = Path(eval_dir)
    scenario_dir = eval_dir / scenario_id
    scenario_dir.mkdir(parents=True, exist_ok=True)
    for filename, content in files.items():
        file_path = scenario_dir / filename
        file_path.parent.mkdir(parents=True, exist_ok=True)
        file_path.write_text(content)
    # BUILD.bazel is now glob-driven — no explicit append needed. The no-op
    # call is retained for backward compatibility with any external callers.
    _append_to_build_bazel(eval_dir, scenario_id)

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
