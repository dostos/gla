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

    assert (eval_dir / "r1_test" / "main.c").read_text() == "int main(){}"
    assert (eval_dir / "r1_test" / "scenario.md").exists()
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

    assert (eval_dir / "r2_missing_dir" / "main.c").read_text() == "void f(){}"
    assert (eval_dir / "r2_missing_dir" / "scenario.md").read_text() == "# R2\n"
    entries = log.read_all()
    assert entries[0].outcome == "scenario_committed"
    assert entries[0].failure_mode == "shader_compile_not_exposed"


def test_commit_leaves_build_bazel_untouched(tmp_path):
    """BUILD.bazel is now glob-driven: commit_scenario must not modify it."""
    eval_dir = tmp_path / "eval"
    eval_dir.mkdir()
    original = (
        'load("@rules_cc//cc:defs.bzl", "cc_binary")\n\n'
        '_SCENARIO_MDS = glob(["*/scenario.md"])\n'
        '_SCENARIO_DIRS = [m[:-len("/scenario.md")] for m in _SCENARIO_MDS]\n'
        '[cc_binary(name=d, srcs=glob([d + "/*.c"]), linkopts=["-lGL"]) '
        'for d in _SCENARIO_DIRS if glob([d + "/*.c"])]\n'
    )
    (eval_dir / "BUILD.bazel").write_text(original)
    log = CoverageLog(tmp_path / "log.jsonl")
    commit_scenario(
        eval_dir=eval_dir, scenario_id="r1_test",
        c_source="int main(){}", md_body="# x",
        coverage_log=log, summary_path=tmp_path / "gaps.md",
        issue_url="https://x/1", source_type="issue",
        triage_verdict="in_scope", fingerprint="state_leak:x",
        tier="core", predicted_helps="yes", observed_helps="yes",
        failure_mode=None, eval_summary=None,
    )
    # BUILD.bazel is auto-discovering scenarios — commit_scenario must not
    # edit it at all.
    assert (eval_dir / "BUILD.bazel").read_text() == original


def test_commit_without_build_bazel_is_fine(tmp_path):
    """If BUILD.bazel doesn't exist, commit_scenario is still fine."""
    eval_dir = tmp_path / "eval"
    eval_dir.mkdir()
    log = CoverageLog(tmp_path / "log.jsonl")
    commit_scenario(
        eval_dir=eval_dir, scenario_id="r2_nobuild",
        c_source="int main(){}", md_body="# x",
        coverage_log=log, summary_path=tmp_path / "gaps.md",
        issue_url="https://x/2", source_type="issue",
        triage_verdict="in_scope", fingerprint="state_leak:y",
        tier="core", predicted_helps="yes", observed_helps="yes",
        failure_mode=None, eval_summary=None,
    )
    # no exception; no build file created
    assert not (eval_dir / "BUILD.bazel").exists()
    # Scenario is written to its directory
    assert (eval_dir / "r2_nobuild" / "main.c").exists()
    assert (eval_dir / "r2_nobuild" / "scenario.md").exists()


def test_commit_scenario_writes_multiple_files(tmp_path):
    eval_dir = tmp_path / "eval"
    log_path = tmp_path / "log.jsonl"
    summary_path = tmp_path / "gaps.md"
    log = CoverageLog(log_path)

    commit_scenario(
        eval_dir=eval_dir,
        scenario_id="r1_test",
        files={
            "main.c": "int main(){}",
            "helper.c": "void helper(void) {}",
            "shader.glsl": "#version 330\n",
            "scenario.md": "# R1_TEST",
        },
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
        eval_summary=None,
    )

    assert (eval_dir / "r1_test" / "main.c").read_text() == "int main(){}"
    assert (eval_dir / "r1_test" / "helper.c").read_text() == "void helper(void) {}"
    assert (eval_dir / "r1_test" / "shader.glsl").read_text().startswith("#version 330")
    assert (eval_dir / "r1_test" / "scenario.md").read_text() == "# R1_TEST"


def test_commit_scenario_writes_nested_upstream_snapshot(tmp_path):
    """Files with forward-slash paths create subdirs."""
    eval_dir = tmp_path / "eval"
    log = CoverageLog(tmp_path / "log.jsonl")

    commit_scenario(
        eval_dir=eval_dir,
        scenario_id="r2_test",
        files={
            "main.c": "int main(){}",
            "scenario.md": "# R2_TEST",
            "upstream_snapshot/original.c": "// verbatim upstream\nvoid foo(){}",
        },
        coverage_log=log,
        summary_path=tmp_path / "gaps.md",
        issue_url="https://x/2",
        source_type="issue",
        triage_verdict="in_scope",
        fingerprint="state_leak:y",
        tier="core",
        predicted_helps="yes",
        observed_helps="yes",
        failure_mode=None,
        eval_summary=None,
    )
    snapshot_path = eval_dir / "r2_test" / "upstream_snapshot" / "original.c"
    assert snapshot_path.exists()
    assert "verbatim upstream" in snapshot_path.read_text()


def test_commit_scenario_legacy_kwargs_still_work(tmp_path):
    """Old c_source/md_body kwargs still work (pipeline not migrated yet)."""
    eval_dir = tmp_path / "eval"
    log = CoverageLog(tmp_path / "log.jsonl")

    commit_scenario(
        eval_dir=eval_dir,
        scenario_id="r3_legacy",
        c_source="int main(){}",
        md_body="# R3_LEGACY",
        coverage_log=log,
        summary_path=tmp_path / "gaps.md",
        issue_url="https://x/3",
        source_type="issue",
        triage_verdict="in_scope",
        fingerprint="state_leak:z",
        tier="core",
        predicted_helps="yes",
        observed_helps="yes",
        failure_mode=None,
        eval_summary=None,
    )
    assert (eval_dir / "r3_legacy" / "main.c").exists()
    assert (eval_dir / "r3_legacy" / "scenario.md").exists()


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
