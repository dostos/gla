"""Tests for the deterministic extract_draft module.

These tests follow the plan in docs/superpowers/plans/2026-05-01-single-path-mining.md
(Task 3, steps 3.1-3.7). They verify that the deterministic replacement for the
LLM-based draft.py produces correctly shaped DraftResult objects and raises
ExtractionFailure when required fields can't be extracted.
"""
import json
from pathlib import Path

from gpa.eval.curation.extract_draft import extract_draft, ExtractionFailure

FIXTURES = Path(__file__).parent / "fixtures" / "curation" / "issue_threads"


def test_extract_well_structured_issue():
    """A short issue body with an inline 'Expected:' phrase passes the
    short-body heuristic (<1500 chars) and yields a populated DraftResult."""
    thread_text = (FIXTURES / "threejs_simple_state_leak.json").read_text()
    fix_pr = {
        "url": "https://github.com/mrdoob/three.js/pull/99999",
        "commit_sha": "deadbeefcafe",
        "files_changed": ["src/renderers/webgl/WebGLState.js"],
    }
    result = extract_draft(
        thread=json.loads(thread_text),
        fix_pr=fix_pr,
        taxonomy_cell="web-3d/three.js",
    )
    assert result.user_report.strip() != ""
    # The threejs fixture has "Expected:" inline (no section header), so
    # extracted expected_section will be empty; the substring check on
    # user_report is what passes for this fixture.
    assert "expected" in result.user_report.lower() or result.expected_section
    assert result.fix_commit_sha == "deadbeefcafe"
    assert result.expected_files == ["src/renderers/webgl/WebGLState.js"]
    assert result.bug_signature_yaml.startswith("type: code_location")


def test_extract_unparseable_raises():
    """A long, completely unstructured body (no Expected/Actual sections AND
    no markdown headers) must raise ExtractionFailure."""
    # Pad a code-fence body well past the 1500-char short-body threshold,
    # with NO markdown headers — pure unstructured text.
    code_dump = "undefined is not a function\n  at foo (bar.js:10)\n"
    long_body = code_dump + ("filler line with no structure\n" * 80)
    assert len(long_body) > 1500
    thread = {
        "title": "Renderer broken",
        "body": long_body,
        "comments": [],
    }
    fix_pr = {
        "url": "https://example/pr/1",
        "commit_sha": "abc",
        "files_changed": ["x.rs"],
    }
    try:
        extract_draft(
            thread=thread, fix_pr=fix_pr, taxonomy_cell="web-3d/three.js"
        )
        assert False, "expected ExtractionFailure"
    except ExtractionFailure as e:
        msg = str(e).lower()
        assert "no section structure" in msg or "too long" in msg


def test_extract_godot_style_issue_body():
    """Godot's issue template uses '### Issue description' / '### Steps to
    reproduce' rather than Expected/Actual. Such bodies were previously
    rejected as 'issue body lacks Expected/Actual sections...'.

    With the expanded section recognition, these now extract: either
    matching the new headers, or accepted via the structured-body
    fallback (any `## ...` header is enough for a long body)."""
    body = (
        "### Tested versions\n4.5\n\n"
        "### System information\nLinux Vulkan\n\n"
        "### Issue description\n"
        "Cube renders with corruption when validation layers run.\n"
        "We see massive distortion across the texture.\n\n"
        "### Steps to reproduce\n1. Open project\n2. Run with --gpu-validation\n\n"
    ) + ("Stack trace:\n" + "frame at 0x123\n" * 200)
    assert len(body) > 1500
    thread = {
        "title": "Cube has corruption with validation layers",
        "body": body,
        "comments": [],
    }
    fix_pr = {
        "url": "https://github.com/godotengine/godot/pull/118968",
        "commit_sha": "f059d64",
        "files_changed": ["servers/rendering/renderer_rd/foo.cpp"],
    }
    result = extract_draft(
        thread=thread, fix_pr=fix_pr,
        taxonomy_cell="framework-maintenance.native-engine.godot",
    )
    assert result.user_report.strip() != ""
    assert result.fix_commit_sha == "f059d64"


def test_filter_source_files_drops_tests_docs_examples():
    """Path-segment + basename filter must drop test/doc/example/md files,
    leaving only real source files. Plan step 3.6."""
    from gpa.eval.curation.extract_draft import _filter_source_files

    raw = [
        "crates/bevy_pbr/src/render/mesh.rs",
        "crates/bevy_pbr/src/render/mesh_test.rs",
        "src/mobjects/three-d/Sphere.test.ts",
        "src/mobjects/three-d/Sphere.spec.ts",
        "tests/integration/render.rs",
        "__tests__/render.ts",
        "examples/3d/repro.rs",
        "docs/changelog.md",
        "CHANGELOG.md",
        "package.json",
        "package-lock.json",
        "pnpm-lock.yaml",
    ]
    assert _filter_source_files(raw) == ["crates/bevy_pbr/src/render/mesh.rs"]
