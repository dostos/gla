"""Tests for `is_browser_tier_scenario` — used by the harness to warn
when with_gla mode is requested for a scenario whose rendering tier
the native LD_PRELOAD shim cannot intercept."""
from __future__ import annotations

from gpa.eval.scenario import ScenarioMetadata, is_browser_tier_scenario


def _make_scenario(scenario_dir: str | None) -> ScenarioMetadata:
    return ScenarioMetadata(
        id="dummy",
        title="t",
        bug_description="",
        expected_output="",
        actual_output="",
        ground_truth_diagnosis="",
        ground_truth_fix="",
        difficulty=1,
        adversarial_principles=[],
        gpa_advantage="",
        source_path="",
        binary_name="",
        scenario_dir=scenario_dir,
    )


def test_web_map_is_browser_tier():
    s = _make_scenario("/repo/tests/eval/web-map/cesium/r5211bd_x")
    assert is_browser_tier_scenario(s) is True


def test_web_3d_is_browser_tier():
    s = _make_scenario("/repo/tests/eval/web-3d/three.js/some_slug")
    assert is_browser_tier_scenario(s) is True


def test_web_2d_is_browser_tier():
    s = _make_scenario("/repo/tests/eval/web-2d/p5.js/another_slug")
    assert is_browser_tier_scenario(s) is True


def test_graphics_lib_is_browser_tier():
    s = _make_scenario("/repo/tests/eval/graphics-lib/webgl/lib_slug")
    assert is_browser_tier_scenario(s) is True


def test_native_engine_is_not_browser_tier():
    s = _make_scenario("/repo/tests/eval/native-engine/godot/rfc2ac5_x")
    assert is_browser_tier_scenario(s) is False


def test_synthetic_is_not_browser_tier():
    s = _make_scenario("/repo/tests/eval/synthetic/state-leak/e1_state_leak")
    assert is_browser_tier_scenario(s) is False


def test_quarantine_subtree_preserves_category():
    """Quarantined scenarios still need the right tier classification —
    they live under tests/eval-quarantine/<original-taxonomy-path>/."""
    # The helper only acts on `tests/eval/...` so a quarantined dir is
    # outside its scope and returns False (safe default).
    s = _make_scenario("/repo/tests/eval-quarantine/web-map/cesium/x")
    assert is_browser_tier_scenario(s) is False


def test_no_scenario_dir_returns_false():
    s = _make_scenario(None)
    assert is_browser_tier_scenario(s) is False


def test_unrecognized_path_returns_false():
    s = _make_scenario("/some/random/path/without/eval/segment")
    assert is_browser_tier_scenario(s) is False


def test_relative_path_with_eval_segment():
    """Relative paths like `tests/eval/web-map/...` should still detect."""
    s = _make_scenario("tests/eval/web-map/cesium/r5211bd_x")
    assert is_browser_tier_scenario(s) is True
