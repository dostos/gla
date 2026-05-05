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


# ---------------------------------------------------------------------------
# R14 P3: browser-tier with_gla scenarios degrade to code_only prompt
# (R13 surfaced with_gla underperforming code_only on web-map by 3 solves;
# the GPA tool block was dead weight since the native shim doesn't see
# browser WebGL.)
# ---------------------------------------------------------------------------


def test_browser_tier_with_gla_sets_effective_mode_to_code_only(tmp_path, monkeypatch):
    """The harness should set tools['effective_mode']='code_only' for a
    browser-tier scenario in with_gla mode."""
    import gpa.eval.scenario as scenario_mod
    from gpa.eval.harness import EvalHarness

    h = EvalHarness()
    # Stub a scenario with a browser-tier scenario_dir
    scenario = _make_browser_scenario(tmp_path)
    tools = h._build_tools(scenario, mode="with_gla")
    assert tools["effective_mode"] == "code_only"


def test_native_with_gla_keeps_effective_mode_with_gla(tmp_path):
    """Native engine scenarios should NOT downgrade — effective_mode stays with_gla."""
    from gpa.eval.harness import EvalHarness

    h = EvalHarness()
    scenario = _make_native_scenario(tmp_path)
    tools = h._build_tools(scenario, mode="with_gla")
    assert tools["effective_mode"] == "with_gla"


def test_browser_tier_with_gla_drops_gpa_only_block_from_prompt(tmp_path):
    """The system_prompt for a browser-tier with_gla scenario should be
    rendered in code_only mode — i.e. should NOT contain the WITH_GPA_ONLY-
    gated content (e.g. 'gpa report --frame latest --json')."""
    from gpa.eval.harness import EvalHarness

    h = EvalHarness()
    scenario = _make_browser_scenario(tmp_path)
    tools = h._build_tools(scenario, mode="with_gla")
    prompt = tools.get("system_prompt") or ""
    # Sanity: the prompt is non-empty
    assert prompt.strip()
    # The WITH_GPA_ONLY block contains 'gpa report --frame latest';
    # it must not appear when effective_mode is code_only.
    assert "gpa report --frame latest" not in prompt


def test_browser_tier_with_gla_skips_run_with_capture(tmp_path):
    """run_with_capture for a browser-tier scenario should return None
    immediately (not even attempt a Bazel build)."""
    from gpa.eval.harness import EvalHarness

    h = EvalHarness()
    scenario = _make_browser_scenario(tmp_path)
    tools = h._build_tools(scenario, mode="with_gla")
    fn = tools.get("run_with_capture")
    assert callable(fn)
    # Call it; should return None without attempting capture
    assert fn() is None


def _make_browser_scenario(tmp_path):
    """A minimal scenario with a web-map scenario_dir to trigger the
    browser-tier check."""
    from gpa.eval.scenario import ScenarioMetadata, FixMetadata

    sd = tmp_path / "tests" / "eval" / "web-map" / "cesium" / "test-slug"
    sd.mkdir(parents=True, exist_ok=True)
    (sd / "scenario.md").write_text("## User Report\n\nA bug.\n")
    return ScenarioMetadata(
        id="test-slug", title="t", bug_description="bug",
        expected_output="", actual_output="",
        ground_truth_diagnosis="", ground_truth_fix="",
        difficulty=2, adversarial_principles=[],
        gpa_advantage="", source_path="",
        binary_name="", scenario_dir=str(sd),
        fix=FixMetadata(
            fix_pr_url="https://github.com/o/r/pull/1",
            fix_sha="abc123", fix_parent_sha="dead",
            bug_class="framework-internal", files=["src/foo.ts"],
        ),
    )


def _make_native_scenario(tmp_path):
    """A minimal scenario with a native-engine scenario_dir (NOT browser tier)."""
    from gpa.eval.scenario import ScenarioMetadata, FixMetadata

    sd = tmp_path / "tests" / "eval" / "native-engine" / "godot" / "test-slug"
    sd.mkdir(parents=True, exist_ok=True)
    (sd / "scenario.md").write_text("## User Report\n\nA bug.\n")
    return ScenarioMetadata(
        id="test-slug", title="t", bug_description="bug",
        expected_output="", actual_output="",
        ground_truth_diagnosis="", ground_truth_fix="",
        difficulty=2, adversarial_principles=[],
        gpa_advantage="", source_path="",
        binary_name="", scenario_dir=str(sd),
        fix=FixMetadata(
            fix_pr_url="https://github.com/o/r/pull/1",
            fix_sha="abc123", fix_parent_sha="dead",
            bug_class="framework-internal", files=["src/foo.cpp"],
        ),
    )


# ---------------------------------------------------------------------------
# R16 P0: source-less scenarios skip with_gla mode entirely (deletion).
# Pre-R16 the harness ran both modes for every scenario, but for mined-
# without-source scenarios the comparison is theater — GPA_FRAME_ID is
# never set so `gpa frames overview` returns empty. Net result: 2x cohort
# cost for zero signal. R16 deletes the with_gla run for source-less.
# ---------------------------------------------------------------------------


def test_run_all_skips_with_gla_for_source_less_scenarios(tmp_path, monkeypatch):
    """When a scenario has no source_path, run_all should skip its
    with_gla run entirely — the comparison is meaningless."""
    from gpa.eval.harness import EvalHarness
    from gpa.eval.scenario import ScenarioMetadata, FixMetadata

    h = EvalHarness()

    # Stub: source-less mined scenario
    mined = ScenarioMetadata(
        id="mined-slug", title="t", bug_description="bug",
        expected_output="", actual_output="",
        ground_truth_diagnosis="", ground_truth_fix="",
        difficulty=2, adversarial_principles=[],
        gpa_advantage="", source_path="",  # the key — source-less
        binary_name="", scenario_dir=str(tmp_path / "scn"),
        fix=FixMetadata(
            fix_pr_url="https://github.com/o/r/pull/1",
            fix_sha="abc", fix_parent_sha="dead",
            bug_class="framework-internal", files=["src/foo.cpp"],
        ),
    )
    # Stub: source-having synthetic scenario
    src_path = tmp_path / "main.c"
    src_path.write_text("int main(void){return 0;}\n")
    synth = ScenarioMetadata(
        id="synth-slug", title="t", bug_description="bug",
        expected_output="", actual_output="",
        ground_truth_diagnosis="", ground_truth_fix="",
        difficulty=2, adversarial_principles=[],
        gpa_advantage="", source_path=str(src_path),
        binary_name="synth-slug", scenario_dir=str(tmp_path),
        fix=None,  # legacy
    )

    # Wire the loader to return our two scenarios
    monkeypatch.setattr(h.loader, "load",
                        lambda sid: {"mined-slug": mined, "synth-slug": synth}[sid])

    # Track which (sid, mode) pairs run_scenario actually receives
    invocations = []
    def fake_run_scenario(sid, mode, agent_fn):
        invocations.append((sid, mode))
        # Return a minimal result so the loop continues
        from gpa.eval.metrics import EvalResult
        return EvalResult(scenario_id=sid, mode=mode,
                          diagnosis_text="", input_tokens=0, output_tokens=0,
                          total_tokens=0, tool_calls=0, num_turns=0,
                          time_seconds=0.0, model="x",
                          timestamp="2026-05-05T00:00:00")
    monkeypatch.setattr(h, "run_scenario", fake_run_scenario)

    h.run_all(agent_fn=lambda *a, **kw: None,
              scenarios=["mined-slug", "synth-slug"],
              modes=["with_gla", "code_only"])

    # mined-slug: only code_only should run (with_gla skipped)
    assert ("mined-slug", "with_gla") not in invocations
    assert ("mined-slug", "code_only") in invocations
    # synth-slug: BOTH modes run (real comparison)
    assert ("synth-slug", "with_gla") in invocations
    assert ("synth-slug", "code_only") in invocations
