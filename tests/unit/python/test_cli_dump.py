"""Tests for ``gpa dump`` output formats and ``gpa frames``/``annotate``."""

from __future__ import annotations

import io
import json
from pathlib import Path

import pytest

from gpa.cli.commands import annotate as annotate_cmd
from gpa.cli.commands import annotations as annotations_cmd
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
        ("attachments", "check-config"),
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
        what=subtarget, frame=1, dc=0,
        client=injected_rest, print_stream=buf,
    )
    assert rc == 3
    captured = capsys.readouterr()
    assert subtarget in captured.err
    assert "removed" in captured.err.lower()
    assert redirect_substr in captured.err
    # Nothing should have been written to stdout — the redirect is on stderr.
    assert buf.getvalue() == ""


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


# --------------------------------------------------------------------------- #
# annotate / annotations
# --------------------------------------------------------------------------- #


def test_annotate_and_get_roundtrip(session_dir, injected_rest, monkeypatch):
    monkeypatch.setenv("GPA_SESSION", str(session_dir))

    post_buf = io.StringIO()
    rc = annotate_cmd.run(
        frame=1, pairs=["scene=main", "count=7"],
        client=injected_rest, print_stream=post_buf,
    )
    assert rc == 0
    posted = json.loads(post_buf.getvalue())
    assert posted.get("ok") is True

    get_buf = io.StringIO()
    rc2 = annotations_cmd.run(
        frame=1, client=injected_rest, print_stream=get_buf,
    )
    assert rc2 == 0
    stored = json.loads(get_buf.getvalue())
    assert stored == {"scene": "main", "count": 7}
