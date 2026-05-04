"""When `runner.run_with_capture` fails (e.g. no Bazel target, build error,
shim missing), the harness's exposed `tools["run_with_capture"]` should
return None rather than propagating, so agents can degrade gracefully."""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from gpa.eval.harness import EvalHarness
from gpa.eval.scenario import ScenarioMetadata


def _make_scenario(**overrides) -> ScenarioMetadata:
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
    base.update(overrides)
    return ScenarioMetadata(**base)


def _bare_harness() -> EvalHarness:
    h = EvalHarness.__new__(EvalHarness)
    h.results = []
    h._model = "test"
    h._snapshot_fetcher = MagicMock()
    h.runner = MagicMock()
    h.loader = MagicMock()
    h._scorer = MagicMock()
    return h


def test_run_with_capture_returns_none_when_runner_raises_runtime_error():
    h = _bare_harness()
    h.runner.run_with_capture.side_effect = RuntimeError("Bazel build failed")
    tools = h._build_tools(_make_scenario(), mode="with_gla")
    assert tools["run_with_capture"]() is None


def test_run_with_capture_returns_none_when_runner_raises_file_not_found():
    h = _bare_harness()
    h.runner.run_with_capture.side_effect = FileNotFoundError("missing binary")
    tools = h._build_tools(_make_scenario(), mode="with_gla")
    assert tools["run_with_capture"]() is None


def test_run_with_capture_propagates_int_when_runner_succeeds():
    h = _bare_harness()
    h.runner.run_with_capture.return_value = 7
    tools = h._build_tools(_make_scenario(), mode="with_gla")
    assert tools["run_with_capture"]() == 7


def test_run_with_capture_absent_from_code_only_tools():
    h = _bare_harness()
    tools = h._build_tools(_make_scenario(), mode="code_only")
    assert "run_with_capture" not in tools
