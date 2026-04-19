from pathlib import Path
from unittest.mock import MagicMock
from datetime import datetime, timezone

from gpa.eval.curation.pipeline import CurationPipeline, parse_args
from gpa.eval.curation.discover import DiscoveryCandidate
from gpa.eval.curation.triage import IssueThread, TriageResult
from gpa.eval.curation.draft import DraftResult
from gpa.eval.curation.validate import ValidationResult
from gpa.eval.curation.run_eval import RunEvalResult
from gpa.eval.metrics import EvalResult


def test_load_config_overrides_default_queries(tmp_path):
    from gpa.eval.curation.pipeline import load_config
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
        "# R1_FAKE\n## User Report\nb\n## Expected Correct Output\ne\n"
        "## Actual Broken Output\na\n"
        "## Ground Truth\n> q\nd\n"
        "## Difficulty Rating\n3/5\n"
        "## Adversarial Principles\n- p\n"
        "## How GPA Helps\nh\n"
        "## Source\n- **URL**: https://github.com/x/y/issues/1\n"
        "## Tier\ncore\n## API\nopengl\n## Framework\nnone\n"
        "## Bug Signature\n```yaml\ntype: framebuffer_dominant_color\n"
        "spec:\n  color: [1.0, 0.0, 0.0, 1.0]\n  tolerance: 0.1\n```\n"
        "## Predicted GPA Helpfulness\n- **Verdict**: yes\n"
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


def test_pipeline_skips_previously_seen_url_without_retriage(tmp_path):
    """A URL already in the coverage log (committed OR rejected in a prior
    run) must be short-circuited before we re-fetch/re-triage it — otherwise
    repeated mining runs re-burn API tokens on the same threads."""
    eval_dir = tmp_path / "eval"
    workdir_root = tmp_path / ".wd"
    log_path = tmp_path / "coverage-log.jsonl"
    summary_path = tmp_path / "coverage-gaps.md"

    # Seed the coverage log with a pre-existing rejection for this URL.
    from gpa.eval.curation.coverage_log import CoverageLog, CoverageEntry
    seeded = CoverageLog(log_path)
    seeded.append(CoverageEntry(
        issue_url="https://github.com/x/y/issues/1",
        reviewed_at=datetime.now(timezone.utc).isoformat(),
        source_type="issue",
        triage_verdict="out_of_scope",
        root_cause_fingerprint="other:n_a",
        outcome="rejected",
        scenario_id=None,
        tier=None,
        rejection_reason="out_of_scope_not_rendering_bug",
        predicted_helps=None,
        observed_helps=None,
        failure_mode=None,
        eval_summary=None,
    ))

    candidate = DiscoveryCandidate(
        url="https://github.com/x/y/issues/1", source_type="issue", title="t"
    )
    discoverer = MagicMock()
    discoverer.run.return_value = [candidate]
    fetch = MagicMock()
    triager = MagicMock()

    p = CurationPipeline(
        discoverer=discoverer,
        fetch_thread=fetch,
        triager=triager,
        drafter=MagicMock(),
        validator=MagicMock(),
        run_eval=MagicMock(),
        failure_mode_fn=MagicMock(),
        eval_dir=eval_dir,
        workdir_root=workdir_root,
        coverage_log_path=log_path,
        summary_path=summary_path,
    )
    p.run_batch()

    # Fetch / triage must NOT have been called — URL was already reviewed.
    fetch.assert_not_called()
    triager.triage.assert_not_called()


def test_pipeline_out_of_scope_is_rejected_before_drafting(tmp_path):
    candidate = DiscoveryCandidate(
        url="https://x/1", source_type="issue", title="t"
    )
    triage = TriageResult(
        verdict="out_of_scope",
        fingerprint="other:n_a",
        rejection_reason="out_of_scope_not_rendering_bug",
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
    from gpa.eval.curation.pipeline import CurationPipeline
    from gpa.eval.curation.discover import DiscoveryCandidate
    from gpa.eval.curation.triage import IssueThread, TriageResult

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

    # Drafter WAS called — ambiguous no longer short-circuits. Pipeline retries
    # once on ValueError, so two calls total before giving up.
    assert drafter.draft.call_count == 2
    # Since drafter raised on both attempts, validator and run_eval were NOT called
    validator.validate.assert_not_called()
    run_eval.run.assert_not_called()
    # Coverage log has a rejection entry with reason not_reproducible (drafter failed)
    from gpa.eval.curation.coverage_log import CoverageLog
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
    from gpa.eval.curation.pipeline import CurationPipeline
    from gpa.eval.curation.discover import DiscoveryCandidate
    from gpa.eval.curation.triage import IssueThread, TriageResult
    from gpa.eval.curation.draft import DraftResult
    from gpa.eval.curation.validate import ValidationResult
    from gpa.eval.curation.run_eval import RunEvalResult
    from gpa.eval.metrics import EvalResult
    from datetime import datetime, timezone

    candidate = DiscoveryCandidate(url="https://github.com/x/y/issues/1",
                                    source_type="issue", title="t")
    triage = TriageResult(verdict="ambiguous", fingerprint="depth_precision:foo",
                          rejection_reason=None, summary="diagnosis in linked PR")
    draft = DraftResult(
        scenario_id="r1_fake",
        c_source="// SOURCE: https://github.com/x/y/issues/1\nint main(){}",
        md_body=("# R1_FAKE\n## User Report\nb\n## Expected Correct Output\ne\n"
                 "## Actual Broken Output\na\n## Ground Truth\n> q\nd\n"
                 "## Difficulty Rating\n3/5\n## Adversarial Principles\n- p\n"
                 "## How GPA Helps\nh\n## Source\n- **URL**: https://github.com/x/y/issues/1\n"
                 "## Tier\ncore\n## API\nopengl\n## Framework\nnone\n"
                 "## Bug Signature\n```yaml\ntype: framebuffer_dominant_color\n"
                 "spec:\n  color: [1.0, 0.0, 0.0, 1.0]\n  tolerance: 0.1\n```\n"
                 "## Predicted GPA Helpfulness\n- **Verdict**: yes\n- **Reasoning**: x\n"))

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
    from gpa.eval.curation.coverage_log import CoverageLog
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
    from gpa.eval.curation.coverage_log import CoverageLog, CoverageEntry

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
    from gpa.eval.curation.pipeline import CurationPipeline
    from gpa.eval.curation.discover import DiscoveryCandidate
    from gpa.eval.curation.triage import IssueThread, Triage
    from gpa.eval.curation.draft import Draft
    from gpa.eval.curation.validate import Validator
    from gpa.eval.curation.run_eval import RunEvalResult
    from gpa.eval.metrics import EvalResult
    from datetime import datetime, timezone

    # Canned LLM responses: one for triage, one for draft, no failure-mode needed
    fixture = json.loads(Path(
        __file__).parent.joinpath(
        "fixtures/curation/issue_threads/threejs_simple_state_leak.json").read_text())

    from unittest.mock import MagicMock
    from gpa.eval.curation.llm_client import LLMResponse

    triage_resp = (
        '```json\n{"triage_verdict":"in_scope",'
        '"root_cause_fingerprint":"state_leak:material_clone_tex_binding",'
        '"rejection_reason":null,"summary":"state leak"}\n```'
    )

    c_src = ('// SOURCE: ' + fixture["url"] + '\n'
             '#include <GL/gl.h>\nint main(){return 0;}\n')
    md_body = (
        "# R1_MATERIAL_CLONE: Second mesh inherits first mesh's texture\n\n"
        "## User Report\nx\n\n"
        "## Expected Correct Output\nDifferent textures per mesh.\n\n"
        "## Actual Broken Output\nSame texture on both meshes.\n\n"
        "## Ground Truth\n"
        '> "known state-leak caused by the cloned material not re-binding its texture" '
        '(from upstream maintainer)\n\n'
        "## Difficulty Rating\n3/5\n\n"
        "## Adversarial Principles\n- Stale state\n\n"
        "## How GPA Helps\ninspect_drawcall exposes the stale binding.\n\n"
        "## Source\n"
        f"- **URL**: {fixture['url']}\n"
        "- **Type**: issue\n"
        "- **Date**: 2024-01-01\n"
        "- **Commit SHA**: (n/a)\n"
        "- **Attribution**: Reported by @alice\n\n"
        "## Tier\ncore\n\n## API\nopengl\n\n## Framework\nnone\n\n"
        "## Bug Signature\n```yaml\ntype: framebuffer_dominant_color\n"
        "spec:\n  color: [1.0, 0.0, 0.0, 1.0]\n  tolerance: 0.1\n```\n\n"
        "## Predicted GPA Helpfulness\n- **Verdict**: yes\n"
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
    assert "Observed OpenGPA Helpfulness" in md_text
    assert "**Verdict**: yes" in md_text
    summary = (tmp_path / "gaps.md").read_text()
    assert "Scenarios committed: 1" in summary


def test_pipeline_skip_validate_commits_without_running_validator(tmp_path):
    """With skip_validate=True, the pipeline writes scenario files and logs
    the commit, without invoking the validator or run_eval."""
    from unittest.mock import MagicMock
    from gpa.eval.curation.pipeline import CurationPipeline
    from gpa.eval.curation.discover import DiscoveryCandidate
    from gpa.eval.curation.triage import IssueThread, TriageResult
    from gpa.eval.curation.draft import DraftResult

    candidate = DiscoveryCandidate(url="https://github.com/x/y/issues/1",
                                    source_type="issue", title="t")
    triage = TriageResult(verdict="in_scope", fingerprint="state_leak:unique",
                           rejection_reason=None, summary="s")
    draft = DraftResult(scenario_id="r1_test",
                         c_source="// SOURCE: https://github.com/x/y/issues/1\nint main(){}",
                         md_body="# R1_TEST\n## Predicted GPA Helpfulness\n- **Verdict**: yes\n")

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
    from gpa.eval.curation.pipeline import parse_args
    args = parse_args(["--no-validate"])
    assert args.no_validate is True
    args_default = parse_args([])
    assert args_default.no_validate is False


def test_pipeline_resolves_snapshot_sha_from_pr_ref(tmp_path):
    """When draft includes (auto-resolve from PR #NNN), pipeline resolves it
    to the parent SHA from gh api before committing."""
    from unittest.mock import MagicMock, patch
    from gpa.eval.curation.pipeline import CurationPipeline
    from gpa.eval.curation.discover import DiscoveryCandidate
    from gpa.eval.curation.triage import IssueThread, TriageResult
    from gpa.eval.curation.draft import DraftResult
    from gpa.eval.curation.validate import ValidationResult
    from gpa.eval.curation.run_eval import RunEvalResult
    from gpa.eval.metrics import EvalResult
    from datetime import datetime, timezone
    import json as _json

    candidate = DiscoveryCandidate(
        url="https://github.com/mrdoob/three.js/issues/1",
        source_type="issue", title="t",
    )
    triage = TriageResult(verdict="in_scope",
                          fingerprint="state_leak:unique",
                          rejection_reason=None, summary="s")

    md_with_sentinel = (
        "# R1\n"
        "## User Report\nb\n## Expected Correct Output\ne\n## Actual Broken Output\na\n"
        "## Ground Truth\n> q from PR #1234\n"
        "## Difficulty Rating\n3/5\n## Adversarial Principles\n- p\n"
        "## How OpenGPA Helps\nh\n"
        "## Source\n- **URL**: https://github.com/mrdoob/three.js/issues/1\n"
        "## Tier\ncore\n## API\nopengl\n## Framework\nnone\n"
        "## Bug Signature\n```yaml\ntype: framebuffer_dominant_color\n"
        "spec:\n  color: [1.0, 0.0, 0.0, 1.0]\n  tolerance: 0.1\n```\n"
        "## Upstream Snapshot\n"
        "- **Repo**: https://github.com/mrdoob/three.js\n"
        "- **SHA**: (auto-resolve from PR #1234)\n"
        "## Predicted OpenGPA Helpfulness\n- **Verdict**: yes\n- **Reasoning**: x\n"
    )
    draft = DraftResult(
        scenario_id="r1_fake",
        files={
            "main.c": "// SOURCE: https://github.com/mrdoob/three.js/issues/1\nint main(){}",
            "scenario.md": md_with_sentinel,
        },
    )

    discoverer = MagicMock(); discoverer.run.return_value = [candidate]
    fetch = MagicMock(); fetch.return_value = IssueThread(
        url=candidate.url, title="t", body="b")
    triager = MagicMock(); triager.triage.return_value = triage
    drafter = MagicMock(); drafter.draft.return_value = draft
    validator = MagicMock()
    validator.validate.return_value = ValidationResult(
        ok=True, reason="ok", framebuffer_png=b"x",
        metadata={"draw_call_count": 1, "draw_calls": []})
    def _mk(mode, correct, total):
        return EvalResult(scenario_id="r1_fake", mode=mode,
                          correct_diagnosis=correct, correct_fix=correct,
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

    pr_response = _json.dumps({"base": {"sha": "resolved_parent_sha"}})

    p = CurationPipeline(
        discoverer=discoverer, fetch_thread=fetch, triager=triager,
        drafter=drafter, validator=validator, run_eval=run_eval,
        failure_mode_fn=MagicMock(),
        eval_dir=tmp_path / "eval", workdir_root=tmp_path / ".wd",
        coverage_log_path=tmp_path / "log.jsonl",
        summary_path=tmp_path / "gaps.md",
    )

    # Mock subprocess.run for the SHA-resolution call. Don't intercept gh calls
    # inside the fetch helpers — fetch is a MagicMock so they never fire.
    with patch("gpa.eval.curation.pipeline.subprocess.run") as mock_sp:
        mock_sp.return_value = MagicMock(stdout=pr_response, returncode=0)
        p.run_batch()

    # Scenario committed; the md file should have the resolved SHA
    md_path = tmp_path / "eval" / "r1_fake" / "scenario.md"
    assert md_path.exists()
    committed_md = md_path.read_text()
    assert "resolved_parent_sha" in committed_md
    assert "(auto-resolve" not in committed_md


def test_pipeline_retries_draft_on_value_error(tmp_path):
    """When draft raises ValueError, pipeline retries once with error feedback.
    Second success commits normally."""
    candidate = DiscoveryCandidate(
        url="https://github.com/x/y/issues/1", source_type="issue", title="t",
    )
    triage = TriageResult(
        verdict="in_scope", fingerprint="state_leak:unique_key",
        rejection_reason=None, summary="s",
    )

    successful_draft = DraftResult(
        scenario_id="r1_fake",
        files={
            "main.c": "// SOURCE: https://github.com/x/y/issues/1\nint main(){}",
            "scenario.md": _draft_md(),
        },
    )

    drafter = MagicMock()
    # First call raises ValueError; second call succeeds
    drafter.draft.side_effect = [
        ValueError("Ground Truth Diagnosis missing upstream citation"),
        successful_draft,
    ]

    discoverer = MagicMock(); discoverer.run.return_value = [candidate]
    fetch_fn = MagicMock()
    fetch_fn.return_value = IssueThread(url=candidate.url, title="t", body="b")
    triager = MagicMock(); triager.triage.return_value = triage
    validator = MagicMock()
    validator.validate.return_value = ValidationResult(
        ok=True, reason="ok", framebuffer_png=b"x",
        metadata={"draw_call_count": 1, "draw_calls": []},
    )
    run_eval = MagicMock()
    run_eval.run.return_value = RunEvalResult(
        with_gla=_eval_result("with_gla", True, 1000),
        code_only=_eval_result("code_only", False, 4000),
        scorer_ambiguous=False,
    )

    p = CurationPipeline(
        discoverer=discoverer, fetch_thread=fetch_fn, triager=triager,
        drafter=drafter, validator=validator, run_eval=run_eval,
        failure_mode_fn=MagicMock(),
        eval_dir=tmp_path / "eval", workdir_root=tmp_path / ".wd",
        coverage_log_path=tmp_path / "log.jsonl",
        summary_path=tmp_path / "gaps.md",
    )
    p.run_batch()

    # Drafter was called twice (first failed, second succeeded)
    assert drafter.draft.call_count == 2
    # Second call had previous_error kwarg with the first error's message
    second_call_kwargs = drafter.draft.call_args_list[1].kwargs
    assert second_call_kwargs.get("previous_error") is not None
    assert "citation" in second_call_kwargs["previous_error"].lower()
    # Scenario committed
    assert (tmp_path / "eval" / "r1_fake" / "main.c").exists()


def test_pipeline_gives_up_after_second_draft_failure(tmp_path):
    """After TWO ValueError failures, pipeline logs not_reproducible."""
    from gpa.eval.curation.coverage_log import CoverageLog

    candidate = DiscoveryCandidate(
        url="https://github.com/x/y/issues/1", source_type="issue", title="t",
    )
    triage = TriageResult(
        verdict="in_scope", fingerprint="state_leak:unique_key",
        rejection_reason=None, summary="s",
    )

    drafter = MagicMock()
    drafter.draft.side_effect = [
        ValueError("first error"),
        ValueError("second error"),
    ]

    discoverer = MagicMock(); discoverer.run.return_value = [candidate]
    fetch_fn = MagicMock()
    fetch_fn.return_value = IssueThread(url=candidate.url, title="t", body="b")
    triager = MagicMock(); triager.triage.return_value = triage
    validator = MagicMock()
    run_eval = MagicMock()

    p = CurationPipeline(
        discoverer=discoverer, fetch_thread=fetch_fn, triager=triager,
        drafter=drafter, validator=validator, run_eval=run_eval,
        failure_mode_fn=MagicMock(),
        eval_dir=tmp_path / "eval", workdir_root=tmp_path / ".wd",
        coverage_log_path=tmp_path / "log.jsonl",
        summary_path=tmp_path / "gaps.md",
    )
    p.run_batch()

    assert drafter.draft.call_count == 2  # retried once, total 2 attempts
    assert validator.validate.call_count == 0  # never got past draft
    log = CoverageLog(tmp_path / "log.jsonl")
    entries = log.read_all()
    assert len(entries) == 1
    assert entries[0].outcome == "rejected"
    assert entries[0].rejection_reason == "not_reproducible"


def test_check_c_compiles_returns_none_for_valid_c():
    from gpa.eval.curation.pipeline import _check_c_compiles
    files = {
        "main.c": "int main() { return 0; }",
        "scenario.md": "# x",
    }
    assert _check_c_compiles(files, "test") is None


def test_check_c_compiles_returns_error_for_invalid_c():
    from gpa.eval.curation.pipeline import _check_c_compiles
    files = {
        # `#error` directive always fails compilation with that message on stderr
        "main.c": "#error forced compile error\nint main(){return 0;}",
        "scenario.md": "# x",
    }
    err = _check_c_compiles(files, "test")
    assert err is not None
    assert "error" in err.lower() or "expected" in err.lower()


def test_check_c_compiles_skips_when_no_c_files():
    from gpa.eval.curation.pipeline import _check_c_compiles
    files = {"scenario.md": "# snapshot-only scenario"}
    assert _check_c_compiles(files, "test") is None


def test_pipeline_retries_draft_on_compile_error(tmp_path):
    """When gcc can't compile the draft's C source, pipeline retries once
    with the gcc stderr fed back as previous_error."""
    candidate = DiscoveryCandidate(
        url="https://github.com/x/y/issues/1", source_type="issue", title="t",
    )
    triage = TriageResult(
        verdict="in_scope", fingerprint="state_leak:unique_key",
        rejection_reason=None, summary="s",
    )

    # First draft has broken C (always-fail #error directive); second is valid
    first_draft = DraftResult(
        scenario_id="r1_fake",
        files={
            "main.c": "// SOURCE: https://github.com/x/y/issues/1\n"
                      "#error forced compile error\nint main(){return 0;}",
            "scenario.md": _draft_md(),
        },
    )
    second_draft = DraftResult(
        scenario_id="r1_fake",
        files={
            "main.c": "// SOURCE: https://github.com/x/y/issues/1\nint main(){ return 0; }",
            "scenario.md": _draft_md(),
        },
    )
    drafter = MagicMock()
    drafter.draft.side_effect = [first_draft, second_draft]

    discoverer = MagicMock(); discoverer.run.return_value = [candidate]
    fetch_fn = MagicMock()
    fetch_fn.return_value = IssueThread(url=candidate.url, title="t", body="b")
    triager = MagicMock(); triager.triage.return_value = triage
    validator = MagicMock()
    validator.validate.return_value = ValidationResult(
        ok=True, reason="ok", framebuffer_png=b"x",
        metadata={"draw_call_count": 1, "draw_calls": []},
    )
    run_eval = MagicMock()
    run_eval.run.return_value = RunEvalResult(
        with_gla=_eval_result("with_gla", True, 1000),
        code_only=_eval_result("code_only", False, 4000),
        scorer_ambiguous=False,
    )

    p = CurationPipeline(
        discoverer=discoverer, fetch_thread=fetch_fn, triager=triager,
        drafter=drafter, validator=validator, run_eval=run_eval,
        failure_mode_fn=MagicMock(),
        eval_dir=tmp_path / "eval", workdir_root=tmp_path / ".wd",
        coverage_log_path=tmp_path / "log.jsonl",
        summary_path=tmp_path / "gaps.md",
    )
    p.run_batch()

    # Drafter called twice (first produced bad C, second good)
    assert drafter.draft.call_count == 2
    second_kwargs = drafter.draft.call_args_list[1].kwargs
    # The retry fed back the gcc stderr via previous_error
    assert second_kwargs.get("previous_error") is not None
    feedback = second_kwargs["previous_error"].lower()
    assert "gcc" in feedback or "compile" in feedback or "error" in feedback
    # Scenario committed
    assert (tmp_path / "eval" / "r1_fake" / "main.c").exists()


def test_pipeline_gives_up_after_second_c_compile_failure(tmp_path):
    """If both draft attempts produce broken C, pipeline logs not_reproducible."""
    from gpa.eval.curation.coverage_log import CoverageLog

    candidate = DiscoveryCandidate(
        url="https://github.com/x/y/issues/1", source_type="issue", title="t",
    )
    triage = TriageResult(
        verdict="in_scope", fingerprint="state_leak:x",
        rejection_reason=None, summary="s",
    )

    broken = DraftResult(
        scenario_id="r1_fake",
        files={
            "main.c": "// SOURCE: https://github.com/x/y/issues/1\n"
                      "#error forced compile error\nint main(){return 0;}",
            "scenario.md": _draft_md(),
        },
    )
    drafter = MagicMock()
    drafter.draft.side_effect = [broken, broken]  # both bad
    discoverer = MagicMock(); discoverer.run.return_value = [candidate]
    fetch_fn = MagicMock()
    fetch_fn.return_value = IssueThread(url=candidate.url, title="t", body="b")
    triager = MagicMock(); triager.triage.return_value = triage
    validator = MagicMock(); run_eval = MagicMock()

    p = CurationPipeline(
        discoverer=discoverer, fetch_thread=fetch_fn, triager=triager,
        drafter=drafter, validator=validator, run_eval=run_eval,
        failure_mode_fn=MagicMock(),
        eval_dir=tmp_path / "eval", workdir_root=tmp_path / ".wd",
        coverage_log_path=tmp_path / "log.jsonl",
        summary_path=tmp_path / "gaps.md",
    )
    p.run_batch()

    assert drafter.draft.call_count == 2
    assert validator.validate.call_count == 0
    log = CoverageLog(tmp_path / "log.jsonl")
    entries = log.read_all()
    assert len(entries) == 1
    assert entries[0].outcome == "rejected"
    assert entries[0].rejection_reason == "not_reproducible"
