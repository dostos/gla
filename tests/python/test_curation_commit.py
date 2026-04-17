from pathlib import Path
from datetime import datetime, timezone
from gla.eval.curation.commit import commit_scenario, log_rejection
from gla.eval.curation.coverage_log import CoverageLog


def test_commit_appends_log_and_writes_summary(tmp_path):
    eval_dir = tmp_path / "eval"
    eval_dir.mkdir()
    log_path = tmp_path / "log.jsonl"
    summary_path = tmp_path / "gaps.md"
    log = CoverageLog(log_path)

    commit_scenario(
        eval_dir=eval_dir,
        scenario_id="r1_test",
        c_source="int main(){}",
        md_body="# R1_TEST\n",
        coverage_log=log,
        summary_path=summary_path,
        issue_url="https://x/1",
        source_type="issue",
        triage_verdict="in_scope",
        fingerprint="state_leak:x",
        tier="core",
        predicted_helps="yes",
        observed_helps="yes",
        failure_mode=None,
        eval_summary={"with_gla": {"correct_diagnosis": True, "total_tokens": 100}},
    )

    assert (eval_dir / "r1_test.c").read_text() == "int main(){}"
    assert (eval_dir / "r1_test.md").exists()
    entries = log.read_all()
    assert len(entries) == 1
    assert entries[0].scenario_id == "r1_test"
    assert summary_path.exists()
    assert "Scenarios committed: 1" in summary_path.read_text()


def test_commit_creates_eval_dir_if_missing(tmp_path):
    # eval_dir does not exist yet — commit_scenario must create it
    eval_dir = tmp_path / "nested" / "eval"
    log = CoverageLog(tmp_path / "log.jsonl")
    summary_path = tmp_path / "gaps.md"

    commit_scenario(
        eval_dir=eval_dir,
        scenario_id="r2_missing_dir",
        c_source="void f(){}",
        md_body="# R2\n",
        coverage_log=log,
        summary_path=summary_path,
        issue_url="https://x/2",
        source_type="issue",
        triage_verdict="in_scope",
        fingerprint=None,
        tier="extended",
        predicted_helps="ambiguous",
        observed_helps="no",
        failure_mode="shader_compile_not_exposed",
        eval_summary=None,
    )

    assert (eval_dir / "r2_missing_dir.c").read_text() == "void f(){}"
    assert (eval_dir / "r2_missing_dir.md").read_text() == "# R2\n"
    entries = log.read_all()
    assert entries[0].outcome == "scenario_committed"
    assert entries[0].failure_mode == "shader_compile_not_exposed"


def test_log_rejection_appends_rejected_entry_and_writes_summary(tmp_path):
    log = CoverageLog(tmp_path / "log.jsonl")
    summary_path = tmp_path / "gaps.md"

    log_rejection(
        coverage_log=log,
        summary_path=summary_path,
        issue_url="https://x/3",
        source_type="fix_commit",
        triage_verdict="out_of_scope",
        fingerprint=None,
        rejection_reason="out_of_scope_compile_error",
    )

    entries = log.read_all()
    assert len(entries) == 1
    entry = entries[0]
    assert entry.outcome == "rejected"
    assert entry.rejection_reason == "out_of_scope_compile_error"
    assert entry.scenario_id is None
    assert entry.tier is None
    assert summary_path.exists()
    assert "Rejected: 1" in summary_path.read_text()
    # No .c or .md files should be written for a rejection
    assert list(tmp_path.glob("*.c")) == []
    assert list(tmp_path.glob("*.md")) == [summary_path]
