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
    """A long body (>1500 chars) without Expected/Actual sections must raise
    ExtractionFailure (the 'too long to use raw' path)."""
    # Pad a code-fence body well past the 1500-char short-body threshold.
    code_dump = (
        "```\n"
        "undefined is not a function\n"
        "  at foo (bar.js:10)\n"
        "```\n"
    )
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
        assert "expected" in msg or "actual" in msg or "too long" in msg


def test_filter_source_files_drops_tests_docs_examples():
    """Path-segment + basename filter must drop test/doc/example/md files,
    leaving only real source files. Plan step 3.6."""
    from gpa.eval.curation.extract_draft import _filter_source_files

    raw = [
        "crates/bevy_pbr/src/render/mesh.rs",
        "crates/bevy_pbr/src/render/mesh_test.rs",
        "tests/integration/render.rs",
        "examples/3d/repro.rs",
        "docs/changelog.md",
        "CHANGELOG.md",
    ]
    assert _filter_source_files(raw) == ["crates/bevy_pbr/src/render/mesh.rs"]
