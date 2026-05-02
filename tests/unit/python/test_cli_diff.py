"""Tests for ``gpa diff`` CLI namespace."""
from __future__ import annotations

import io
import json
from typing import Any, Dict, Optional

import pytest

from gpa.cli.commands import diff as diff_mod


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


def _client(**extra_paths) -> _CapturingClient:
    responses: Dict[str, Any] = {}
    responses.update(extra_paths)
    return _CapturingClient(responses)


# --------------------------------------------------------------------------- #
# diff frames — smoke test (default depth)
# --------------------------------------------------------------------------- #


def test_diff_frames_default_depth():
    payload = {"frame_id_a": 3, "frame_id_b": 5, "summary": {}}
    path = "/api/v1/diff/3/5?depth=summary"
    client = _client(**{path: payload})
    buf = io.StringIO()
    rc = diff_mod.run_frames(client=client, a=3, b=5, print_stream=buf)
    assert rc == 0
    assert ("GET", path) in client.calls
    assert json.loads(buf.getvalue()) == payload


# --------------------------------------------------------------------------- #
# diff frames — explicit depth param
# --------------------------------------------------------------------------- #


def test_diff_frames_depth_drawcalls():
    path = "/api/v1/diff/1/2?depth=drawcalls"
    client = _client(**{path: {"draw_call_diffs": []}})
    buf = io.StringIO()
    rc = diff_mod.run_frames(client=client, a=1, b=2, depth="drawcalls", print_stream=buf)
    assert rc == 0
    assert ("GET", path) in client.calls


def test_diff_frames_depth_pixels():
    path = "/api/v1/diff/4/7?depth=pixels"
    client = _client(**{path: {"pixel_diffs": []}})
    buf = io.StringIO()
    rc = diff_mod.run_frames(client=client, a=4, b=7, depth="pixels", print_stream=buf)
    assert rc == 0
    assert ("GET", path) in client.calls


# --------------------------------------------------------------------------- #
# no session → exit 2
# --------------------------------------------------------------------------- #


def test_diff_frames_no_session(monkeypatch):
    monkeypatch.setenv("GPA_SESSION", "")
    import gpa.cli.session as _sess
    monkeypatch.setattr(_sess.Session, "discover", staticmethod(lambda **kw: None))
    buf = io.StringIO()
    rc = diff_mod.run_frames(a=1, b=2, print_stream=buf)
    assert rc == 2
