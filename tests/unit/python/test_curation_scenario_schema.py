"""Tests for extended ScenarioMetadata fields (real-world curation pipeline)."""
import textwrap
from pathlib import Path
from gla.eval.scenario import ScenarioMetadata, ScenarioLoader, _parse_upstream_snapshot


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

    (tmp_path / "r1_test").mkdir()
    (tmp_path / "r1_test" / "scenario.md").write_text(md)
    (tmp_path / "r1_test" / "main.c").write_text("int main(){}")

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
        (tmp_path / prefix).mkdir()
        (tmp_path / prefix / "scenario.md").write_text(
            f"# {prefix}\n## Bug\nbug\n## Ground Truth Diagnosis\ngt"
        )
        (tmp_path / prefix / "main.c").write_text("int main(){}")

    loader = ScenarioLoader(eval_dir=str(tmp_path))
    ids = [s.id for s in loader.load_all()]
    assert "e1_test" in ids
    assert "r1_test" in ids


def test_parser_backward_compatible_with_e1():
    """Existing E1-E10 scenarios still parse (new fields default to None)."""
    eval_dir = Path(__file__).parent.parent.parent / "eval"
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


# ---------------------------------------------------------------------------
# G1: Upstream snapshot schema tests
# ---------------------------------------------------------------------------

def test_scenario_metadata_upstream_snapshot_fields_default():
    s = ScenarioMetadata(
        id="x", title="x", bug_description="x", expected_output="x",
        actual_output="x", ground_truth_diagnosis="x", ground_truth_fix="x",
        difficulty=1, adversarial_principles=[], gla_advantage="",
        source_path="", binary_name="x",
    )
    assert s.upstream_snapshot_repo is None
    assert s.upstream_snapshot_sha is None
    assert s.upstream_snapshot_relevant_files == []


def test_parser_extracts_upstream_snapshot_section(tmp_path):
    md = textwrap.dedent("""
        # R1: Godot shader bug

        ## Bug
        Shader miscompiles.

        ## Expected Correct Output
        X.

        ## Actual Broken Output
        Y.

        ## Ground Truth Diagnosis
        See PR #12345.

        ## Difficulty Rating
        3/5

        ## Adversarial Principles
        - Distant cause

        ## How OpenGPA Helps
        ...

        ## Tier
        snapshot

        ## API
        opengl

        ## Framework
        godot

        ## Upstream Snapshot
        - **Repo**: https://github.com/godotengine/godot
        - **SHA**: abc1234def
        - **Relevant Files**:
          - drivers/gles3/shaders/scene.glsl
          - servers/rendering/renderer_rd/shader_compiler.cpp
    """).strip()

    (tmp_path / "r1_godot").mkdir()
    (tmp_path / "r1_godot" / "scenario.md").write_text(md)
    # No main.c — snapshot-only scenario

    loader = ScenarioLoader(eval_dir=str(tmp_path))
    s = loader.load("r1_godot")
    assert s.upstream_snapshot_repo == "https://github.com/godotengine/godot"
    assert s.upstream_snapshot_sha == "abc1234def"
    assert "drivers/gles3/shaders/scene.glsl" in s.upstream_snapshot_relevant_files
    assert "servers/rendering/renderer_rd/shader_compiler.cpp" in s.upstream_snapshot_relevant_files
    assert s.tier == "snapshot"


def test_scenario_without_upstream_snapshot_section_has_nones(tmp_path):
    md = textwrap.dedent("""
        # R2: Core

        ## Bug
        B.
        ## Ground Truth Diagnosis
        > q
    """).strip()
    (tmp_path / "r2_core").mkdir()
    (tmp_path / "r2_core" / "scenario.md").write_text(md)
    (tmp_path / "r2_core" / "main.c").write_text("int main(){}")

    loader = ScenarioLoader(eval_dir=str(tmp_path))
    s = loader.load("r2_core")
    assert s.upstream_snapshot_repo is None
    assert s.upstream_snapshot_sha is None
    assert s.upstream_snapshot_relevant_files == []


def test_snapshot_tier_without_main_c_still_loads(tmp_path):
    """tier: snapshot scenarios may omit main.c; source_path falls back to empty."""
    md = textwrap.dedent("""
        # R3: Snapshot-only

        ## Bug
        B.

        ## Ground Truth Diagnosis
        > q from PR #5

        ## Tier
        snapshot

        ## Upstream Snapshot
        - **Repo**: https://github.com/o/r
        - **SHA**: deadbeef
    """).strip()
    (tmp_path / "r3_snap").mkdir()
    (tmp_path / "r3_snap" / "scenario.md").write_text(md)
    # No main.c

    loader = ScenarioLoader(eval_dir=str(tmp_path))
    s = loader.load("r3_snap")
    assert s.tier == "snapshot"
    assert s.source_path == "" or s.source_path.endswith("/r3_snap")
    assert s.source_files == []  # no C source files
    assert s.upstream_snapshot_repo == "https://github.com/o/r"
    assert s.upstream_snapshot_sha == "deadbeef"


def test_relevant_files_nested_bullet_list(tmp_path):
    """Relevant files appear as an indented bullet list under the key."""
    md_nested = textwrap.dedent("""
        # R4

        ## Bug
        b
        ## Ground Truth Diagnosis
        > q

        ## Upstream Snapshot
        - **Repo**: https://github.com/o/r
        - **SHA**: abc
        - **Relevant Files**:
          - src/foo.c
          - src/bar.c
    """).strip()
    (tmp_path / "r4").mkdir()
    (tmp_path / "r4" / "scenario.md").write_text(md_nested)
    (tmp_path / "r4" / "main.c").write_text("int main(){}")

    loader = ScenarioLoader(eval_dir=str(tmp_path))
    s = loader.load("r4")
    assert s.upstream_snapshot_relevant_files == ["src/foo.c", "src/bar.c"]


def test_parse_upstream_snapshot_helper_empty():
    """Helper returns (None, None, []) on empty input."""
    repo, sha, files = _parse_upstream_snapshot("")
    assert repo is None
    assert sha is None
    assert files == []


def test_parse_upstream_snapshot_helper_full():
    """Helper parses all three fields correctly."""
    section = textwrap.dedent("""
        - **Repo**: https://github.com/mrdoob/three.js
        - **SHA**: deadcafe1234
        - **Relevant Files**:
          - src/renderers/webgpu/WebGPUShadowMap.js
          - src/nodes/lighting/ShadowNode.js
    """).strip()
    repo, sha, files = _parse_upstream_snapshot(section)
    assert repo == "https://github.com/mrdoob/three.js"
    assert sha == "deadcafe1234"
    assert files == [
        "src/renderers/webgpu/WebGPUShadowMap.js",
        "src/nodes/lighting/ShadowNode.js",
    ]
