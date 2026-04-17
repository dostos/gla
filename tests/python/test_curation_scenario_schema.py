"""Tests for extended ScenarioMetadata fields (real-world curation pipeline)."""
import textwrap
from pathlib import Path
from gla.eval.scenario import ScenarioMetadata, ScenarioLoader


def test_parser_extracts_new_sections(tmp_path):
    md = textwrap.dedent('''
        # R1: Test Scenario

        ## Bug
        Something is wrong.

        ## Expected Correct Output
        Red quad.

        ## Actual Broken Output
        Blue quad.

        ## Ground Truth Diagnosis
        The texture is wrong.

        ## Difficulty Rating
        3/5

        ## Adversarial Principles
        - Stale state

        ## How GLA Helps
        inspect_drawcall exposes the binding.

        ## Source
        - **URL**: https://github.com/mrdoob/three.js/issues/12345
        - **Type**: issue
        - **Date**: 2024-03-17
        - **Commit SHA**: (n/a)
        - **Attribution**: Reported by @alice

        ## Tier
        core

        ## API
        opengl

        ## Framework
        none

        ## Bug Signature
        ```yaml
        type: color_histogram_in_region
        spec:
          region: [0.0, 0.0, 1.0, 1.0]
          dominant_color: [1.0, 0.0, 0.0, 1.0]
          tolerance: 0.1
        ```

        ## Predicted GLA Helpfulness
        - **Verdict**: yes
        - **Reasoning**: The binding is visible via inspect_drawcall.
    ''').strip()

    (tmp_path / "r1_test.md").write_text(md)
    (tmp_path / "r1_test.c").write_text("int main(){}")

    loader = ScenarioLoader(eval_dir=str(tmp_path))
    s = loader.load("r1_test")

    assert s.source_url == "https://github.com/mrdoob/three.js/issues/12345"
    assert s.source_type == "issue"
    assert s.source_date == "2024-03-17"
    assert s.source_attribution == "Reported by @alice"
    assert s.tier == "core"
    assert s.api == "opengl"
    assert s.framework == "none"
    assert s.bug_signature["type"] == "color_histogram_in_region"
    assert s.bug_signature["spec"]["dominant_color"] == [1.0, 0.0, 0.0, 1.0]
    assert s.predicted_helps == "yes"
    assert s.predicted_helps_reasoning.startswith("The binding")


def test_load_all_includes_real_world_scenarios(tmp_path):
    """load_all discovers both e-prefixed and r-prefixed scenarios via glob."""
    for prefix in ("e1_test", "r1_test"):
        (tmp_path / f"{prefix}.md").write_text(
            f"# {prefix}\n## Bug\nbug\n## Ground Truth Diagnosis\ngt"
        )
        (tmp_path / f"{prefix}.c").write_text("int main(){}")

    loader = ScenarioLoader(eval_dir=str(tmp_path))
    ids = [s.id for s in loader.load_all()]
    assert "e1_test" in ids
    assert "r1_test" in ids


def test_parser_backward_compatible_with_e1():
    """Existing E1-E10 scenarios still parse (new fields default to None)."""
    eval_dir = Path(__file__).parent.parent / "eval"
    loader = ScenarioLoader(eval_dir=str(eval_dir))
    s = loader.load("e1_state_leak")
    assert s.id == "e1_state_leak"
    assert s.source_url is None
    assert s.tier is None


def test_scenario_metadata_has_new_fields():
    s = ScenarioMetadata(
        id="r1_test",
        title="Test",
        bug_description="bug",
        expected_output="e",
        actual_output="a",
        ground_truth_diagnosis="gt",
        ground_truth_fix="fix",
        difficulty=3,
        adversarial_principles=[],
        gla_advantage="",
        source_path="/tmp/x.c",
        binary_name="r1_test",
        # New fields — all optional
        source_url="https://github.com/x/y/issues/1",
        source_type="issue",
        source_date="2024-03-17",
        source_commit_sha=None,
        source_attribution="Reported by @u",
        tier="core",
        api="opengl",
        framework="none",
        bug_signature={"type": "color_histogram_in_region",
                       "spec": {"region": [0, 0, 1, 1],
                                "dominant_color": [1, 0, 0, 1],
                                "tolerance": 0.1}},
        predicted_helps="yes",
        predicted_helps_reasoning="GPU state exposes the uniform",
        observed_helps=None,
        observed_helps_evidence=None,
        failure_mode=None,
        failure_mode_details=None,
    )
    assert s.source_url == "https://github.com/x/y/issues/1"
    assert s.tier == "core"
    assert s.bug_signature["type"] == "color_histogram_in_region"
    assert s.observed_helps is None
