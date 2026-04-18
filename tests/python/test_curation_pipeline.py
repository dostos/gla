from pathlib import Path
from unittest.mock import MagicMock
from datetime import datetime, timezone

from gla.eval.curation.pipeline import CurationPipeline, parse_args
from gla.eval.curation.discover import DiscoveryCandidate
from gla.eval.curation.triage import IssueThread, TriageResult
from gla.eval.curation.draft import DraftResult
from gla.eval.curation.validate import ValidationResult
from gla.eval.curation.run_eval import RunEvalResult
from gla.eval.metrics import EvalResult


def test_load_config_overrides_default_queries(tmp_path):
    from gla.eval.curation.pipeline import load_config
    cfg_path = tmp_path / "cfg.yaml"
    cfg_path.write_text(
        "batch_quota: 5\n"
        "queries:\n"
        "  issue:\n"
        "    - repo:test/repo is:issue label:\"bug\"\n"
        "  commit: []\n"
    )
    cfg = load_config(str(cfg_path))
    assert cfg["batch_quota"] == 5
    assert cfg["queries"]["issue"] == ["repo:test/repo is:issue label:\"bug\""]


def test_parse_args_defaults():
    args = parse_args(["--batch-quota", "10"])
    assert args.batch_quota == 10
    assert args.eval_dir == "tests/eval"


def test_parse_args_backend_default_is_auto():
    args = parse_args([])
    assert args.backend == "auto"


def test_parse_args_backend_claude_code():
    args = parse_args(["--backend", "claude-code"])
    assert args.backend == "claude-code"


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

    assert (eval_dir / "r1_fake" / "main.c").exists()
    assert (eval_dir / "r1_fake" / "scenario.md").exists()
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


def test_pipeline_ambiguous_reaches_drafter(tmp_path):
    """triage=ambiguous no longer early-rejects; the drafter is invoked and
    decides via its own validation whether the candidate can become a scenario."""
    from unittest.mock import MagicMock
    from gla.eval.curation.pipeline import CurationPipeline
    from gla.eval.curation.discover import DiscoveryCandidate
    from gla.eval.curation.triage import IssueThread, TriageResult

    candidate = DiscoveryCandidate(url="https://x/1", source_type="issue", title="t")
    triage = TriageResult(verdict="ambiguous", fingerprint="other:unknown",
                          rejection_reason=None, summary="unclear")

    discoverer = MagicMock(); discoverer.run.return_value = [candidate]
    fetch = MagicMock(); fetch.return_value = IssueThread(url=candidate.url, title="t", body="b")
    triager = MagicMock(); triager.triage.return_value = triage
    drafter = MagicMock()
    # Simulate drafter blocking (no citation available even with linked context)
    drafter.draft.side_effect = ValueError("Ground Truth Diagnosis missing upstream citation")
    validator = MagicMock()
    run_eval = MagicMock()

    p = CurationPipeline(
        discoverer=discoverer, fetch_thread=fetch, triager=triager,
        drafter=drafter, validator=validator, run_eval=run_eval,
        failure_mode_fn=MagicMock(),
        eval_dir=tmp_path / "eval", workdir_root=tmp_path / ".wd",
        coverage_log_path=tmp_path / "log.jsonl",
        summary_path=tmp_path / "gaps.md",
    )
    p.run_batch()

    # Drafter WAS called — ambiguous no longer short-circuits
    drafter.draft.assert_called_once()
    # Since drafter raised, validator and run_eval were NOT called
    validator.validate.assert_not_called()
    run_eval.run.assert_not_called()
    # Coverage log has a rejection entry with reason not_reproducible (drafter failed)
    from gla.eval.curation.coverage_log import CoverageLog
    log = CoverageLog(tmp_path / "log.jsonl")
    entries = log.read_all()
    assert len(entries) == 1
    assert entries[0].outcome == "rejected"
    assert entries[0].rejection_reason == "not_reproducible"
    assert entries[0].triage_verdict == "ambiguous"


def test_pipeline_ambiguous_drafter_succeeds(tmp_path):
    """When drafter can handle the ambiguous case (e.g., via linked PR context),
    the scenario is committed normally."""
    from unittest.mock import MagicMock
    from gla.eval.curation.pipeline import CurationPipeline
    from gla.eval.curation.discover import DiscoveryCandidate
    from gla.eval.curation.triage import IssueThread, TriageResult
    from gla.eval.curation.draft import DraftResult
    from gla.eval.curation.validate import ValidationResult
    from gla.eval.curation.run_eval import RunEvalResult
    from gla.eval.metrics import EvalResult
    from datetime import datetime, timezone

    candidate = DiscoveryCandidate(url="https://github.com/x/y/issues/1",
                                    source_type="issue", title="t")
    triage = TriageResult(verdict="ambiguous", fingerprint="depth_precision:foo",
                          rejection_reason=None, summary="diagnosis in linked PR")
    draft = DraftResult(
        scenario_id="r1_fake",
        c_source="// SOURCE: https://github.com/x/y/issues/1\nint main(){}",
        md_body=("# R1_FAKE\n## Bug\nb\n## Expected Correct Output\ne\n"
                 "## Actual Broken Output\na\n## Ground Truth Diagnosis\n> q\nd\n"
                 "## Difficulty Rating\n3/5\n## Adversarial Principles\n- p\n"
                 "## How GLA Helps\nh\n## Source\n- **URL**: https://github.com/x/y/issues/1\n"
                 "## Tier\ncore\n## API\nopengl\n## Framework\nnone\n"
                 "## Bug Signature\n```yaml\ntype: framebuffer_dominant_color\n"
                 "spec:\n  color: [1.0, 0.0, 0.0, 1.0]\n  tolerance: 0.1\n```\n"
                 "## Predicted GLA Helpfulness\n- **Verdict**: yes\n- **Reasoning**: x\n"))

    discoverer = MagicMock(); discoverer.run.return_value = [candidate]
    fetch = MagicMock(); fetch.return_value = IssueThread(url=candidate.url, title="t", body="b")
    triager = MagicMock(); triager.triage.return_value = triage
    drafter = MagicMock(); drafter.draft.return_value = draft
    validator = MagicMock()
    validator.validate.return_value = ValidationResult(ok=True, reason="ok",
                                                       framebuffer_png=b"x",
                                                       metadata={"draw_call_count": 1,
                                                                 "draw_calls": []})
    def _mk(mode, correct, total):
        return EvalResult(scenario_id="r1_fake", mode=mode, correct_diagnosis=correct,
                          correct_fix=correct, diagnosis_text="d",
                          input_tokens=0, output_tokens=0, total_tokens=total,
                          tool_calls=0, num_turns=0, time_seconds=0.0,
                          model="x", timestamp=datetime.now(timezone.utc).isoformat())
    run_eval = MagicMock()
    run_eval.run.return_value = RunEvalResult(
        with_gla=_mk("with_gla", True, 1000),
        code_only=_mk("code_only", False, 4000),
        scorer_ambiguous=False)

    p = CurationPipeline(
        discoverer=discoverer, fetch_thread=fetch, triager=triager,
        drafter=drafter, validator=validator, run_eval=run_eval,
        failure_mode_fn=MagicMock(),
        eval_dir=tmp_path / "eval", workdir_root=tmp_path / ".wd",
        coverage_log_path=tmp_path / "log.jsonl",
        summary_path=tmp_path / "gaps.md",
    )
    p.run_batch()

    # Scenario was committed
    assert (tmp_path / "eval" / "r1_fake" / "main.c").exists()
    # Coverage log shows scenario_committed despite ambiguous triage
    from gla.eval.curation.coverage_log import CoverageLog
    log = CoverageLog(tmp_path / "log.jsonl")
    entries = log.read_all()
    assert len(entries) == 1
    assert entries[0].outcome == "scenario_committed"
    assert entries[0].triage_verdict == "ambiguous"


def test_pipeline_caches_triage_across_runs(tmp_path):
    """A second run on the same URL must not re-call the triager or drafter."""
    candidate = DiscoveryCandidate(
        url="https://github.com/x/y/issues/99",
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
        c_source="// SOURCE: https://github.com/x/y/issues/99\nint main(){}",
        md_body=_draft_md(),
    )

    thread = IssueThread(url=candidate.url, title="t", body="b", comments=["c1"])

    def _mk_components(eval_dir: Path, log_path: Path, summary: Path):
        discoverer = MagicMock()
        discoverer.run.return_value = [candidate]
        fetch_fn = MagicMock()
        fetch_fn.return_value = thread
        triager = MagicMock()
        triager.triage.return_value = triage
        drafter = MagicMock()
        drafter.draft.return_value = draft
        validator = MagicMock()
        validator.validate.return_value = ValidationResult(
            ok=True, reason="ok",
            framebuffer_png=b"x",
            metadata={"draw_call_count": 1, "draw_calls": []},
        )
        run_eval = MagicMock()
        run_eval.run.return_value = RunEvalResult(
            with_gla=_eval_result("with_gla", True, 1000),
            code_only=_eval_result("code_only", False, 4000),
            scorer_ambiguous=False,
        )
        pipeline = CurationPipeline(
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
            summary_path=summary,
        )
        return pipeline, triager, drafter

    eval_dir1 = tmp_path / "eval1"
    eval_dir2 = tmp_path / "eval2"
    workdir_root = tmp_path / ".wd"  # shared across runs
    log1 = tmp_path / "log1.jsonl"
    log2 = tmp_path / "log2.jsonl"
    summary1 = tmp_path / "gaps1.md"
    summary2 = tmp_path / "gaps2.md"

    # First run
    p1, triager1, drafter1 = _mk_components(eval_dir1, log1, summary1)
    p1.run_batch()
    assert triager1.triage.call_count == 1
    assert drafter1.draft.call_count == 1

    # Second run with shared workdir_root: triage/draft should be cached.
    p2, triager2, drafter2 = _mk_components(eval_dir2, log2, summary2)
    p2.run_batch()
    assert triager2.triage.call_count == 0, \
        "Triage should be cached on second run"
    assert drafter2.draft.call_count == 0, \
        "Draft should be cached on second run"


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


def test_pipeline_end_to_end_with_fixture(tmp_path):
    """Full orchestrator run with an LLM that returns a valid canned draft.

    Bazel build and runtime capture are stubbed out; symptom-match uses a
    real framebuffer fixture.
    """
    import json
    from gla.eval.curation.pipeline import CurationPipeline
    from gla.eval.curation.discover import DiscoveryCandidate
    from gla.eval.curation.triage import IssueThread, Triage
    from gla.eval.curation.draft import Draft
    from gla.eval.curation.validate import Validator
    from gla.eval.curation.run_eval import RunEvalResult
    from gla.eval.metrics import EvalResult
    from datetime import datetime, timezone

    # Canned LLM responses: one for triage, one for draft, no failure-mode needed
    fixture = json.loads(Path(
        __file__).parent.joinpath(
        "fixtures/curation/issue_threads/threejs_simple_state_leak.json").read_text())

    from unittest.mock import MagicMock
    from gla.eval.curation.llm_client import LLMResponse

    triage_resp = (
        '```json\n{"triage_verdict":"in_scope",'
        '"root_cause_fingerprint":"state_leak:material_clone_tex_binding",'
        '"rejection_reason":null,"summary":"state leak"}\n```'
    )

    c_src = ('// SOURCE: ' + fixture["url"] + '\n'
             '#include <GL/gl.h>\nint main(){return 0;}\n')
    md_body = (
        "# R1_MATERIAL_CLONE: Second mesh inherits first mesh's texture\n\n"
        "## Bug\nx\n\n"
        "## Expected Correct Output\nDifferent textures per mesh.\n\n"
        "## Actual Broken Output\nSame texture on both meshes.\n\n"
        "## Ground Truth Diagnosis\n"
        '> "known state-leak caused by the cloned material not re-binding its texture" '
        '(from upstream maintainer)\n\n'
        "## Difficulty Rating\n3/5\n\n"
        "## Adversarial Principles\n- Stale state\n\n"
        "## How GLA Helps\ninspect_drawcall exposes the stale binding.\n\n"
        "## Source\n"
        f"- **URL**: {fixture['url']}\n"
        "- **Type**: issue\n"
        "- **Date**: 2024-01-01\n"
        "- **Commit SHA**: (n/a)\n"
        "- **Attribution**: Reported by @alice\n\n"
        "## Tier\ncore\n\n## API\nopengl\n\n## Framework\nnone\n\n"
        "## Bug Signature\n```yaml\ntype: framebuffer_dominant_color\n"
        "spec:\n  color: [1.0, 0.0, 0.0, 1.0]\n  tolerance: 0.1\n```\n\n"
        "## Predicted GLA Helpfulness\n- **Verdict**: yes\n"
        "- **Reasoning**: inspect_drawcall exposes the stale binding.\n"
    )
    draft_resp = (
        "<!-- filename: main.c -->\n"
        f"```c\n{c_src}```\n\n"
        "<!-- filename: scenario.md -->\n"
        f"```markdown\n{md_body}```\n"
    )

    llm = MagicMock()
    llm.complete.side_effect = [
        LLMResponse(text=triage_resp, input_tokens=0, output_tokens=0,
                    cache_creation_input_tokens=0, cache_read_input_tokens=0,
                    stop_reason="end_turn"),
        LLMResponse(text=draft_resp, input_tokens=0, output_tokens=0,
                    cache_creation_input_tokens=0, cache_read_input_tokens=0,
                    stop_reason="end_turn"),
    ]

    triager = Triage(llm_client=llm)
    drafter = Draft(llm_client=llm)

    # Validator uses a fake runner that returns a red PNG
    red_png = Path(__file__).parent.joinpath(
        "fixtures/curation/framebuffers/solid_red.png").read_bytes()
    fake_runner = MagicMock()
    fake_runner.build_and_capture.return_value = {
        "framebuffer_png": red_png,
        "metadata": {"draw_call_count": 2, "draw_calls": []},
    }
    validator = Validator(eval_dir=tmp_path / "eval", runner=fake_runner)

    # Run-eval returns with_gla correct, code_only wrong
    def _mk(mode, correct, total):
        return EvalResult(scenario_id="r1_material_clone_second_mesh_inherits_first_mesh_s_texture",
                          mode=mode, correct_diagnosis=correct, correct_fix=correct,
                          diagnosis_text="d", input_tokens=0, output_tokens=0,
                          total_tokens=total, tool_calls=0, num_turns=0,
                          time_seconds=0.0, model="x",
                          timestamp=datetime.now(timezone.utc).isoformat())
    run_eval = MagicMock()
    run_eval.run.return_value = RunEvalResult(
        with_gla=_mk("with_gla", True, 1000),
        code_only=_mk("code_only", False, 4000),
        scorer_ambiguous=False,
    )

    discoverer = MagicMock()
    discoverer.run.return_value = [
        DiscoveryCandidate(url=fixture["url"], source_type="issue",
                           title=fixture["title"]),
    ]
    fetch = MagicMock()
    fetch.return_value = IssueThread(url=fixture["url"], title=fixture["title"],
                                      body=fixture["body"],
                                      comments=fixture["comments"])

    p = CurationPipeline(
        discoverer=discoverer, fetch_thread=fetch, triager=triager,
        drafter=drafter, validator=validator, run_eval=run_eval,
        failure_mode_fn=MagicMock(),
        eval_dir=tmp_path / "eval", workdir_root=tmp_path / ".wd",
        coverage_log_path=tmp_path / "log.jsonl",
        summary_path=tmp_path / "gaps.md",
    )
    p.run_batch()

    committed = list((tmp_path / "eval").glob("r1_*/main.c"))
    assert len(committed) == 1
    md_text = (committed[0].parent / "scenario.md").read_text()
    assert "Observed GLA Helpfulness" in md_text
    assert "**Verdict**: yes" in md_text
    summary = (tmp_path / "gaps.md").read_text()
    assert "Scenarios committed: 1" in summary


def test_pipeline_skip_validate_commits_without_running_validator(tmp_path):
    """With skip_validate=True, the pipeline writes scenario files and logs
    the commit, without invoking the validator or run_eval."""
    from unittest.mock import MagicMock
    from gla.eval.curation.pipeline import CurationPipeline
    from gla.eval.curation.discover import DiscoveryCandidate
    from gla.eval.curation.triage import IssueThread, TriageResult
    from gla.eval.curation.draft import DraftResult

    candidate = DiscoveryCandidate(url="https://github.com/x/y/issues/1",
                                    source_type="issue", title="t")
    triage = TriageResult(verdict="in_scope", fingerprint="state_leak:unique",
                           rejection_reason=None, summary="s")
    draft = DraftResult(scenario_id="r1_test",
                         c_source="// SOURCE: https://github.com/x/y/issues/1\nint main(){}",
                         md_body="# R1_TEST\n## Predicted GLA Helpfulness\n- **Verdict**: yes\n")

    discoverer = MagicMock(); discoverer.run.return_value = [candidate]
    fetch = MagicMock(); fetch.return_value = IssueThread(url=candidate.url, title="t", body="b")
    triager = MagicMock(); triager.triage.return_value = triage
    drafter = MagicMock(); drafter.draft.return_value = draft
    validator = MagicMock()  # should NOT be called
    run_eval = MagicMock()   # should NOT be called

    p = CurationPipeline(
        discoverer=discoverer, fetch_thread=fetch, triager=triager,
        drafter=drafter, validator=validator, run_eval=run_eval,
        failure_mode_fn=MagicMock(),
        eval_dir=tmp_path / "eval", workdir_root=tmp_path / ".wd",
        coverage_log_path=tmp_path / "log.jsonl",
        summary_path=tmp_path / "gaps.md",
        skip_validate=True,
    )
    p.run_batch()

    validator.validate.assert_not_called()
    run_eval.run.assert_not_called()
    assert (tmp_path / "eval" / "r1_test" / "main.c").exists()
    assert (tmp_path / "eval" / "r1_test" / "scenario.md").exists()


def test_parse_args_no_validate_flag():
    from gla.eval.curation.pipeline import parse_args
    args = parse_args(["--no-validate"])
    assert args.no_validate is True
    args_default = parse_args([])
    assert args_default.no_validate is False
