"""Tests for ``gpa dump`` output formats and ``gpa frames``."""

from __future__ import annotations

import io
import json
from pathlib import Path

import pytest

from gpa.cli.commands import dump as dump_cmd
from gpa.cli.commands import frames as frames_cmd
from gpa.cli.rest_client import RestClient, RestError


@pytest.fixture
def session_dir(tmp_path) -> Path:
    d = tmp_path / "sess"
    d.mkdir()
    (d / "token").write_text("test-token")
    (d / "port").write_text("18080")
    (d / "shm-name").write_text("/gpa-test")
    return d


@pytest.fixture
def injected_rest(client):
    def http_callable(method, path, headers, body=None):
        if method == "GET":
            resp = client.get(path, headers=headers)
        elif method == "POST":
            if body is not None and not isinstance(body, (bytes, str)):
                body = json.dumps(body).encode("utf-8")
                headers = {**headers, "Content-Type": "application/json"}
            resp = client.post(path, headers=headers, content=body)
        else:  # pragma: no cover
            raise AssertionError(method)
        if resp.status_code >= 400:
            raise RestError(
                f"{method} {path} → HTTP {resp.status_code}",
                status=resp.status_code,
            )
        if not resp.content:
            return None
        return resp.json()
    return RestClient(token="test-token", http_callable=http_callable)


# --------------------------------------------------------------------------- #
# dump frame / drawcalls
# --------------------------------------------------------------------------- #


def test_dump_frame_plain(session_dir, injected_rest, monkeypatch):
    monkeypatch.setenv("GPA_SESSION", str(session_dir))
    buf = io.StringIO()
    rc = dump_cmd.run(
        what="frame", frame=1, client=injected_rest, print_stream=buf,
    )
    assert rc == 0
    out = buf.getvalue()
    # Plain form is key\tvalue per line.
    assert "draw_call_count\t42" in out
    assert "framebuffer_width\t800" in out


def test_dump_frame_json(session_dir, injected_rest, monkeypatch):
    monkeypatch.setenv("GPA_SESSION", str(session_dir))
    buf = io.StringIO()
    dump_cmd.run(
        what="frame", frame=1, fmt="json",
        client=injected_rest, print_stream=buf,
    )
    data = json.loads(buf.getvalue())
    assert data["draw_call_count"] == 42


def test_dump_frame_compact(session_dir, injected_rest, monkeypatch):
    monkeypatch.setenv("GPA_SESSION", str(session_dir))
    buf = io.StringIO()
    dump_cmd.run(
        what="frame", frame=1, fmt="compact",
        client=injected_rest, print_stream=buf,
    )
    out = buf.getvalue().strip()
    assert "draw_call_count=42" in out
    # Single-line grep-friendly.
    assert "\n" not in out


def test_dump_drawcalls_plain(session_dir, injected_rest, monkeypatch):
    monkeypatch.setenv("GPA_SESSION", str(session_dir))
    buf = io.StringIO()
    dump_cmd.run(
        what="drawcalls", frame=1, client=injected_rest, print_stream=buf,
    )
    out = buf.getvalue()
    assert "id" in out and "primitive_type" in out
    assert "TRIANGLES" in out


def test_dump_pixel_plain(session_dir, injected_rest, monkeypatch):
    monkeypatch.setenv("GPA_SESSION", str(session_dir))
    buf = io.StringIO()
    rc = dump_cmd.run(
        what="pixel", frame=1, x=10, y=20,
        client=injected_rest, print_stream=buf,
    )
    assert rc == 0
    out = buf.getvalue()
    assert "r\t255" in out
    assert "g\t0" in out


def test_dump_unknown_target(session_dir, injected_rest, monkeypatch):
    monkeypatch.setenv("GPA_SESSION", str(session_dir))
    buf = io.StringIO()
    rc = dump_cmd.run(
        what="bogus", frame=1, client=injected_rest, print_stream=buf,
    )
    assert rc == 1


# --------------------------------------------------------------------------- #
# Removed subtargets — anti-regression for the +$0.39/pair dump pattern
# (see docs/superpowers/specs/2026-04-27-bidirectional-narrow-queries-design.md).
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "subtarget,redirect_substr",
    [
        ("drawcall", "explain-draw"),
        ("shader", "explain-draw"),
        ("textures", "explain-draw"),
        ("attachments", "/api/v1/frames/"),
    ],
)
def test_dump_removed_subtarget_shows_redirect(
    subtarget, redirect_substr,
    session_dir, injected_rest, monkeypatch, capsys,
):
    """Each removed subtarget must fail with exit-3 + a concrete redirect.

    Silently-broken aliases would re-introduce the dump-pattern regression
    we removed; loud failure with a pointer to the narrow command keeps the
    agent on-rails.
    """
    monkeypatch.setenv("GPA_SESSION", str(session_dir))
    buf = io.StringIO()
    rc = dump_cmd.run(
        what=subtarget, frame=1,
        client=injected_rest, print_stream=buf,
    )
    assert rc == 3
    captured = capsys.readouterr()
    assert subtarget in captured.err
    assert "removed" in captured.err.lower()
    assert redirect_substr in captured.err
    # Nothing should have been written to stdout — the redirect is on stderr.
    assert buf.getvalue() == ""


@pytest.mark.parametrize(
    "argv",
    [
        # Bare form (no positional id) — exercised pre-fix too.
        ["dump", "drawcall"],
        # Natural form with trailing positional id — used to die with exit 2
        # (argparse "unrecognized arguments") before the trailing-positional
        # absorber was added. Must now reach the redirect handler too.
        ["dump", "drawcall", "0"],
    ],
)
def test_dump_removed_subtarget_via_full_cli(argv, session_dir, monkeypatch, capsys):
    """Regression guard: full CLI parser must route ``dump drawcall [0]``
    through the redirect (exit 3), not argparse's exit 2."""
    from gpa.cli.main import main as cli_main

    monkeypatch.setenv("GPA_SESSION", str(session_dir))
    rc = cli_main(argv)
    assert rc == 3
    err = capsys.readouterr().err
    assert "drawcall" in err
    assert "removed" in err.lower()
    assert "explain-draw" in err


# --------------------------------------------------------------------------- #
# Kept subtargets via FULL CLI — anti-regression for argparse.REMAINDER which
# greedily ate flags (`--x 10 --y 20`), silently breaking ``dump pixel`` etc.
# These tests must go through the full argparse path (`cli_main(argv)`); the
# direct ``dump_cmd.run(...)`` tests above bypass argparse entirely and so
# would not have caught the regression.
# --------------------------------------------------------------------------- #


def test_dump_pixel_via_full_cli_parses_xy(session_dir, monkeypatch):
    """``gpa dump pixel --x 10 --y 20 --frame 1`` must reach the handler with
    x=10, y=20, frame=1 — not all-None (which is what REMAINDER produced)."""
    from gpa.cli import main as cli_main_mod

    monkeypatch.setenv("GPA_SESSION", str(session_dir))
    captured = {}

    def fake_run(**kwargs):
        captured.update(kwargs)
        return 0

    monkeypatch.setattr(cli_main_mod.dump_cmd, "run", fake_run)
    rc = cli_main_mod.main(["dump", "pixel", "--x", "10", "--y", "20", "--frame", "1"])
    assert rc == 0
    assert captured["what"] == "pixel"
    assert captured["x"] == 10
    assert captured["y"] == 20
    assert captured["frame"] == 1
    assert captured["fmt"] == "plain"


def test_dump_frame_via_full_cli_parses_frame(session_dir, monkeypatch):
    """``gpa dump frame --frame 7`` must reach the handler with frame=7."""
    from gpa.cli import main as cli_main_mod

    monkeypatch.setenv("GPA_SESSION", str(session_dir))
    captured = {}

    def fake_run(**kwargs):
        captured.update(kwargs)
        return 0

    monkeypatch.setattr(cli_main_mod.dump_cmd, "run", fake_run)
    rc = cli_main_mod.main(["dump", "frame", "--frame", "7"])
    assert rc == 0
    assert captured["what"] == "frame"
    assert captured["frame"] == 7


def test_dump_drawcalls_via_full_cli_parses_format(session_dir, monkeypatch):
    """``gpa dump drawcalls --format json`` must reach the handler with
    fmt='json' (REMAINDER would have absorbed ``--format json``)."""
    from gpa.cli import main as cli_main_mod

    monkeypatch.setenv("GPA_SESSION", str(session_dir))
    captured = {}

    def fake_run(**kwargs):
        captured.update(kwargs)
        return 0

    monkeypatch.setattr(cli_main_mod.dump_cmd, "run", fake_run)
    rc = cli_main_mod.main(["dump", "drawcalls", "--format", "json"])
    assert rc == 0
    assert captured["what"] == "drawcalls"
    assert captured["fmt"] == "json"


# --------------------------------------------------------------------------- #
# frames
# --------------------------------------------------------------------------- #


def test_frames_falls_back_to_latest_when_no_list_route(
    session_dir, injected_rest, monkeypatch
):
    monkeypatch.setenv("GPA_SESSION", str(session_dir))
    buf = io.StringIO()
    rc = frames_cmd.run(client=injected_rest, print_stream=buf)
    assert rc == 0
    # The app has no ``/api/v1/frames`` list route so we fall back to current.
    out = buf.getvalue().strip()
    assert out == "1"


