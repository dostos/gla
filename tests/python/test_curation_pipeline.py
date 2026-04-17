from unittest.mock import MagicMock
from datetime import datetime, timezone

from gla.eval.curation.pipeline import CurationPipeline, parse_args
from gla.eval.curation.discover import DiscoveryCandidate
from gla.eval.curation.triage import IssueThread, TriageResult
from gla.eval.curation.draft import DraftResult
from gla.eval.curation.validate import ValidationResult
from gla.eval.curation.run_eval import RunEvalResult
from gla.eval.metrics import EvalResult


def test_parse_args_defaults():
    args = parse_args(["--batch-quota", "10"])
    assert args.batch_quota == 10
    assert args.eval_dir == "tests/eval"


def test_parse_args_custom_paths():
    args = parse_args(["--eval-dir", "/tmp/eval", "--log",
                       "/tmp/log.jsonl", "--batch-quota", "5"])
    assert args.eval_dir == "/tmp/eval"
    assert args.log == "/tmp/log.jsonl"


def _eval_result(mode, correct, total):
    return EvalResult(
        scenario_id="r1_fake",
        mode=mode,
        correct_diagnosis=correct,
        correct_fix=correct,
        diagnosis_text="d",
        input_tokens=0,
        output_tokens=0,
        total_tokens=total,
        tool_calls=0,
        num_turns=0,
        time_seconds=0.0,
        model="x",
        timestamp=datetime.now(timezone.utc).isoformat(),
    )


def _draft_md() -> str:
    return (
        "# R1_FAKE\n## Bug\nb\n## Expected Correct Output\ne\n"
        "## Actual Broken Output\na\n"
        "## Ground Truth Diagnosis\n> q\nd\n"
        "## Difficulty Rating\n3/5\n"
        "## Adversarial Principles\n- p\n"
        "## How GLA Helps\nh\n"
        "## Source\n- **URL**: https://github.com/x/y/issues/1\n"
        "## Tier\ncore\n## API\nopengl\n## Framework\nnone\n"
        "## Bug Signature\n```yaml\ntype: framebuffer_dominant_color\n"
        "spec:\n  color: [1.0, 0.0, 0.0, 1.0]\n  tolerance: 0.1\n```\n"
        "## Predicted GLA Helpfulness\n- **Verdict**: yes\n"
        "- **Reasoning**: x\n"
    )


def test_pipeline_happy_path_commits_one_scenario(tmp_path):
    eval_dir = tmp_path / "eval"
    workdir_root = tmp_path / ".wd"
    log_path = tmp_path / "coverage-log.jsonl"
    summary_path = tmp_path / "coverage-gaps.md"

    candidate = DiscoveryCandidate(
        url="https://github.com/x/y/issues/1",
        source_type="issue",
        title="t",
    )
    triage = TriageResult(
        verdict="in_scope",
        fingerprint="state_leak:unique_key",
        rejection_reason=None,
        summary="s",
    )
    draft = DraftResult(
        scenario_id="r1_fake",
        c_source="// SOURCE: https://github.com/x/y/issues/1\nint main(){}",
        md_body=_draft_md(),
    )

    discoverer = MagicMock()
    discoverer.run.return_value = [candidate]
    fetch_fn = MagicMock()
    fetch_fn.return_value = IssueThread(url=candidate.url, title="t", body="b")
    triager = MagicMock()
    triager.triage.return_value = triage
    drafter = MagicMock()
    drafter.draft.return_value = draft
    validator = MagicMock()
    validator.validate.return_value = ValidationResult(
        ok=True,
        reason="ok",
        framebuffer_png=b"x",
        metadata={"draw_call_count": 1, "draw_calls": []},
    )
    run_eval = MagicMock()
    run_eval.run.return_value = RunEvalResult(
        with_gla=_eval_result("with_gla", True, 1000),
        code_only=_eval_result("code_only", False, 4000),
        scorer_ambiguous=False,
    )

    p = CurationPipeline(
        discoverer=discoverer,
        fetch_thread=fetch_fn,
        triager=triager,
        drafter=drafter,
        validator=validator,
        run_eval=run_eval,
        failure_mode_fn=MagicMock(),
        eval_dir=eval_dir,
        workdir_root=workdir_root,
        coverage_log_path=log_path,
        summary_path=summary_path,
    )
    p.run_batch()

    assert (eval_dir / "r1_fake.c").exists()
    assert (eval_dir / "r1_fake.md").exists()
    assert log_path.exists()
    assert "Scenarios committed: 1" in summary_path.read_text()


def test_pipeline_out_of_scope_is_rejected_before_drafting(tmp_path):
    candidate = DiscoveryCandidate(
        url="https://x/1", source_type="issue", title="t"
    )
    triage = TriageResult(
        verdict="out_of_scope",
        fingerprint="other:n_a",
        rejection_reason="out_of_scope_compile_error",
        summary="",
    )

    discoverer = MagicMock()
    discoverer.run.return_value = [candidate]
    fetch = MagicMock()
    fetch.return_value = IssueThread(url=candidate.url, title="t", body="b")
    triager = MagicMock()
    triager.triage.return_value = triage
    drafter = MagicMock()
    validator = MagicMock()
    run_eval = MagicMock()

    p = CurationPipeline(
        discoverer=discoverer,
        fetch_thread=fetch,
        triager=triager,
        drafter=drafter,
        validator=validator,
        run_eval=run_eval,
        failure_mode_fn=MagicMock(),
        eval_dir=tmp_path / "eval",
        workdir_root=tmp_path / ".wd",
        coverage_log_path=tmp_path / "log.jsonl",
        summary_path=tmp_path / "gaps.md",
    )
    p.run_batch()

    drafter.draft.assert_not_called()
    validator.validate.assert_not_called()


def test_pipeline_duplicate_fingerprint_skips_drafting(tmp_path):
    from gla.eval.curation.coverage_log import CoverageLog, CoverageEntry

    log_path = tmp_path / "log.jsonl"
    log = CoverageLog(log_path)
    log.append(
        CoverageEntry(
            issue_url="https://x/old",
            reviewed_at="2026-04-17T10:00:00Z",
            source_type="issue",
            triage_verdict="in_scope",
            root_cause_fingerprint="state_leak:X",
            outcome="scenario_committed",
            scenario_id="r0_old",
            tier="core",
            rejection_reason=None,
            predicted_helps="yes",
            observed_helps="yes",
            failure_mode=None,
            eval_summary=None,
        )
    )

    candidate = DiscoveryCandidate(
        url="https://x/new", source_type="issue", title="t"
    )
    triage = TriageResult(
        verdict="in_scope",
        fingerprint="state_leak:X",
        rejection_reason=None,
        summary="",
    )

    discoverer = MagicMock()
    discoverer.run.return_value = [candidate]
    fetch = MagicMock()
    fetch.return_value = IssueThread(url=candidate.url, title="t", body="b")
    triager = MagicMock()
    triager.triage.return_value = triage
    drafter = MagicMock()
    validator = MagicMock()
    run_eval = MagicMock()

    p = CurationPipeline(
        discoverer=discoverer,
        fetch_thread=fetch,
        triager=triager,
        drafter=drafter,
        validator=validator,
        run_eval=run_eval,
        failure_mode_fn=MagicMock(),
        eval_dir=tmp_path / "eval",
        workdir_root=tmp_path / ".wd",
        coverage_log_path=log_path,
        summary_path=tmp_path / "gaps.md",
    )
    p.run_batch()

    drafter.draft.assert_not_called()
