"""Tests for the GPA eval harness: ScenarioLoader, ReportGenerator."""
from __future__ import annotations

import textwrap
from datetime import datetime, timezone
from pathlib import Path

import pytest

from gpa.eval.metrics import EvalResult, ReportGenerator
from gpa.eval.scenario import ScenarioLoader, ScenarioMetadata


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

EVAL_DIR = Path(__file__).parent.parent.parent / "eval"


def _make_result(
    scenario_id: str = "e1_state_leak",
    mode: str = "with_gla",
    solved: bool = True,
    total_tokens: int = 1000,
    input_tokens: int = 800,
    output_tokens: int = 200,
    tool_calls: int = 3,
    num_turns: int = 5,
    time_seconds: float = 2.5,
) -> EvalResult:
    """Build an EvalResult with verdict.solved=solved (R17: replaces
    correct_diagnosis/correct_fix with the verdict-orchestrator field)."""
    return EvalResult(
        scenario_id=scenario_id,
        mode=mode,
        diagnosis_text="The texture binding is missing for Quad B.",
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        total_tokens=total_tokens,
        tool_calls=tool_calls,
        num_turns=num_turns,
        time_seconds=time_seconds,
        model="test-model",
        timestamp=datetime.now(timezone.utc).isoformat(),
        verdict={"solved": solved, "scorer": "test", "confidence": "high"},
    )


# ---------------------------------------------------------------------------
# ScenarioLoader tests
# ---------------------------------------------------------------------------

class TestScenarioLoader:
    def test_load_e1_state_leak(self):
        """ScenarioLoader parses e1_state_leak.md and populates all fields."""
        loader = ScenarioLoader(eval_dir=str(EVAL_DIR))
        scenario = loader.load("e1_state_leak")

        assert scenario.id == "e1_state_leak"
        assert "State Leak" in scenario.title
        assert scenario.difficulty == 1
        # User Report describes the symptom (two quads, both end up red)
        assert "red" in scenario.bug_description.lower()
        # Expected output should mention red and blue
        assert "red" in scenario.expected_output.lower()
        assert "blue" in scenario.expected_output.lower()
        # Actual output — both quads appear red
        assert "red" in scenario.actual_output.lower()
        # Ground Truth carries the diagnosis — must name the missing bind
        # or the texture state machine
        gt = scenario.ground_truth_diagnosis.lower()
        assert "glbindtexture" in gt or "texture" in gt
        # At least one adversarial principle
        assert len(scenario.adversarial_principles) > 0
        # GPA advantage text present
        assert len(scenario.gpa_advantage) > 0
        # Source path now points to the scenario dir's main.c
        assert scenario.source_path.endswith("e1_state_leak/main.c")
        assert scenario.binary_name == "e1_state_leak"

    def test_scenario_metadata_lists_source_files(self):
        loader = ScenarioLoader(eval_dir=str(EVAL_DIR))
        s = loader.load("e1_state_leak")
        assert "main.c" in s.source_files
        assert s.scenario_dir.endswith("e1_state_leak")
        assert s.source_path.endswith("main.c")

    def test_load_e9_scissor(self):
        """ScenarioLoader handles alternative section names (Difficulty, GPA Advantage)."""
        loader = ScenarioLoader(eval_dir=str(EVAL_DIR))
        scenario = loader.load("e9_scissor_not_reset")

        assert scenario.id == "e9_scissor_not_reset"
        assert "Scissor" in scenario.title
        # Difficulty section uses 'Medium' without a /5 rating in e9
        assert scenario.difficulty == 3  # Medium maps to 3
        assert "scissor" in scenario.ground_truth_diagnosis.lower()
        assert len(scenario.adversarial_principles) >= 2
        assert len(scenario.gpa_advantage) > 0

    def test_load_all_returns_synthetic_scenarios(self):
        """load_all() returns the original 10 synthetic (e1-e10) scenarios
        plus any later e-prefixed additions (e.g. the e11-e110 batch).
        May also include real-world (r-prefixed) scenarios curated from
        upstream issues."""
        loader = ScenarioLoader(eval_dir=str(EVAL_DIR))
        scenarios = loader.load_all()
        ids = [s.id for s in scenarios]
        assert len(scenarios) >= 10
        e_ids = [i for i in ids if i.startswith("e")]
        assert len(e_ids) >= 10
        assert "e1_state_leak" in ids
        assert "e10_compensating_vp" in ids

    def test_load_nonexistent_raises(self):
        """Loading an unknown scenario ID raises FileNotFoundError."""
        loader = ScenarioLoader(eval_dir=str(EVAL_DIR))
        with pytest.raises(FileNotFoundError):
            loader.load("e99_does_not_exist")


# R17: DiagnosisScorer tests deleted along with the class. The
# verdict orchestrator (file_level → prose → judge) is the only
# scoring path now. See `tests/unit/python/test_scorer*.py` for the
# replacement coverage.


# ---------------------------------------------------------------------------
# ReportGenerator tests
# ---------------------------------------------------------------------------

class TestReportGenerator:
    def _two_mode_results(self) -> list[EvalResult]:
        return [
            _make_result("e1_state_leak", "with_gla", solved=True,
                         total_tokens=500, input_tokens=400, output_tokens=100,
                         tool_calls=3, num_turns=4, time_seconds=1.2),
            _make_result("e1_state_leak", "code_only", solved=False,
                         total_tokens=1500, input_tokens=1200, output_tokens=300,
                         tool_calls=0, num_turns=6, time_seconds=3.0),
        ]

    def test_generate_markdown_contains_header(self):
        gen = ReportGenerator()
        md = gen.generate_markdown(self._two_mode_results())
        assert "# OpenGPA Evaluation Report" in md

    def test_generate_markdown_contains_scenario_id(self):
        gen = ReportGenerator()
        md = gen.generate_markdown(self._two_mode_results())
        assert "e1_state_leak" in md

    def test_generate_markdown_contains_modes(self):
        gen = ReportGenerator()
        md = gen.generate_markdown(self._two_mode_results())
        assert "with_gla" in md
        assert "code_only" in md

    def test_generate_markdown_shows_token_reduction(self):
        gen = ReportGenerator()
        md = gen.generate_markdown(self._two_mode_results())
        # Token reduction from 1500 -> 500 is 66.7 %
        assert "Token reduction" in md
        assert "66.7%" in md

    def test_generate_summary_structure(self):
        gen = ReportGenerator()
        summary = gen.generate_summary(self._two_mode_results())
        assert "scenarios" in summary
        assert "overall" in summary
        assert "token_reduction_fraction" in summary
        assert "e1_state_leak" in summary["scenarios"]
        assert "with_gla" in summary["scenarios"]["e1_state_leak"]
        assert "code_only" in summary["scenarios"]["e1_state_leak"]

    def test_generate_summary_token_reduction(self):
        gen = ReportGenerator()
        summary = gen.generate_summary(self._two_mode_results())
        reduction = summary["token_reduction_fraction"]
        assert reduction is not None
        # 1500 -> 500 = 2/3 reduction
        assert abs(reduction - 2 / 3) < 0.01

    def test_empty_results_produce_valid_markdown(self):
        gen = ReportGenerator()
        md = gen.generate_markdown([])
        assert "# OpenGPA Evaluation Report" in md
        assert isinstance(md, str)


# ---------------------------------------------------------------------------
# EvalResult optional fields tests
# ---------------------------------------------------------------------------

def test_eval_result_has_observed_helps_field():
    r = _make_result()
    r.observed_helps = "yes"
    r.failure_mode = None
    d = r.to_dict()
    r2 = EvalResult.from_dict(d)
    assert r2.observed_helps == "yes"
    assert r2.failure_mode is None
