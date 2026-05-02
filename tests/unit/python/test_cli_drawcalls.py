"""Tests for ``gpa drawcalls`` CLI namespace.

Uses a _CapturingClient that records (method, path, body?) tuples so we can
assert the right REST path is constructed, without spinning up a real HTTP
server.  The run_* helpers in drawcalls.py accept an injected ``client``
kwarg so tests never touch argparse or Session discovery.
"""
from __future__ import annotations

import io
import json
import sys
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

import pytest

from gpa.cli.commands import drawcalls as dc_mod


# --------------------------------------------------------------------------- #
# Fake client
# --------------------------------------------------------------------------- #


class _CapturingClient:
    """Records every REST call and returns a canned response."""

    def __init__(self, responses: Optional[Dict[str, Any]] = None):
        self._responses: Dict[str, Any] = responses or {}
        self.calls: list = []

    def get_json(self, path: str):
        self.calls.append(("GET", path))
        return self._responses.get(path, {"ok": True})

    def post_json(self, path: str, body: Any):
        self.calls.append(("POST", path, body))
        return self._responses.get(path, {"ok": True})


# Fixed frame_id returned by the "current" overview fallback.
_CURRENT_FID = 7
_CURRENT_OV_PATH = "/api/v1/frames/current/overview"


def _client(**extra_paths) -> _CapturingClient:
    """Return a client that resolves frame=7 via the current-overview fallback."""
    responses: Dict[str, Any] = {_CURRENT_OV_PATH: {"frame_id": _CURRENT_FID}}
    responses.update(extra_paths)
    return _CapturingClient(responses)


# --------------------------------------------------------------------------- #
# list
# --------------------------------------------------------------------------- #


def test_list_hits_correct_url(monkeypatch):
    monkeypatch.delenv("GPA_FRAME_ID", raising=False)
    client = _client()
    buf = io.StringIO()
    rc = dc_mod.run_list(client=client, frame=None, print_stream=buf)
    assert rc == 0
    assert any(
        call[0] == "GET" and call[1] == f"/api/v1/frames/{_CURRENT_FID}/drawcalls"
        for call in client.calls
    )


def test_list_with_explicit_frame(monkeypatch):
    monkeypatch.delenv("GPA_FRAME_ID", raising=False)
    client = _client()
    buf = io.StringIO()
    rc = dc_mod.run_list(client=client, frame="3", print_stream=buf)
    assert rc == 0
    assert ("GET", "/api/v1/frames/3/drawcalls") in client.calls


def test_list_with_limit_and_offset(monkeypatch):
    monkeypatch.delenv("GPA_FRAME_ID", raising=False)
    client = _client()
    buf = io.StringIO()
    rc = dc_mod.run_list(client=client, frame="5", limit=10, offset=20, print_stream=buf)
    assert rc == 0
    assert ("GET", "/api/v1/frames/5/drawcalls?limit=10&offset=20") in client.calls


def test_list_output_is_json(monkeypatch):
    monkeypatch.delenv("GPA_FRAME_ID", raising=False)
    payload = [{"id": 0, "primitive_type": "TRIANGLES"}]
    client = _client(**{f"/api/v1/frames/{_CURRENT_FID}/drawcalls": payload})
    buf = io.StringIO()
    dc_mod.run_list(client=client, frame=None, print_stream=buf)
    # Must be valid JSON.
    parsed = json.loads(buf.getvalue())
    assert parsed == payload


# --------------------------------------------------------------------------- #
# get
# --------------------------------------------------------------------------- #


def test_get_hits_correct_url(monkeypatch):
    monkeypatch.delenv("GPA_FRAME_ID", raising=False)
    client = _client()
    buf = io.StringIO()
    rc = dc_mod.run_get(client=client, frame=None, dc=42, print_stream=buf)
    assert rc == 0
    assert ("GET", f"/api/v1/frames/{_CURRENT_FID}/drawcalls/42") in client.calls


# --------------------------------------------------------------------------- #
# shader
# --------------------------------------------------------------------------- #


def test_shader_hits_correct_url(monkeypatch):
    monkeypatch.delenv("GPA_FRAME_ID", raising=False)
    client = _client()
    buf = io.StringIO()
    rc = dc_mod.run_shader(client=client, frame=None, dc=3, print_stream=buf)
    assert rc == 0
    assert ("GET", f"/api/v1/frames/{_CURRENT_FID}/drawcalls/3/shader") in client.calls


# --------------------------------------------------------------------------- #
# textures
# --------------------------------------------------------------------------- #


def test_textures_hits_correct_url(monkeypatch):
    monkeypatch.delenv("GPA_FRAME_ID", raising=False)
    client = _client()
    buf = io.StringIO()
    rc = dc_mod.run_textures(client=client, frame=None, dc=5, print_stream=buf)
    assert rc == 0
    assert ("GET", f"/api/v1/frames/{_CURRENT_FID}/drawcalls/5/textures") in client.calls


# --------------------------------------------------------------------------- #
# vertices
# --------------------------------------------------------------------------- #


def test_vertices_hits_correct_url(monkeypatch):
    monkeypatch.delenv("GPA_FRAME_ID", raising=False)
    client = _client()
    buf = io.StringIO()
    rc = dc_mod.run_vertices(client=client, frame=None, dc=2, print_stream=buf)
    assert rc == 0
    assert ("GET", f"/api/v1/frames/{_CURRENT_FID}/drawcalls/2/vertices") in client.calls


# --------------------------------------------------------------------------- #
# attachments
# --------------------------------------------------------------------------- #


def test_attachments_hits_correct_url(monkeypatch):
    monkeypatch.delenv("GPA_FRAME_ID", raising=False)
    client = _client()
    buf = io.StringIO()
    rc = dc_mod.run_attachments(client=client, frame=None, dc=8, print_stream=buf)
    assert rc == 0
    assert ("GET", f"/api/v1/frames/{_CURRENT_FID}/drawcalls/8/attachments") in client.calls


# --------------------------------------------------------------------------- #
# nan-uniforms
# --------------------------------------------------------------------------- #


def test_nan_uniforms_hits_correct_url(monkeypatch):
    monkeypatch.delenv("GPA_FRAME_ID", raising=False)
    client = _client()
    buf = io.StringIO()
    rc = dc_mod.run_nan_uniforms(client=client, frame=None, dc=11, print_stream=buf)
    assert rc == 0
    assert ("GET", f"/api/v1/frames/{_CURRENT_FID}/drawcalls/11/nan-uniforms") in client.calls


# --------------------------------------------------------------------------- #
# feedback-loops
# --------------------------------------------------------------------------- #


def test_feedback_loops_hits_correct_url(monkeypatch):
    monkeypatch.delenv("GPA_FRAME_ID", raising=False)
    client = _client()
    buf = io.StringIO()
    rc = dc_mod.run_feedback_loops(client=client, frame=None, dc=6, print_stream=buf)
    assert rc == 0
    assert ("GET", f"/api/v1/frames/{_CURRENT_FID}/drawcalls/6/feedback-loops") in client.calls


# --------------------------------------------------------------------------- #
# explain  (uses /draws/ not /drawcalls/)
# --------------------------------------------------------------------------- #


def test_explain_hits_correct_url(monkeypatch):
    monkeypatch.delenv("GPA_FRAME_ID", raising=False)
    client = _client()
    buf = io.StringIO()
    rc = dc_mod.run_explain(client=client, frame=None, dc=9, print_stream=buf)
    assert rc == 0
    assert ("GET", f"/api/v1/frames/{_CURRENT_FID}/draws/9/explain") in client.calls


# --------------------------------------------------------------------------- #
# diff  (uses /draws/diff?  not /drawcalls/)
# --------------------------------------------------------------------------- #


def test_diff_hits_correct_url_default_scope(monkeypatch):
    monkeypatch.delenv("GPA_FRAME_ID", raising=False)
    client = _client()
    buf = io.StringIO()
    rc = dc_mod.run_diff(client=client, frame=None, a=0, b=1, print_stream=buf)
    assert rc == 0
    assert ("GET", f"/api/v1/frames/{_CURRENT_FID}/draws/diff?a=0&b=1&scope=all") in client.calls


def test_diff_with_explicit_scope(monkeypatch):
    monkeypatch.delenv("GPA_FRAME_ID", raising=False)
    client = _client()
    buf = io.StringIO()
    rc = dc_mod.run_diff(client=client, frame="2", a=3, b=4, scope="uniforms", print_stream=buf)
    assert rc == 0
    assert ("GET", "/api/v1/frames/2/draws/diff?a=3&b=4&scope=uniforms") in client.calls


# --------------------------------------------------------------------------- #
# sources get / set
# --------------------------------------------------------------------------- #


def test_sources_get_hits_correct_url(monkeypatch):
    monkeypatch.delenv("GPA_FRAME_ID", raising=False)
    client = _client()
    buf = io.StringIO()
    rc = dc_mod.run_sources_get(client=client, frame=None, dc=7, print_stream=buf)
    assert rc == 0
    assert ("GET", f"/api/v1/frames/{_CURRENT_FID}/drawcalls/7/sources") in client.calls


def test_sources_set_body_json(monkeypatch):
    monkeypatch.delenv("GPA_FRAME_ID", raising=False)
    client = _client()
    buf = io.StringIO()
    body = {"x": 1}
    rc = dc_mod.run_sources_set(
        client=client, frame=None, dc=7,
        body_json=json.dumps(body), file_path=None, print_stream=buf,
    )
    assert rc == 0
    # Should have POSTed to the right path with the right body.
    assert any(
        call[0] == "POST"
        and call[1] == f"/api/v1/frames/{_CURRENT_FID}/drawcalls/7/sources"
        and call[2] == body
        for call in client.calls
    )


def test_sources_set_file(monkeypatch, tmp_path):
    monkeypatch.delenv("GPA_FRAME_ID", raising=False)
    body = {"vertex_src": "void main() {}"}
    f = tmp_path / "src.json"
    f.write_text(json.dumps(body))
    client = _client()
    buf = io.StringIO()
    rc = dc_mod.run_sources_set(
        client=client, frame=None, dc=4,
        body_json=None, file_path=str(f), print_stream=buf,
    )
    assert rc == 0
    assert any(
        call[0] == "POST"
        and call[1] == f"/api/v1/frames/{_CURRENT_FID}/drawcalls/4/sources"
        and call[2] == body
        for call in client.calls
    )


# --------------------------------------------------------------------------- #
# GPA_FRAME_ID env default
# --------------------------------------------------------------------------- #


def test_frame_defaults_from_env(monkeypatch):
    monkeypatch.setenv("GPA_FRAME_ID", "99")
    client = _CapturingClient({"ok": True})
    buf = io.StringIO()
    rc = dc_mod.run_get(client=client, frame=None, dc=1, print_stream=buf)
    assert rc == 0
    assert ("GET", "/api/v1/frames/99/drawcalls/1") in client.calls


# --------------------------------------------------------------------------- #
# Deprecation warnings emitted for legacy aliases
# --------------------------------------------------------------------------- #


def test_explain_draw_deprecation_warning(monkeypatch, capsys):
    """gpa explain-draw should emit a deprecation warning to stderr."""
    from gpa.cli.main import main as cli_main

    monkeypatch.setenv("GPA_SESSION", "nonexistent_session_path_xyz")
    # We just need the warning; the command itself will fail (no session).
    cli_main(["explain-draw", "0"])
    err = capsys.readouterr().err
    assert "deprecated" in err
    assert "gpa drawcalls explain" in err


def test_diff_draws_deprecation_warning(monkeypatch, capsys):
    """gpa diff-draws should emit a deprecation warning to stderr."""
    from gpa.cli.main import main as cli_main

    monkeypatch.setenv("GPA_SESSION", "nonexistent_session_path_xyz")
    cli_main(["diff-draws", "0", "1"])
    err = capsys.readouterr().err
    assert "deprecated" in err
    assert "gpa drawcalls diff" in err
