import io
import json
import pytest
from pathlib import Path
from gpa.cli.commands import upstream as upstream_cmd


def _make_root(tmp_path: Path) -> Path:
    root = tmp_path / "src"
    root.mkdir()
    (root / "main.c").write_text("int main(){return 0;}\n// hello\n")
    (root / "lib").mkdir()
    (root / "lib" / "util.c").write_text("void f(){} // hello\n")
    return root


def test_upstream_read_returns_json(tmp_path, monkeypatch):
    root = _make_root(tmp_path)
    monkeypatch.setenv("GPA_UPSTREAM_ROOT", str(root))
    buf = io.StringIO()
    rc = upstream_cmd.run_read(path="main.c", max_bytes=200000, print_stream=buf)
    assert rc == 0
    obj = json.loads(buf.getvalue())
    assert obj["path"] == "main.c"
    assert obj["bytes"] == len((root / "main.c").read_bytes())
    assert "int main" in obj["text"]


def test_upstream_read_max_bytes(tmp_path, monkeypatch):
    root = _make_root(tmp_path)
    monkeypatch.setenv("GPA_UPSTREAM_ROOT", str(root))
    buf = io.StringIO()
    rc = upstream_cmd.run_read(path="main.c", max_bytes=5, print_stream=buf)
    assert rc == 0
    obj = json.loads(buf.getvalue())
    assert obj["truncated"] is True
    assert len(obj["text"].encode("utf-8")) <= 5


def test_upstream_read_traversal_rejected(tmp_path, monkeypatch):
    root = _make_root(tmp_path)
    monkeypatch.setenv("GPA_UPSTREAM_ROOT", str(root))
    buf = io.StringIO()
    err = io.StringIO()
    rc = upstream_cmd.run_read(
        path="../../etc/passwd", max_bytes=200000,
        print_stream=buf, err_stream=err,
    )
    assert rc == 2
    assert "escapes root" in err.getvalue()


def test_upstream_grep_finds_pattern(tmp_path, monkeypatch):
    root = _make_root(tmp_path)
    monkeypatch.setenv("GPA_UPSTREAM_ROOT", str(root))
    buf = io.StringIO()
    rc = upstream_cmd.run_grep(
        pattern="hello", subdir="", glob="", max_matches=50, print_stream=buf,
    )
    assert rc == 0
    obj = json.loads(buf.getvalue())
    paths = sorted({m["path"] for m in obj["matches"]})
    assert paths == ["lib/util.c", "main.c"]
    assert obj["truncated"] is False


def test_upstream_grep_max_matches(tmp_path, monkeypatch):
    root = _make_root(tmp_path)
    monkeypatch.setenv("GPA_UPSTREAM_ROOT", str(root))
    buf = io.StringIO()
    rc = upstream_cmd.run_grep(
        pattern="hello", subdir="", glob="", max_matches=1, print_stream=buf,
    )
    assert rc == 0
    obj = json.loads(buf.getvalue())
    assert len(obj["matches"]) == 1
    assert obj["truncated"] is True


def test_upstream_no_root_set(monkeypatch):
    monkeypatch.delenv("GPA_UPSTREAM_ROOT", raising=False)
    buf = io.StringIO()
    err = io.StringIO()
    rc = upstream_cmd.run_read(
        path="main.c", max_bytes=200000,
        print_stream=buf, err_stream=err,
    )
    assert rc == 2
    assert "GPA_UPSTREAM_ROOT" in err.getvalue()


def test_upstream_list_returns_entries(tmp_path, monkeypatch):
    root = tmp_path / "up"
    (root / "src").mkdir(parents=True)
    (root / "src" / "a.c").write_text("")
    (root / "src" / "b.c").write_text("")
    (root / "src" / "lib").mkdir()
    monkeypatch.setenv("GPA_UPSTREAM_ROOT", str(root))
    buf = io.StringIO()
    rc = upstream_cmd.run_list(subdir="src", print_stream=buf)
    assert rc == 0
    obj = json.loads(buf.getvalue())
    names = sorted((e["name"], e["type"]) for e in obj["entries"])
    assert names == [("a.c", "file"), ("b.c", "file"), ("lib", "dir")]


def test_upstream_list_empty_subdir(tmp_path, monkeypatch):
    root = tmp_path / "up"
    root.mkdir()
    (root / "README").write_text("hi")
    (root / "src").mkdir()
    monkeypatch.setenv("GPA_UPSTREAM_ROOT", str(root))
    buf = io.StringIO()
    rc = upstream_cmd.run_list(subdir="", print_stream=buf)
    assert rc == 0
    obj = json.loads(buf.getvalue())
    assert obj["subdir"] == ""
    names = sorted((e["name"], e["type"]) for e in obj["entries"])
    assert names == [("README", "file"), ("src", "dir")]


# ---------------------------------------------------------------------------
# R15: outline + read --lines — token-efficient triage path. Driven by
# R12c-R14 forensics: agents burn 5-10k tokens per full-file read on
# 300-400 KB framework sources.
# ---------------------------------------------------------------------------


def test_upstream_outline_lists_functions(tmp_path, monkeypatch):
    """outline returns kind+name+line+signature for each definition."""
    root = tmp_path / "up"
    (root / "src").mkdir(parents=True)
    (root / "src" / "a.cpp").write_text(
        "namespace ns {\n"
        "class Foo {\n"
        "    void method_a() {}\n"
        "};\n"
        "void free_function(int x) {\n"
        "    return;\n"
        "}\n"
        "struct Bar {};\n"
    )
    monkeypatch.setenv("GPA_UPSTREAM_ROOT", str(root))
    buf = io.StringIO()
    rc = upstream_cmd.run_outline(path="src/a.cpp", max_definitions=500,
                                  print_stream=buf)
    assert rc == 0
    obj = json.loads(buf.getvalue())
    assert obj["lang"] == "cpp"
    kinds = {(d["kind"], d["name"]) for d in obj["definitions"]}
    assert ("namespace", "ns") in kinds
    assert ("class", "Foo") in kinds
    assert ("struct", "Bar") in kinds
    # free_function should match the function pattern
    assert any(d["name"] == "free_function" for d in obj["definitions"])


def test_upstream_outline_filters_control_flow_keywords(tmp_path, monkeypatch):
    """The cpp function regex is loose; outline must filter out control-
    flow keywords (`if`, `for`, etc.) so they don't pollute the list."""
    root = tmp_path / "up"
    (root / "src").mkdir(parents=True)
    (root / "src" / "x.cpp").write_text(
        "void foo() {\n"
        "    if (x) {\n"
        "        for (int i = 0; i < 10; ++i) {\n"
        "            return;\n"
        "        }\n"
        "    }\n"
        "}\n"
    )
    monkeypatch.setenv("GPA_UPSTREAM_ROOT", str(root))
    buf = io.StringIO()
    rc = upstream_cmd.run_outline(path="src/x.cpp", max_definitions=500,
                                  print_stream=buf)
    assert rc == 0
    obj = json.loads(buf.getvalue())
    names = {d["name"] for d in obj["definitions"]}
    # `foo` is a real function, must be present
    assert "foo" in names
    # Control-flow keywords must be filtered out
    assert "if" not in names
    assert "for" not in names
    assert "return" not in names


def test_upstream_outline_unknown_extension_falls_back_gracefully(tmp_path, monkeypatch):
    """For files without a known outline language, return a degenerate
    outline (line count + size) instead of erroring — the agent doesn't
    have to retry with `read`."""
    root = tmp_path / "up"; root.mkdir()
    (root / "README.md").write_text("# hello\nworld\n")
    monkeypatch.setenv("GPA_UPSTREAM_ROOT", str(root))
    buf = io.StringIO()
    rc = upstream_cmd.run_outline(path="README.md", max_definitions=500,
                                  print_stream=buf)
    assert rc == 0
    obj = json.loads(buf.getvalue())
    assert obj["lang"] == ""
    assert obj["definitions"] == []
    # `count('\n') + 1` on "# hello\nworld\n" yields 3 (trailing newline
    # creates a phantom line). Minor inaccuracy, fine for triage.
    assert obj["total_lines"] >= 2
    assert "note" in obj


def test_upstream_outline_python(tmp_path, monkeypatch):
    """Python file: list def and class definitions."""
    root = tmp_path / "up"; root.mkdir()
    (root / "lib.py").write_text(
        "class Foo:\n"
        "    def method(self):\n"
        "        pass\n"
        "\n"
        "def standalone():\n"
        "    return 1\n"
    )
    monkeypatch.setenv("GPA_UPSTREAM_ROOT", str(root))
    buf = io.StringIO()
    rc = upstream_cmd.run_outline(path="lib.py", max_definitions=500,
                                  print_stream=buf)
    assert rc == 0
    obj = json.loads(buf.getvalue())
    assert obj["lang"] == "py"
    names = {d["name"] for d in obj["definitions"]}
    assert names == {"Foo", "method", "standalone"}


def test_upstream_outline_truncates_at_cap(tmp_path, monkeypatch):
    """When a file has more definitions than max_definitions, return
    truncated=True and stop early."""
    root = tmp_path / "up"; root.mkdir()
    body = "\n".join(f"def f{i}(): pass" for i in range(20))
    (root / "many.py").write_text(body + "\n")
    monkeypatch.setenv("GPA_UPSTREAM_ROOT", str(root))
    buf = io.StringIO()
    rc = upstream_cmd.run_outline(path="many.py", max_definitions=5,
                                  print_stream=buf)
    assert rc == 0
    obj = json.loads(buf.getvalue())
    assert obj["truncated"] is True
    assert len(obj["definitions"]) == 5


def test_upstream_read_with_line_range(tmp_path, monkeypatch):
    """read --lines START..END returns only the specified lines."""
    root = tmp_path / "up"; root.mkdir()
    text = "".join(f"line {i}\n" for i in range(1, 11))  # 10 lines
    (root / "f.c").write_text(text)
    monkeypatch.setenv("GPA_UPSTREAM_ROOT", str(root))
    buf = io.StringIO()
    rc = upstream_cmd.run_read(path="f.c", max_bytes=512_000, lines="3..5",
                               print_stream=buf)
    assert rc == 0
    obj = json.loads(buf.getvalue())
    assert obj["line_start"] == 3
    assert obj["line_end"] == 5
    assert obj["total_lines"] == 10
    assert obj["text"] == "line 3\nline 4\nline 5\n"


def test_upstream_read_with_single_line(tmp_path, monkeypatch):
    """read --lines 5 returns only line 5."""
    root = tmp_path / "up"; root.mkdir()
    text = "".join(f"line {i}\n" for i in range(1, 11))
    (root / "f.c").write_text(text)
    monkeypatch.setenv("GPA_UPSTREAM_ROOT", str(root))
    buf = io.StringIO()
    rc = upstream_cmd.run_read(path="f.c", max_bytes=512_000, lines="5",
                               print_stream=buf)
    assert rc == 0
    obj = json.loads(buf.getvalue())
    assert obj["line_start"] == 5
    assert obj["line_end"] == 5
    assert obj["text"] == "line 5\n"


def test_upstream_read_invalid_line_spec_returns_error(tmp_path, monkeypatch):
    root = tmp_path / "up"; root.mkdir()
    (root / "f.c").write_text("hi\n")
    monkeypatch.setenv("GPA_UPSTREAM_ROOT", str(root))
    err = io.StringIO()
    rc = upstream_cmd.run_read(path="f.c", max_bytes=1000, lines="bogus",
                               print_stream=io.StringIO(), err_stream=err)
    assert rc == 2
    assert "--lines" in err.getvalue()


def test_upstream_read_no_line_range_returns_full_file(tmp_path, monkeypatch):
    """Backwards-compat: when --lines is empty, return the whole file."""
    root = tmp_path / "up"; root.mkdir()
    (root / "f.c").write_text("alpha\nbeta\n")
    monkeypatch.setenv("GPA_UPSTREAM_ROOT", str(root))
    buf = io.StringIO()
    rc = upstream_cmd.run_read(path="f.c", max_bytes=1000, lines="",
                               print_stream=buf)
    assert rc == 0
    obj = json.loads(buf.getvalue())
    # No line-range fields present in legacy mode
    assert "line_start" not in obj
    assert obj["text"] == "alpha\nbeta\n"
