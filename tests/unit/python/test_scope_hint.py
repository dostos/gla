"""Tests for compute_scope_hint — the fix-PR scope summary that gets
injected into agent prompts to calibrate search depth without leaking
which specific files the canonical fix touched."""
from __future__ import annotations

from gpa.eval.scope_hint import compute_scope_hint


def test_empty_returns_placeholder():
    assert compute_scope_hint([]) == "no fix files recorded"
    assert compute_scope_hint([""]) == "no fix files recorded"


def test_single_file_with_dir():
    assert compute_scope_hint(["src/render/Renderer.ts"]) == "1 file in src/render/"


def test_single_file_no_dir():
    assert compute_scope_hint(["main.c"]) == "1 file (main.c)"


def test_two_files_same_dir():
    out = compute_scope_hint(["src/a.ts", "src/b.ts"])
    assert "2 files in src/" == out


def test_three_files_same_subdir():
    out = compute_scope_hint([
        "src/render/draw.ts",
        "src/render/state.ts",
        "src/render/buffer.ts",
    ])
    assert "3 files in src/render/" == out


def test_godot_renderer_rd_pattern():
    """Real R12c fix: 13 files spanning 4 sub-dirs of renderer_rd/.
    Hint should name renderer_rd/ as the area; the agent learns the
    bug is renderer-RD-internal, not in editor/ or core/."""
    files = [
        "servers/rendering/renderer_rd/forward_clustered/render_forward_clustered.cpp",
        "servers/rendering/renderer_rd/forward_mobile/render_forward_mobile.cpp",
        "servers/rendering/renderer_rd/forward_mobile/render_forward_mobile.h",
        "servers/rendering/renderer_rd/renderer_scene_render_rd.cpp",
        "servers/rendering/renderer_rd/storage_rd/render_scene_buffers_rd.cpp",
    ]
    out = compute_scope_hint(files)
    assert "5 files" in out
    assert "servers/rendering/renderer_rd/" in out
    # Should mention the spread of sub-dirs without listing every file
    assert "forward_clustered/" in out or "sub-directories" in out


def test_no_common_prefix_falls_back_to_top_level():
    """When files span unrelated top-level dirs (e.g. editor/ +
    servers/), the hint shows the top-level distribution."""
    files = [
        "editor/editor_node.cpp",
        "servers/rendering/foo.cpp",
        "scene/main/scene_tree.cpp",
    ]
    out = compute_scope_hint(files)
    assert "3 files" in out
    assert "across top-level" in out
    # All three top-level dirs should appear
    assert "editor/" in out
    assert "servers/" in out
    assert "scene/" in out


def test_many_top_level_dirs_truncates():
    files = [
        "a/x.c", "b/x.c", "c/x.c", "d/x.c", "e/x.c", "f/x.c",
    ]
    out = compute_scope_hint(files)
    assert "6 files" in out
    assert "+3 others" in out  # top 3 shown, 3 others


def test_does_not_leak_filenames():
    """The hint must not contain ANY basename from the input."""
    files = [
        "servers/rendering/renderer_rd/forward_clustered/render_forward_clustered.cpp",
        "servers/rendering/renderer_rd/storage_rd/render_scene_buffers_rd.cpp",
    ]
    out = compute_scope_hint(files)
    assert "render_forward_clustered" not in out
    assert "render_scene_buffers_rd" not in out
    # But directory names ARE allowed (that's the area signal)
    assert "renderer_rd" in out


def test_handles_files_under_common_dir_directly():
    """Files directly in the common dir (no further sub-dir) should
    not produce '(direct)' as a sub-directory category by itself."""
    files = [
        "src/foo.ts",
        "src/bar.ts",
    ]
    out = compute_scope_hint(files)
    assert "2 files in src/" == out


def test_mixed_direct_and_subdir():
    files = [
        "src/foo.ts",
        "src/render/draw.ts",
        "src/state/buffer.ts",
    ]
    out = compute_scope_hint(files)
    assert "3 files under src/" in out
    assert "render/" in out and "state/" in out
