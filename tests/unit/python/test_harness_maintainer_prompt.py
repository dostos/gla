"""Tests for Phase 4 harness maintainer-framing prompt selection and
full-repo snapshot tool surface.

See ``docs/superpowers/specs/2026-04-21-maintainer-framing-design.md``
Phase 4.  The harness uses ``scenario.fix.bug_class`` to pick a
class-specific system prompt; when no Fix metadata is present the agent
falls back to its built-in diagnosis prompt (legacy path).
"""
from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from gpa.eval.harness import EvalHarness
from gpa.eval.scenario import FixMetadata, ScenarioMetadata


# ---------------------------------------------------------------------------
# Helpers (mirrored from test_harness_snapshot_tools.py)
# ---------------------------------------------------------------------------


def _make_scenario(**overrides) -> ScenarioMetadata:
    base = dict(
        id="test_id",
        title="Test scenario",
        bug_description="VERBATIM_ISSUE_BODY_SENTINEL",
        expected_output="e",
        actual_output="a",
        ground_truth_diagnosis="gt",
        ground_truth_fix="fix",
        difficulty=3,
        adversarial_principles=[],
        gpa_advantage="",
        source_path="/tmp/x.c",
        binary_name="test_id",
        framework="three.js",
    )
    base.update(overrides)
    return ScenarioMetadata(**base)


def _make_harness(snapshot_root: Path | None = None) -> EvalHarness:
    harness = EvalHarness.__new__(EvalHarness)
    harness.results = []
    harness._model = "test"
    if snapshot_root is not None:
        mock_fetcher = MagicMock()
        mock_fetcher.fetch.return_value = snapshot_root
        harness._snapshot_fetcher = mock_fetcher
    else:
        harness._snapshot_fetcher = None
    harness.runner = MagicMock()
    harness.runner.read_source.return_value = "int main(){}"
    harness.loader = MagicMock()
    harness._scorer = MagicMock()
    return harness


def _fix(bug_class: str, files=("src/Renderer.js",), summary: str = "gt") -> FixMetadata:
    return FixMetadata(
        fix_pr_url="https://github.com/x/y/pull/1",
        fix_sha="deadbeef",
        fix_parent_sha="cafebabe",
        bug_class=bug_class,
        files=list(files),
        change_summary=summary,
    )


# ---------------------------------------------------------------------------
# Prompt selection by bug_class
# ---------------------------------------------------------------------------


def test_framework_internal_uses_maintainer_prompt():
    """`bug_class: framework-internal` → tools['system_prompt'] is the
    maintainer prompt containing the user report and framework name."""
    harness = _make_harness()
    scenario = _make_scenario(
        fix=_fix("framework-internal"),
        upstream_snapshot_repo="https://github.com/mrdoob/three.js",
        upstream_snapshot_sha="abc123",
    )
    tools = harness._build_tools(scenario, mode="code_only")
    assert tools["bug_class"] == "framework-internal"
    prompt = tools["system_prompt"]
    assert prompt is not None
    # Must identify the agent as a maintainer of the named framework.
    assert "maintainer" in prompt.lower()
    assert "three.js" in prompt
    # Must carry the verbatim user report.
    assert "VERBATIM_ISSUE_BODY_SENTINEL" in prompt
    # Must mention the framework-internal JSON output schema.
    assert "framework-internal" in prompt
    assert "proposed_patches" in prompt
    # Must forbid main.c / tests/ paths.
    assert "main.c" in prompt
    assert "tests/" in prompt


def test_consumer_misuse_uses_advisor_prompt():
    """`bug_class: consumer-misuse` → advisor prompt (user code change)."""
    harness = _make_harness()
    scenario = _make_scenario(fix=_fix("consumer-misuse"))
    tools = harness._build_tools(scenario, mode="code_only")
    assert tools["bug_class"] == "consumer-misuse"
    prompt = tools["system_prompt"]
    assert prompt is not None
    # The advisor prompt is framed around telling the user to change
    # their code, not patching the framework.
    assert "misuse" in prompt.lower() or "user_code_change" in prompt
    # Must NOT use the maintainer JSON schema.
    assert "proposed_patches" not in prompt
    # Must carry the user report.
    assert "VERBATIM_ISSUE_BODY_SENTINEL" in prompt


def test_user_config_uses_config_advice_prompt():
    """`bug_class: user-config` → config-advice prompt."""
    harness = _make_harness()
    scenario = _make_scenario(fix=_fix("user-config"))
    tools = harness._build_tools(scenario, mode="code_only")
    assert tools["bug_class"] == "user-config"
    prompt = tools["system_prompt"]
    assert prompt is not None
    # The config-advice prompt references a setting_change schema.
    assert "setting_change" in prompt or "config" in prompt.lower()
    # Must NOT use the maintainer or advisor schemas.
    assert "proposed_patches" not in prompt
    assert "user_code_change" not in prompt


def test_legacy_uses_existing_diagnosis_prompt():
    """Legacy scenarios (no ``fix`` metadata) → system_prompt=None so the
    agent falls back to its built-in diagnosis prompt."""
    harness = _make_harness()
    scenario = _make_scenario(fix=None)
    tools = harness._build_tools(scenario, mode="code_only")
    assert tools["bug_class"] == "legacy"
    assert tools["system_prompt"] is None


def test_bug_class_legacy_explicit_also_none():
    """`bug_class: legacy` (retrofit escape hatch) → system_prompt=None."""
    harness = _make_harness()
    scenario = _make_scenario(fix=_fix("legacy", files=[]))
    tools = harness._build_tools(scenario, mode="code_only")
    assert tools["bug_class"] == "legacy"
    assert tools["system_prompt"] is None


def test_with_gla_includes_gpa_tool_block():
    """`mode='with_gla'` includes the OpenGPA-only tool block in the prompt."""
    harness = _make_harness()
    scenario = _make_scenario(
        fix=_fix("framework-internal"),
        upstream_snapshot_repo="https://github.com/mrdoob/three.js",
        upstream_snapshot_sha="abc123",
    )
    prompt_gla = harness._build_tools(scenario, mode="with_gla")["system_prompt"]
    prompt_code = harness._build_tools(scenario, mode="code_only")["system_prompt"]
    # With GPA, the prompt must mention gpa commands; code-only must not.
    assert "gpa report" in prompt_gla or "gpa trace" in prompt_gla
    assert "gpa report" not in prompt_code and "gpa trace" not in prompt_code
    # Both must have the snapshot reference.
    assert "mrdoob/three.js" in prompt_gla
    assert "mrdoob/three.js" in prompt_code


def test_maintainer_prompt_includes_snapshot_sha():
    harness = _make_harness()
    scenario = _make_scenario(
        fix=_fix("framework-internal"),
        upstream_snapshot_repo="https://github.com/mrdoob/three.js",
        upstream_snapshot_sha="SNAPSHOT_SHA_SENTINEL",
    )
    prompt = harness._build_tools(scenario, mode="code_only")["system_prompt"]
    assert "SNAPSHOT_SHA_SENTINEL" in prompt


# ---------------------------------------------------------------------------
# Full-repo snapshot tool surface
# ---------------------------------------------------------------------------


def test_full_repo_access_when_fix_metadata_present(tmp_path):
    """`read_upstream` works on ANY file in the snapshot, not just
    ``relevant_files``.  The spec requires full-tree access when the
    scenario carries Fix metadata."""
    # Build a snapshot tree where only ONE file is listed in the scenario's
    # relevant_files hint list.
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "Hinted.js").write_text("// hint file")
    (tmp_path / "src" / "NotHinted.js").write_text("// not in hint list")
    (tmp_path / "src" / "deep").mkdir()
    (tmp_path / "src" / "deep" / "Nested.js").write_text("// nested, not hinted")
    (tmp_path / ".complete").write_text("")

    harness = _make_harness(snapshot_root=tmp_path)
    scenario = _make_scenario(
        upstream_snapshot_repo="https://github.com/x/y",
        upstream_snapshot_sha="abc123",
        upstream_snapshot_relevant_files=["src/Hinted.js"],
        fix=_fix("framework-internal", files=["src/Hinted.js"]),
    )
    tools = harness._build_tools(scenario, mode="code_only")
    assert "read_upstream" in tools
    assert "list_upstream_files" in tools
    assert "grep_upstream" in tools

    # Read the hinted file — classic case.
    assert tools["read_upstream"]("src/Hinted.js") == "// hint file"
    # Read a NON-hinted file — this is what Phase 4 guarantees.
    assert tools["read_upstream"]("src/NotHinted.js") == "// not in hint list"
    # Read a deeply-nested file never mentioned in the hint list.
    assert (
        tools["read_upstream"]("src/deep/Nested.js") == "// nested, not hinted"
    )
    # list_upstream_files walks the full tree too.
    root_listing = tools["list_upstream_files"]("")
    assert "src/" in root_listing
    deep_listing = tools["list_upstream_files"]("src/deep")
    assert "Nested.js" in deep_listing

    # grep_upstream sees ALL files, including NotHinted.js.
    grep_out = tools["grep_upstream"]("hint")
    assert "Hinted.js" in grep_out
    assert "NotHinted.js" in grep_out


def test_full_repo_access_works_without_fix_metadata_too(tmp_path):
    """Legacy scenarios (no Fix) with snapshot refs still get full-repo
    access — the spec never restricted based on `fix` presence."""
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "File.js").write_text("content")
    (tmp_path / ".complete").write_text("")

    harness = _make_harness(snapshot_root=tmp_path)
    scenario = _make_scenario(
        upstream_snapshot_repo="https://github.com/x/y",
        upstream_snapshot_sha="abc123",
        upstream_snapshot_relevant_files=[],  # empty hint list
        fix=None,  # legacy
    )
    tools = harness._build_tools(scenario, mode="code_only")
    assert tools["read_upstream"]("src/File.js") == "content"


def test_build_tools_has_bug_class_and_system_prompt_keys():
    """Contract: ``tools`` dict always exposes bug_class + system_prompt,
    even for legacy scenarios (where they are "legacy" + None)."""
    harness = _make_harness()
    scenario = _make_scenario()
    tools = harness._build_tools(scenario, mode="code_only")
    assert "bug_class" in tools
    assert "system_prompt" in tools


# ---------------------------------------------------------------------------
# run_scenario integration: scorer populates maintainer fields
# ---------------------------------------------------------------------------


def test_run_scenario_populates_maintainer_score_on_framework_internal(tmp_path):
    """An end-to-end run on a framework-internal scenario populates
    ``maintainer_solved`` / ``file_score`` on the EvalResult."""
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "Renderer.js").write_text("// real file")
    (tmp_path / ".complete").write_text("")

    harness = _make_harness(snapshot_root=tmp_path)
    # Stub the legacy scorer so it never fails on the mock.
    harness._scorer.score.return_value = (False, False)

    scenario = _make_scenario(
        id="test_maintainer_scored",
        upstream_snapshot_repo="https://github.com/x/y",
        upstream_snapshot_sha="abc123",
        fix=_fix("framework-internal", files=["src/Renderer.js"]),
    )
    harness.loader.load.return_value = scenario

    # agent_fn returns a response with a JSON tail that names the correct file.
    json_tail = (
        '{"bug_class": "framework-internal", '
        '"proposed_patches": [{"file": "src/Renderer.js", "change_summary": "ok"}]}'
    )
    def _agent_fn(scn, mode, tools):
        return (json_tail, 10, 20, 0, 3, 1.0)

    r = harness.run_scenario("test_maintainer_scored", "code_only", _agent_fn)
    assert r.bug_class == "framework-internal"
    assert r.parsed_json is True
    assert r.maintainer_solved is True
    assert r.file_score == pytest.approx(1.0)
    assert r.file_hits == ["src/Renderer.js"]


def test_run_scenario_flags_missing_json_tail():
    """Agent that forgets the JSON tail → parsed_json=False, maintainer
    fields set to the scorer's failure output."""
    harness = _make_harness()
    harness._scorer.score.return_value = (False, False)
    scenario = _make_scenario(
        id="test_missing_json",
        fix=_fix("framework-internal", files=["src/a.js"]),
    )
    harness.loader.load.return_value = scenario

    def _agent_fn(scn, mode, tools):
        return ("Just prose, no JSON tail.", 10, 20, 0, 3, 1.0)

    r = harness.run_scenario("test_missing_json", "code_only", _agent_fn)
    assert r.parsed_json is False
    assert r.maintainer_solved is False
    assert r.file_score == 0.0


def test_run_scenario_legacy_scenario_leaves_maintainer_fields_none():
    """Legacy scenarios don't populate the maintainer fields on EvalResult."""
    harness = _make_harness()
    harness._scorer.score.return_value = (True, True)
    scenario = _make_scenario(id="test_legacy", fix=None)
    harness.loader.load.return_value = scenario

    def _agent_fn(scn, mode, tools):
        return ("DIAGNOSIS: foo\nFIX: bar", 10, 20, 0, 3, 1.0)

    r = harness.run_scenario("test_legacy", "code_only", _agent_fn)
    assert r.bug_class == "legacy"
    assert r.maintainer_solved is None
    assert r.file_score is None
    assert r.parsed_json is None


def test_prompt_renderer_strips_with_gpa_block_for_code_only():
    """The ``<!-- WITH_GPA_ONLY -->`` block in the raw template must
    disappear entirely when rendered for code_only mode — no marker
    leak into the final prompt."""
    harness = _make_harness()
    scenario = _make_scenario(
        fix=_fix("framework-internal"),
        upstream_snapshot_repo="https://github.com/x/y",
        upstream_snapshot_sha="abc",
    )
    prompt = harness._build_tools(scenario, mode="code_only")["system_prompt"]
    assert "<!-- WITH_GPA_ONLY -->" not in prompt
    assert "<!-- END_WITH_GPA_ONLY -->" not in prompt


def test_prompt_renderer_keeps_block_content_for_with_gla():
    """In with_gla mode, the gated content stays but the markers are gone."""
    harness = _make_harness()
    scenario = _make_scenario(
        fix=_fix("framework-internal"),
        upstream_snapshot_repo="https://github.com/x/y",
        upstream_snapshot_sha="abc",
    )
    prompt = harness._build_tools(scenario, mode="with_gla")["system_prompt"]
    assert "<!-- WITH_GPA_ONLY -->" not in prompt
    assert "<!-- END_WITH_GPA_ONLY -->" not in prompt
    # Content within the block survives.
    assert "gpa report" in prompt
