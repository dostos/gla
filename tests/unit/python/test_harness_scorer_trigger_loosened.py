"""File-level scorer should fire whenever scenario.fix.files is populated,
not only when bug_class == 'framework-internal'. Round 12 surfaced this
as the gap that left consumer-misuse / user-config scenarios scoreless
even when their fix metadata is real and complete."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from gpa.eval.harness import EvalHarness
from gpa.eval.scenario import FixMetadata, ScenarioMetadata


_FIX_FILES = ["src/render/draw_fill.ts"]


def _make_scenario(*, bug_class: str, fix_files: list = None) -> ScenarioMetadata:
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
            bug_class=bug_class,
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


def test_scorer_fires_for_consumer_misuse_with_fix_files_and_json(monkeypatch):
    h = _bare_harness()
    s = _make_scenario(bug_class="consumer-misuse", fix_files=_FIX_FILES)
    h.loader.load.return_value = s
    json_tail = '{"proposed_patches":[{"file":"src/render/draw_fill.ts"}]}'
    diagnosis = f"reasoning here\n```json\n{json_tail}\n```"
    res = h.run_scenario(s.id, "code_only", _stub_agent(diagnosis))
    assert res.file_score is not None  # scoring fired
    assert res.maintainer_solved is True
    assert "src/render/draw_fill.ts" in (res.file_hits or [])


def test_scorer_skips_consumer_misuse_when_no_json_tail(monkeypatch):
    """Advisor-format prompts don't ask for JSON. When the agent's diagnosis
    has no JSON tail, we should NOT pollute file_score with a 0.0 value;
    leave fields None so a future prose scorer / aggregation handles it."""
    h = _bare_harness()
    s = _make_scenario(bug_class="consumer-misuse", fix_files=_FIX_FILES)
    h.loader.load.return_value = s
    diagnosis = "DIAGNOSIS: bug somewhere\nFIX: change something"
    res = h.run_scenario(s.id, "code_only", _stub_agent(diagnosis))
    assert res.file_score is None
    assert res.maintainer_solved is None
    assert res.parsed_json is False


def test_scorer_still_fires_for_framework_internal_without_json(monkeypatch):
    """Existing behavior preserved: framework-internal scenarios are
    expected to emit JSON; missing JSON is itself a 'failed' signal,
    so scoring fires and records solved=False."""
    h = _bare_harness()
    s = _make_scenario(bug_class="framework-internal", fix_files=_FIX_FILES)
    h.loader.load.return_value = s
    diagnosis = "no JSON here"
    res = h.run_scenario(s.id, "code_only", _stub_agent(diagnosis))
    # File-level scoring fired even though no JSON
    assert res.file_score is not None
    assert res.maintainer_solved is False
    assert res.parsed_json is False


def test_scorer_skipped_when_no_fix_files():
    """Legacy scenarios without fix.files (or with fix=None) shouldn't
    trigger file-level scoring at all."""
    h = _bare_harness()
    s = _make_scenario(bug_class="legacy", fix_files=None)
    h.loader.load.return_value = s
    res = h.run_scenario(s.id, "code_only", _stub_agent("anything"))
    assert res.file_score is None
    assert res.maintainer_solved is None


def test_scorer_skipped_when_fix_files_empty():
    """Empty file list — nothing to score against."""
    h = _bare_harness()
    s = _make_scenario(bug_class="framework-internal", fix_files=[])
    h.loader.load.return_value = s
    res = h.run_scenario(s.id, "code_only", _stub_agent("anything"))
    assert res.file_score is None
