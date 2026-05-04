"""Harness wires `score_run` into the verdict field of EvalResult.

End-to-end tests on the bare harness that confirm:
- a clear file-level solve produces verdict.scorer == "file_level"
- a prose-only diagnosis produces verdict.scorer == "prose"
- a gave-up tail vetoes any positive verdict
- legacy scenarios without fix.files get scorer == "no_signal"
"""
from __future__ import annotations

from unittest.mock import MagicMock

from gpa.eval.harness import EvalHarness
from gpa.eval.scenario import FixMetadata, ScenarioMetadata


_FIX_FILES = ["src/render/draw_fill.ts", "src/render/painter.ts"]


def _make_scenario(*, fix_files=None) -> ScenarioMetadata:
    base = dict(
        id="test_id",
        title="T",
        bug_description="b",
        expected_output="e",
        actual_output="a",
        ground_truth_diagnosis="gt",
        ground_truth_fix="fix",
        difficulty=3,
        adversarial_principles=[],
        gpa_advantage="",
        source_path="/tmp/x.c",
        binary_name="test_id",
    )
    if fix_files is not None:
        base["fix"] = FixMetadata(
            fix_pr_url="https://github.com/o/r/pull/1",
            fix_sha="abc",
            bug_class="framework-internal",
            files=list(fix_files),
        )
    return ScenarioMetadata(**base)


def _bare_harness() -> EvalHarness:
    h = EvalHarness.__new__(EvalHarness)
    h.results = []
    h._model = "test"
    h._snapshot_fetcher = MagicMock()
    h.runner = MagicMock()
    h.runner.read_source.return_value = "// hi"
    h.loader = MagicMock()
    h._scorer = MagicMock()
    h._scorer.score.return_value = (False, False)
    return h


def _stub_agent(diagnosis: str):
    def fn(scen, mode, tools):
        return (diagnosis, 0, 0, 0, 0, 0.1)
    return fn


def test_verdict_file_level_when_json_solves():
    h = _bare_harness()
    s = _make_scenario(fix_files=_FIX_FILES)
    h.loader.load.return_value = s
    json_tail = (
        '{"proposed_patches":'
        '[{"file":"src/render/draw_fill.ts"},'
        '{"file":"src/render/painter.ts"}]}'
    )
    diagnosis = f"reasoning here\n```json\n{json_tail}\n```"
    res = h.run_scenario(s.id, "code_only", _stub_agent(diagnosis))
    assert res.verdict is not None
    assert res.verdict["scorer"] == "file_level"
    assert res.verdict["solved"] is True
    assert res.verdict["confidence"] == "high"


def test_verdict_prose_when_no_json_but_files_cited():
    h = _bare_harness()
    s = _make_scenario(fix_files=_FIX_FILES)
    h.loader.load.return_value = s
    diagnosis = (
        "After investigating: the bug is in `src/render/draw_fill.ts` "
        "and `src/render/painter.ts`. FIX: at line 42."
    )
    res = h.run_scenario(s.id, "code_only", _stub_agent(diagnosis))
    assert res.verdict is not None
    assert res.verdict["scorer"] == "prose"
    assert res.verdict["solved"] is True
    assert res.verdict["confidence"] == "medium"


def test_verdict_gave_up_vetoes_solve():
    h = _bare_harness()
    s = _make_scenario(fix_files=_FIX_FILES)
    h.loader.load.return_value = s
    diagnosis = (
        "I cannot provide a specific diagnosis without source access. "
        "Speculatively: maybe `src/render/draw_fill.ts`."
    )
    res = h.run_scenario(s.id, "code_only", _stub_agent(diagnosis))
    assert res.verdict is not None
    assert res.verdict["scorer"] == "gave_up"
    assert res.verdict["solved"] is False
    assert res.verdict["gave_up"] is True


def test_verdict_no_signal_for_legacy_scenarios_without_fix_files():
    """Legacy scenarios with no fix.files → verdict.scorer = no_signal,
    but the result still records (the dict is populated)."""
    h = _bare_harness()
    s = _make_scenario(fix_files=None)
    h.loader.load.return_value = s
    res = h.run_scenario(s.id, "code_only", _stub_agent("anything goes"))
    assert res.verdict is not None
    assert res.verdict["scorer"] == "no_signal"
    assert res.verdict["solved"] is False


def test_verdict_low_confidence_review_when_one_of_three_files_cited():
    """Maplibre 3d_terrain pattern: agent cited 1 of 3 gt files —
    needs_review=True, not a hard ✗."""
    h = _bare_harness()
    s = _make_scenario(fix_files=[
        "src/render/draw_fill.ts",
        "src/render/draw_line.ts",
        "src/render/painter.ts",
    ])
    h.loader.load.return_value = s
    diagnosis = (
        "Sharp diagnosis: the render-pass guard in `src/render/draw_fill.ts` "
        "is missing a stencil-config update."
    )
    res = h.run_scenario(s.id, "code_only", _stub_agent(diagnosis))
    assert res.verdict is not None
    assert res.verdict["scorer"] == "prose"
    assert res.verdict["solved"] is False
    assert res.verdict["needs_review"] is True
    assert res.verdict["confidence"] == "low"


# ---------------------------------------------------------------------------
# Judge tier (opt-in via llm_judge_client) upgrades needs_review
# ---------------------------------------------------------------------------


def test_judge_tier_upgrades_needs_review_to_solved(tmp_path, monkeypatch):
    """When llm_judge_client + snapshot_root are wired, a needs_review
    prose verdict gets upgraded via semantic match."""
    from types import SimpleNamespace

    h = _bare_harness()

    class _StubJudgeClient:
        def __init__(self):
            self.calls = 0

        def complete(self, *, system, messages):
            self.calls += 1
            return SimpleNamespace(text="full")

    h._llm_judge_client = _StubJudgeClient()
    h._judge_cache_dir = tmp_path / "cache"
    # Provide a fake snapshot root via _ensure_snapshot
    snap = tmp_path / "snap"
    snap.mkdir()
    h._ensure_snapshot = MagicMock(return_value=snap)
    # Make fetch_pr_diff_summary return a non-empty payload
    monkeypatch.setattr(
        "gpa.eval.judge.fetch_pr_diff_summary",
        lambda fix_sha, snapshot_root, **_: "stat output",
    )

    s = _make_scenario(fix_files=[
        "src/render/draw_fill.ts",
        "src/render/draw_line.ts",
        "src/render/painter.ts",
    ])
    # Set upstream fields so _ensure_snapshot is reachable
    s.upstream_snapshot_repo = "https://github.com/o/r"
    s.upstream_snapshot_sha = "abc1234"
    h.loader.load.return_value = s
    diagnosis = (
        "Sharp diagnosis: the render-pass guard in `src/render/draw_fill.ts` "
        "is missing a stencil-config update."
    )
    res = h.run_scenario(s.id, "code_only", _stub_agent(diagnosis))
    assert res.verdict is not None
    assert res.verdict["scorer"] == "judge"
    assert res.verdict["solved"] is True
    assert res.verdict["judge_verdict"] == "full"
