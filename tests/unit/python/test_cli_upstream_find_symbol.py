"""`gpa upstream find-symbol` — language-aware symbol-definition finder
+ raised read cap + grep --context.

R12 audit found `gpa upstream grep` is the only navigation tool the
agent has, but it has no `--context` and the 200 KB read cap truncates
godot files at 369–402 KB. Three small additions:

- `find-symbol NAME` — match definition lines across language-known
  patterns (function/class/method definitions). Returns
  `{path, line, kind, signature, lang}` per hit. ~80 LoC + tests.
- `grep --context N` — emit N lines before/after each match.
- `read --max-bytes` default raised from 200 K to 512 K.
"""
from __future__ import annotations

import io
import json
from pathlib import Path

import pytest


# ---------------------------------------------------------------------------
# find-symbol
# ---------------------------------------------------------------------------


def _populate_polyglot_root(root: Path) -> None:
    (root / "src").mkdir()
    (root / "src" / "render.cpp").write_text(
        "void render_frame() {\n"
        "    glClear(GL_COLOR_BUFFER_BIT);\n"
        "}\n"
        "\n"
        "static int compute_state(int x) {\n"
        "    return x * 2;\n"
        "}\n"
    )
    (root / "src" / "draw.ts").write_text(
        "export function drawFill(painter: Painter): void {\n"
        "    painter.render();\n"
        "}\n"
        "\n"
        "export class Painter {\n"
        "    constructor() {}\n"
        "}\n"
        "const SHADER_SOURCE = `#version 300 es`;\n"
    )
    (root / "src" / "scene.py").write_text(
        "class Scene:\n"
        "    def update(self):\n"
        "        pass\n"
        "\n"
        "def make_scene():\n"
        "    return Scene()\n"
    )
    (root / "src" / "ui.gd").write_text(
        "extends Node\n"
        "\n"
        "func ready():\n"
        "    pass\n"
        "\n"
        "func _process(delta):\n"
        "    pass\n"
    )


def test_find_symbol_cpp_function(tmp_path, monkeypatch):
    from gpa.cli.commands import upstream as upstream_cmd
    root = tmp_path / "snap"
    root.mkdir()
    _populate_polyglot_root(root)
    monkeypatch.setenv("GPA_UPSTREAM_ROOT", str(root))
    buf = io.StringIO()
    rc = upstream_cmd.run_find_symbol(
        name="render_frame", subdir="", lang="",
        max_matches=20, print_stream=buf,
    )
    assert rc == 0
    obj = json.loads(buf.getvalue())
    assert len(obj["matches"]) == 1
    m = obj["matches"][0]
    assert m["path"] == "src/render.cpp"
    assert m["line"] == 1
    assert m["kind"] == "function"
    assert "render_frame" in m["signature"]


def test_find_symbol_cpp_static_function(tmp_path, monkeypatch):
    from gpa.cli.commands import upstream as upstream_cmd
    root = tmp_path / "snap"
    root.mkdir()
    _populate_polyglot_root(root)
    monkeypatch.setenv("GPA_UPSTREAM_ROOT", str(root))
    buf = io.StringIO()
    rc = upstream_cmd.run_find_symbol(
        name="compute_state", subdir="", lang="",
        max_matches=20, print_stream=buf,
    )
    obj = json.loads(buf.getvalue())
    paths = [m["path"] for m in obj["matches"]]
    assert "src/render.cpp" in paths


def test_find_symbol_typescript_function(tmp_path, monkeypatch):
    from gpa.cli.commands import upstream as upstream_cmd
    root = tmp_path / "snap"
    root.mkdir()
    _populate_polyglot_root(root)
    monkeypatch.setenv("GPA_UPSTREAM_ROOT", str(root))
    buf = io.StringIO()
    rc = upstream_cmd.run_find_symbol(
        name="drawFill", subdir="", lang="",
        max_matches=20, print_stream=buf,
    )
    obj = json.loads(buf.getvalue())
    paths = [m["path"] for m in obj["matches"]]
    assert "src/draw.ts" in paths


def test_find_symbol_typescript_class(tmp_path, monkeypatch):
    from gpa.cli.commands import upstream as upstream_cmd
    root = tmp_path / "snap"
    root.mkdir()
    _populate_polyglot_root(root)
    monkeypatch.setenv("GPA_UPSTREAM_ROOT", str(root))
    buf = io.StringIO()
    rc = upstream_cmd.run_find_symbol(
        name="Painter", subdir="", lang="",
        max_matches=20, print_stream=buf,
    )
    obj = json.loads(buf.getvalue())
    kinds = [m["kind"] for m in obj["matches"]]
    assert "class" in kinds


def test_find_symbol_python_def_and_class(tmp_path, monkeypatch):
    from gpa.cli.commands import upstream as upstream_cmd
    root = tmp_path / "snap"
    root.mkdir()
    _populate_polyglot_root(root)
    monkeypatch.setenv("GPA_UPSTREAM_ROOT", str(root))
    buf = io.StringIO()
    rc = upstream_cmd.run_find_symbol(
        name="make_scene", subdir="", lang="",
        max_matches=20, print_stream=buf,
    )
    obj = json.loads(buf.getvalue())
    assert any(m["path"] == "src/scene.py" for m in obj["matches"])

    buf = io.StringIO()
    rc = upstream_cmd.run_find_symbol(
        name="Scene", subdir="", lang="",
        max_matches=20, print_stream=buf,
    )
    obj = json.loads(buf.getvalue())
    kinds = [m["kind"] for m in obj["matches"]]
    assert "class" in kinds


def test_find_symbol_godot_func(tmp_path, monkeypatch):
    from gpa.cli.commands import upstream as upstream_cmd
    root = tmp_path / "snap"
    root.mkdir()
    _populate_polyglot_root(root)
    monkeypatch.setenv("GPA_UPSTREAM_ROOT", str(root))
    buf = io.StringIO()
    rc = upstream_cmd.run_find_symbol(
        name="_process", subdir="", lang="",
        max_matches=20, print_stream=buf,
    )
    obj = json.loads(buf.getvalue())
    assert any(m["path"] == "src/ui.gd" for m in obj["matches"])


def test_find_symbol_no_match(tmp_path, monkeypatch):
    from gpa.cli.commands import upstream as upstream_cmd
    root = tmp_path / "snap"
    root.mkdir()
    _populate_polyglot_root(root)
    monkeypatch.setenv("GPA_UPSTREAM_ROOT", str(root))
    buf = io.StringIO()
    rc = upstream_cmd.run_find_symbol(
        name="nonexistent_symbol_xyz", subdir="", lang="",
        max_matches=20, print_stream=buf,
    )
    assert rc == 0
    obj = json.loads(buf.getvalue())
    assert obj["matches"] == []


def test_find_symbol_lang_filter(tmp_path, monkeypatch):
    """When --lang is given, only files matching that lang's extensions
    are searched."""
    from gpa.cli.commands import upstream as upstream_cmd
    root = tmp_path / "snap"
    root.mkdir()
    _populate_polyglot_root(root)
    # Add a python file whose body says `Painter` to verify we skip it
    # when lang=ts.
    (root / "src" / "ghost.py").write_text("class Painter:\n    pass\n")
    monkeypatch.setenv("GPA_UPSTREAM_ROOT", str(root))
    buf = io.StringIO()
    rc = upstream_cmd.run_find_symbol(
        name="Painter", subdir="", lang="ts",
        max_matches=20, print_stream=buf,
    )
    obj = json.loads(buf.getvalue())
    paths = [m["path"] for m in obj["matches"]]
    assert "src/draw.ts" in paths
    assert "src/ghost.py" not in paths


# ---------------------------------------------------------------------------
# read --max-bytes default raised to 512 K
# ---------------------------------------------------------------------------


def test_read_default_max_bytes_is_512k():
    from gpa.cli.commands import upstream as upstream_cmd
    assert upstream_cmd._DEFAULT_MAX_BYTES >= 512_000


# ---------------------------------------------------------------------------
# grep --context N
# ---------------------------------------------------------------------------


def test_grep_with_context_includes_surrounding_lines(tmp_path, monkeypatch):
    from gpa.cli.commands import upstream as upstream_cmd
    root = tmp_path / "snap"
    root.mkdir()
    (root / "main.c").write_text(
        "line one\nline two\nMATCH HERE\nline four\nline five\n"
    )
    monkeypatch.setenv("GPA_UPSTREAM_ROOT", str(root))
    buf = io.StringIO()
    rc = upstream_cmd.run_grep(
        pattern="MATCH", subdir="", glob="",
        max_matches=10, context=2, print_stream=buf,
    )
    assert rc == 0
    obj = json.loads(buf.getvalue())
    assert len(obj["matches"]) == 1
    m = obj["matches"][0]
    # Context fields present
    assert "context_before" in m
    assert "context_after" in m
    assert m["context_before"] == ["line one", "line two"]
    assert m["context_after"] == ["line four", "line five"]


def test_grep_default_context_zero_keeps_old_shape(tmp_path, monkeypatch):
    """Default context=0 — match shape is back-compat (no context_before /
    context_after fields)."""
    from gpa.cli.commands import upstream as upstream_cmd
    root = tmp_path / "snap"
    root.mkdir()
    (root / "main.c").write_text("line one\nMATCH HERE\nline three\n")
    monkeypatch.setenv("GPA_UPSTREAM_ROOT", str(root))
    buf = io.StringIO()
    rc = upstream_cmd.run_grep(
        pattern="MATCH", subdir="", glob="",
        max_matches=10, context=0, print_stream=buf,
    )
    obj = json.loads(buf.getvalue())
    m = obj["matches"][0]
    assert "path" in m
    assert "line" in m
    assert "text" in m
    assert "context_before" not in m
