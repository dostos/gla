import json
from gla.eval.curation.coverage_log import CoverageLog, CoverageEntry

def test_append_and_read(tmp_path):
    log_path = tmp_path / "coverage-log.jsonl"
    log = CoverageLog(log_path)

    entry = CoverageEntry(
        issue_url="https://github.com/x/y/issues/1",
        reviewed_at="2026-04-17T10:00:00Z",
        source_type="issue",
        triage_verdict="in_scope",
        root_cause_fingerprint="state_leak:bind_between_draws",
        outcome="scenario_committed",
        scenario_id="r1_state_leak",
        tier="core",
        rejection_reason=None,
        predicted_helps="yes",
        observed_helps="yes",
        failure_mode=None,
        eval_summary={"with_gla": {"correct_diagnosis": True, "total_tokens": 1820},
                      "code_only": {"correct_diagnosis": False, "total_tokens": 5940}},
    )
    log.append(entry)

    entries = log.read_all()
    assert len(entries) == 1
    assert entries[0].issue_url == entry.issue_url
    assert entries[0].eval_summary["with_gla"]["total_tokens"] == 1820

def test_contains_url(tmp_path):
    log = CoverageLog(tmp_path / "log.jsonl")
    assert log.contains_url("https://x") is False
    log.append(CoverageEntry(issue_url="https://x", reviewed_at="2026-04-17T10:00:00Z",
                              source_type="issue", triage_verdict="out_of_scope",
                              root_cause_fingerprint=None, outcome="rejected",
                              scenario_id=None, tier=None,
                              rejection_reason="out_of_scope_compile_error",
                              predicted_helps=None, observed_helps=None,
                              failure_mode=None, eval_summary=None))
    assert log.contains_url("https://x") is True


def test_regenerate_coverage_gaps(tmp_path):
    log = CoverageLog(tmp_path / "log.jsonl")
    # 1 committed (predicted/observed both yes), 1 committed (observed no),
    # 1 rejected as duplicate
    log.append(CoverageEntry(
        issue_url="https://x/1", reviewed_at="2026-04-17T10:00:00Z",
        source_type="issue", triage_verdict="in_scope",
        root_cause_fingerprint="state_leak:x", outcome="scenario_committed",
        scenario_id="r1_a", tier="core", rejection_reason=None,
        predicted_helps="yes", observed_helps="yes", failure_mode=None,
        eval_summary=None))
    log.append(CoverageEntry(
        issue_url="https://x/2", reviewed_at="2026-04-17T10:00:00Z",
        source_type="issue", triage_verdict="in_scope",
        root_cause_fingerprint="shader_compile:x", outcome="scenario_committed",
        scenario_id="r2_b", tier="core", rejection_reason=None,
        predicted_helps="yes", observed_helps="no",
        failure_mode="shader_compile_not_exposed", eval_summary=None))
    log.append(CoverageEntry(
        issue_url="https://x/3", reviewed_at="2026-04-17T10:00:00Z",
        source_type="issue", triage_verdict="in_scope",
        root_cause_fingerprint="state_leak:x", outcome="rejected",
        scenario_id=None, tier=None, rejection_reason="duplicate_of_existing_scenario",
        predicted_helps=None, observed_helps=None, failure_mode=None,
        eval_summary=None))

    md_path = tmp_path / "coverage-gaps.md"
    log.regenerate_summary(md_path)

    text = md_path.read_text()
    assert "Issues reviewed: 3" in text
    assert "Scenarios committed: 2" in text
    assert "shader_compile_not_exposed" in text
    assert "duplicate_of_existing_scenario" in text
