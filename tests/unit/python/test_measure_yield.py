"""Tests for the curation pipeline's yield-measurement dry-run."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from gpa.eval.curation.coverage_log import CoverageEntry, CoverageLog
from gpa.eval.curation.discover import DiscoveryCandidate
from gpa.eval.curation.draft import DraftResult
from gpa.eval.curation.triage import IssueThread, TriageResult
from gpa.eval.curation.measure_yield import (
    STAGE_ORDER,
    YieldMeasurer,
    YieldRecord,
    _extract_fix_pr_url_from_md,
    _stage_counts,
    parse_args,
    render_report,
    write_jsonl,
)


# --- helpers ---------------------------------------------------------------


def _cand(url: str, *, source_type: str = "issue", title: str = "t"
         ) -> DiscoveryCandidate:
    return DiscoveryCandidate(url=url, source_type=source_type, title=title)


def _make_log(tmp_path: Path) -> CoverageLog:
    return CoverageLog(tmp_path / "coverage.jsonl")


def _seed_log_with_url(log: CoverageLog, url: str,
                       *, outcome: str = "rejected",
                       fingerprint: str = "other:n_a") -> None:
    log.append(CoverageEntry(
        issue_url=url,
        reviewed_at=datetime.now(timezone.utc).isoformat(),
        source_type="issue",
        triage_verdict="out_of_scope" if outcome == "rejected" else "in_scope",
        root_cause_fingerprint=fingerprint,
        outcome=outcome,
        scenario_id=("r1_seeded" if outcome == "scenario_committed" else None),
        tier=None,
        rejection_reason=("out_of_scope_not_rendering_bug"
                          if outcome == "rejected" else None),
        predicted_helps=None,
        observed_helps=None,
        failure_mode=None,
        eval_summary=None,
    ))


def _build_measurer(*, candidates, log, fetch_fn=None, triager=None,
                    drafter=None, with_difficulty_check=False,
                    difficulty_check_fn=None):
    """Construct YieldMeasurer with mocks; returns (measurer, records)."""
    discoverer = MagicMock()
    discoverer.run.return_value = candidates
    if fetch_fn is None:
        fetch_fn = MagicMock(side_effect=lambda u: IssueThread(
            url=u, title="t", body="b"))
    if triager is None:
        triager = MagicMock()
        triager.triage.return_value = TriageResult(
            verdict="in_scope", fingerprint="state_leak:foo",
            rejection_reason=None, summary="s",
        )
    if drafter is None:
        drafter = MagicMock()
        drafter.draft.return_value = DraftResult(
            scenario_id="r_yield_xx",
            c_source="// SOURCE: u\nint main(){}",
            md_body="# scenario\n## Fix\n```yaml\nfix_pr_url: https://x/pr/1\n```\n",
        )

    records: list = []
    m = YieldMeasurer(
        discoverer=discoverer,
        fetch_thread=fetch_fn,
        triager=triager,
        drafter=drafter,
        coverage_log=log,
        records_out=records,
        with_difficulty_check=with_difficulty_check,
        difficulty_check_fn=difficulty_check_fn,
    )
    return m, records


# --- tests -----------------------------------------------------------------


def test_record_default_stage_is_discovered():
    rec = YieldRecord(url="u", source_type="issue", title="t",
                      stage_reached="discovered")
    assert rec.stage_reached == "discovered"
    assert rec.rejection_reason is None
    d = rec.to_dict()
    # rejection_reason is whitelisted to always appear, even when None
    assert "rejection_reason" in d
    assert "fingerprint" in d


def test_url_dedup_short_circuits_before_fetch(tmp_path):
    log = _make_log(tmp_path)
    _seed_log_with_url(log, "https://x/1")

    fetch_fn = MagicMock()
    triager = MagicMock()
    m, records = _build_measurer(
        candidates=[_cand("https://x/1")],
        log=log, fetch_fn=fetch_fn, triager=triager,
    )
    m.run()

    fetch_fn.assert_not_called()
    triager.triage.assert_not_called()
    assert len(records) == 1
    assert records[0].stage_reached == "discovered"
    assert records[0].rejection_reason == "url_dedup"


def test_fetch_failure_logged_as_fetch_failed(tmp_path):
    log = _make_log(tmp_path)
    fetch_fn = MagicMock(side_effect=ConnectionError("network down"))
    m, records = _build_measurer(
        candidates=[_cand("https://x/1")],
        log=log, fetch_fn=fetch_fn,
    )
    m.run()
    assert records[0].stage_reached == "deduped"
    assert records[0].rejection_reason == "fetch_failed"
    assert records[0].notes == "ConnectionError"


def test_out_of_scope_logs_in_scope_rejection(tmp_path):
    log = _make_log(tmp_path)
    triager = MagicMock()
    triager.triage.return_value = TriageResult(
        verdict="out_of_scope", fingerprint="other:n_a",
        rejection_reason="out_of_scope_not_rendering_bug", summary="",
    )
    drafter = MagicMock()
    m, records = _build_measurer(
        candidates=[_cand("https://x/1")],
        log=log, triager=triager, drafter=drafter,
    )
    m.run()
    drafter.draft.assert_not_called()
    assert records[0].stage_reached == "thread_fetched"
    assert records[0].rejection_reason == "out_of_scope_not_rendering_bug"
    assert records[0].fingerprint == "other:n_a"


def test_fingerprint_dedup_against_committed(tmp_path):
    """A fingerprint that matches a previously COMMITTED scenario rejects;
    matching a previously REJECTED entry does NOT (mirrors pipeline)."""
    log = _make_log(tmp_path)
    # Committed seed should cause dedup
    _seed_log_with_url(
        log, "https://x/seed", outcome="scenario_committed",
        fingerprint="state_leak:foo",
    )
    # Rejected seed should NOT cause dedup
    _seed_log_with_url(
        log, "https://x/seed2", outcome="rejected",
        fingerprint="state_leak:bar",
    )

    triager = MagicMock()
    # Use the SAME fingerprint as the committed seed
    triager.triage.return_value = TriageResult(
        verdict="in_scope", fingerprint="state_leak:foo",
        rejection_reason=None, summary="s",
    )
    drafter = MagicMock()
    m, records = _build_measurer(
        candidates=[_cand("https://x/new")],
        log=log, triager=triager, drafter=drafter,
    )
    m.run()
    assert records[0].stage_reached == "in_scope"
    assert records[0].rejection_reason == "duplicate_of_existing_scenario"
    drafter.draft.assert_not_called()


def test_draft_value_error_logged_as_draft_invalid(tmp_path):
    log = _make_log(tmp_path)
    drafter = MagicMock()
    drafter.draft.side_effect = ValueError("Ground Truth missing citation")
    m, records = _build_measurer(
        candidates=[_cand("https://x/1")],
        log=log, drafter=drafter,
    )
    m.run()
    assert records[0].stage_reached == "not_fingerprint_dup"
    assert records[0].rejection_reason == "draft_invalid"
    assert "missing citation" in (records[0].notes or "")


def test_draft_runtime_error_logged_as_draft_error(tmp_path):
    log = _make_log(tmp_path)
    drafter = MagicMock()
    drafter.draft.side_effect = RuntimeError("LLM backend timeout")
    m, records = _build_measurer(
        candidates=[_cand("https://x/1")],
        log=log, drafter=drafter,
    )
    m.run()
    assert records[0].rejection_reason == "draft_error"
    assert records[0].notes == "RuntimeError"


def test_happy_path_reaches_drafted_stage(tmp_path):
    log = _make_log(tmp_path)
    m, records = _build_measurer(
        candidates=[_cand("https://x/1")],
        log=log,
    )
    m.run()
    assert records[0].stage_reached == "drafted"
    assert records[0].rejection_reason is None
    assert records[0].fingerprint == "state_leak:foo"
    assert records[0].fix_pr_url == "https://x/pr/1"
    assert records[0].draft_size_lines is not None
    assert records[0].draft_size_lines > 0


def test_difficulty_check_marks_easy_solved_as_too_easy(tmp_path):
    log = _make_log(tmp_path)
    diff_fn = MagicMock(return_value=True)  # sonnet "solved" the scenario
    m, records = _build_measurer(
        candidates=[_cand("https://x/1")],
        log=log, with_difficulty_check=True, difficulty_check_fn=diff_fn,
    )
    m.run()
    assert records[0].stage_reached == "drafted"
    assert records[0].rejection_reason == "would_be_too_easy"
    diff_fn.assert_called_once()


def test_difficulty_check_passes_unsolved_to_not_too_easy(tmp_path):
    log = _make_log(tmp_path)
    diff_fn = MagicMock(return_value=False)
    m, records = _build_measurer(
        candidates=[_cand("https://x/1")],
        log=log, with_difficulty_check=True, difficulty_check_fn=diff_fn,
    )
    m.run()
    assert records[0].stage_reached == "not_too_easy"
    assert records[0].rejection_reason is None


def test_difficulty_check_exception_treated_as_unsolved(tmp_path):
    """If the sonnet code_only run raises, treat as 'not solved' rather than
    blowing up the whole measurement run."""
    log = _make_log(tmp_path)
    diff_fn = MagicMock(side_effect=RuntimeError("oops"))
    m, records = _build_measurer(
        candidates=[_cand("https://x/1")],
        log=log, with_difficulty_check=True, difficulty_check_fn=diff_fn,
    )
    m.run()
    assert records[0].stage_reached == "not_too_easy"


def test_stage_counts_are_cumulative():
    records = [
        YieldRecord(url="a", source_type="issue", title="t",
                    stage_reached="discovered", rejection_reason="url_dedup"),
        YieldRecord(url="b", source_type="issue", title="t",
                    stage_reached="in_scope",
                    rejection_reason="duplicate_of_existing_scenario"),
        YieldRecord(url="c", source_type="issue", title="t",
                    stage_reached="drafted"),
    ]
    counts = _stage_counts(records)
    assert counts["discovered"] == 3
    assert counts["deduped"] == 2  # b and c passed dedup
    assert counts["thread_fetched"] == 2
    assert counts["in_scope"] == 2
    assert counts["not_fingerprint_dup"] == 1  # only c
    assert counts["drafted"] == 1
    assert counts["not_too_easy"] == 0


def test_render_report_shows_yield_percentages():
    records = [
        YieldRecord(url=f"u{i}", source_type="issue", title="t",
                    stage_reached="discovered", rejection_reason="url_dedup")
        for i in range(8)
    ] + [
        YieldRecord(url="u8", source_type="issue", title="t",
                    stage_reached="drafted"),
        YieldRecord(url="u9", source_type="issue", title="t",
                    stage_reached="in_scope",
                    rejection_reason="duplicate_of_existing_scenario"),
    ]
    out = render_report(
        records, queries_used=5, config_path="cfg.yaml",
        with_difficulty_check=False,
    )
    assert "Mining Yield Baseline" in out
    assert "URLs from discovery:    10" in out
    assert "After URL dedup:        2" in out
    assert "url_dedup: 8" in out
    assert "End-to-end yield" in out


def test_render_report_with_difficulty_check_includes_section():
    records = [
        YieldRecord(url="a", source_type="issue", title="t",
                    stage_reached="not_too_easy"),
        YieldRecord(url="b", source_type="issue", title="t",
                    stage_reached="drafted",
                    rejection_reason="would_be_too_easy"),
    ]
    out = render_report(
        records, queries_used=1, config_path=None,
        with_difficulty_check=True,
    )
    assert "Would-be-not-too-easy" in out


def test_render_report_handles_zero_discovered():
    """Don't divide-by-zero when no candidates were discovered."""
    out = render_report(
        records=[], queries_used=0, config_path=None,
        with_difficulty_check=False,
    )
    assert "n/a" in out  # percentages should fall back to n/a


def test_write_jsonl_produces_one_record_per_line(tmp_path):
    records = [
        YieldRecord(url="a", source_type="issue", title="t",
                    stage_reached="drafted", fingerprint="state_leak:x"),
        YieldRecord(url="b", source_type="issue", title="t",
                    stage_reached="discovered", rejection_reason="url_dedup"),
    ]
    out = tmp_path / "y.jsonl"
    write_jsonl(records, out)
    lines = out.read_text().strip().split("\n")
    assert len(lines) == 2
    parsed = [json.loads(line) for line in lines]
    assert parsed[0]["url"] == "a"
    assert parsed[0]["stage_reached"] == "drafted"
    assert parsed[1]["rejection_reason"] == "url_dedup"


def test_extract_fix_pr_url_from_yaml_block():
    md = (
        "# x\n## Fix\n```yaml\n"
        "fix_pr_url: https://github.com/x/y/pull/123\n"
        "fix_sha: abc\n"
        "```\n"
    )
    assert _extract_fix_pr_url_from_md(md) == "https://github.com/x/y/pull/123"


def test_extract_fix_pr_url_returns_none_when_missing():
    assert _extract_fix_pr_url_from_md("no yaml here") is None
    assert _extract_fix_pr_url_from_md("```yaml\n: invalid yaml\n```") is None


def test_parse_args_defaults():
    args = parse_args([])
    assert args.batch_quota == 20
    assert args.backend == "auto"
    assert args.with_difficulty_check is False
    assert args.skip_draft is False


def test_parse_args_with_difficulty_flag():
    args = parse_args(["--with-difficulty-check", "--report", "/tmp/r.md"])
    assert args.with_difficulty_check is True
    assert args.report == "/tmp/r.md"


def test_dedup_uses_snapshot_so_run_does_not_repeat_disk_io(tmp_path, monkeypatch):
    """The measurer reads coverage_log ONCE on construction, not per candidate.
    We verify by constructing, then mutating the log file's contents — the
    in-memory snapshot should not see the change."""
    log = _make_log(tmp_path)
    _seed_log_with_url(log, "https://x/1")
    cands = [_cand("https://x/1"), _cand("https://x/2")]

    fetch_fn = MagicMock(side_effect=lambda u: IssueThread(
        url=u, title="t", body="b"))
    triager = MagicMock()
    triager.triage.return_value = TriageResult(
        verdict="in_scope", fingerprint="state_leak:foo",
        rejection_reason=None, summary="s",
    )
    m, records = _build_measurer(
        candidates=cands, log=log, fetch_fn=fetch_fn, triager=triager,
    )
    # After construction, mutate the log on disk to add x/2 as well
    _seed_log_with_url(log, "https://x/2")

    m.run()
    # x/1 dedups (was in snapshot), x/2 does NOT (added after snapshot)
    assert records[0].rejection_reason == "url_dedup"
    assert records[1].rejection_reason is None
    # And triager was called exactly once (for x/2)
    assert triager.triage.call_count == 1


def test_does_not_mutate_coverage_log(tmp_path):
    """Critical: dry-run must NEVER append to the production coverage log."""
    log = _make_log(tmp_path)
    log_path = log.path
    initial_size = log_path.stat().st_size if log_path.exists() else 0

    m, records = _build_measurer(
        candidates=[_cand("https://x/1"), _cand("https://x/2")],
        log=log,
    )
    m.run()

    final_size = log_path.stat().st_size if log_path.exists() else 0
    assert final_size == initial_size, "measure_yield must not write to coverage log"


def test_noop_coverage_log_returns_false_and_swallows_appends():
    """The Discoverer-stub log must not gate or persist anything."""
    from gpa.eval.curation.measure_yield import _NoOpCoverageLog
    log = _NoOpCoverageLog()
    assert log.contains_url("https://x/anything") is False
    assert log.contains_fingerprint("state_leak:foo") is False
    # append() must be a silent no-op even with a fully-formed entry
    log.append(CoverageEntry(
        issue_url="u", reviewed_at="t", source_type="issue",
        triage_verdict="out_of_scope", root_cause_fingerprint=None,
        outcome="rejected", scenario_id=None, tier=None,
        rejection_reason="x", predicted_helps=None,
        observed_helps=None, failure_mode=None, eval_summary=None,
    ))
    assert log.read_all() == []


def test_build_components_uses_noop_log_for_discoverer(tmp_path):
    """Regression: when measure_yield builds its components, the Discoverer
    must receive a no-op log (not the real coverage log) so it does not
    pre-dedup or pollute the real log."""
    from unittest.mock import patch
    from gpa.eval.curation.measure_yield import (
        _build_components, _NoOpCoverageLog, parse_args,
    )

    log_path = tmp_path / "real-log.jsonl"
    args = parse_args([
        "--log", str(log_path),
        "--backend", "claude-code",
    ])
    # Patch out the heavy LLM/search constructors — we only care which log
    # the Discoverer receives.
    with patch("gpa.eval.curation.discover.GitHubSearch"), \
         patch("gpa.eval.curation.discover.StackExchangeSearch"), \
         patch("gpa.eval.curation.llm_client.ClaudeCodeLLMClient"):
        real_log, disc, fetch_fn, triager, drafter = _build_components(
            args, queries={"issue": [], "commit": [], "stackoverflow": []},
            batch_quota=5,
        )
    # The returned log is the REAL one (used by YieldMeasurer for dedup).
    assert real_log.path == log_path
    # The Discoverer received the NO-OP log.
    assert isinstance(disc._log, _NoOpCoverageLog)


def test_progress_fn_called_with_per_candidate_status(tmp_path):
    """The optional progress_fn lets the CLI surface live status during a run."""
    log = _make_log(tmp_path)
    msgs: list[str] = []
    discoverer = MagicMock()
    discoverer.run.return_value = [
        _cand("https://x/1"), _cand("https://x/2"),
    ]
    triager = MagicMock()
    triager.triage.return_value = TriageResult(
        verdict="in_scope", fingerprint="state_leak:x",
        rejection_reason=None, summary="s",
    )
    fetch_fn = MagicMock(side_effect=lambda u: IssueThread(
        url=u, title="t", body="b"))
    drafter = MagicMock()
    drafter.draft.return_value = DraftResult(
        scenario_id="r_yield_xx",
        c_source="// SOURCE: u\nint main(){}",
        md_body="# x\n## Fix\n```yaml\nfix_pr_url: https://x/pr/1\n```\n",
    )

    records: list = []
    m = YieldMeasurer(
        discoverer=discoverer, fetch_thread=fetch_fn, triager=triager,
        drafter=drafter, coverage_log=log, records_out=records,
        progress_fn=msgs.append,
    )
    m.run()

    # Should announce candidates discovered, two per-candidate processing
    # lines, and two stage-update lines.
    joined = "\n".join(msgs)
    assert "discovered 2" in joined
    assert "[1/2]" in joined
    assert "[2/2]" in joined
    assert joined.count("-> stage=drafted") == 2


def test_stage_order_constant_is_complete():
    """STAGE_ORDER must include every stage emitted by YieldMeasurer."""
    expected = {"discovered", "deduped", "thread_fetched", "in_scope",
                "not_fingerprint_dup", "drafted", "not_too_easy"}
    assert set(STAGE_ORDER) == expected
