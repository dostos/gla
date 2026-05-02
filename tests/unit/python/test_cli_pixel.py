"""Tests for ``gpa pixel`` CLI namespace.

Uses a _CapturingClient that records (method, path) tuples so we can
assert the right REST path is constructed, without spinning up a real HTTP
server.  The run_* helpers in pixel.py accept an injected ``client``
kwarg so tests never touch argparse or Session discovery.
"""
from __future__ import annotations

import io
import json
from typing import Any, Dict, Optional

import pytest

from gpa.cli.commands import pixel as pixel_mod


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


# Fixed frame_id returned by the "current" overview fallback.
_CURRENT_FID = 7
_CURRENT_OV_PATH = "/api/v1/frames/current/overview"


def _client(**extra_paths) -> _CapturingClient:
    """Return a client that resolves frame=7 via the current-overview fallback."""
    responses: Dict[str, Any] = {_CURRENT_OV_PATH: {"frame_id": _CURRENT_FID}}
    responses.update(extra_paths)
    return _CapturingClient(responses)


# --------------------------------------------------------------------------- #
# pixel get
# --------------------------------------------------------------------------- #


def test_get_hits_correct_url(monkeypatch):
    monkeypatch.delenv("GPA_FRAME_ID", raising=False)
    client = _client()
    buf = io.StringIO()
    rc = pixel_mod.run_get(client=client, frame=None, x=100, y=200, print_stream=buf)
    assert rc == 0
    assert ("GET", f"/api/v1/frames/{_CURRENT_FID}/pixel/100/200") in client.calls


def test_get_output_is_json_passthrough(monkeypatch):
    monkeypatch.delenv("GPA_FRAME_ID", raising=False)
    payload = {"r": 255, "g": 0, "b": 0, "a": 255}
    path = f"/api/v1/frames/{_CURRENT_FID}/pixel/10/20"
    client = _client(**{path: payload})
    buf = io.StringIO()
    pixel_mod.run_get(client=client, frame=None, x=10, y=20, print_stream=buf)
    parsed = json.loads(buf.getvalue())
    assert parsed == payload


# --------------------------------------------------------------------------- #
# pixel explain
# --------------------------------------------------------------------------- #


def test_explain_hits_correct_url(monkeypatch):
    monkeypatch.delenv("GPA_FRAME_ID", raising=False)
    client = _client()
    buf = io.StringIO()
    rc = pixel_mod.run_explain(client=client, frame=None, x=50, y=75, print_stream=buf)
    assert rc == 0
    assert ("GET", f"/api/v1/frames/{_CURRENT_FID}/explain-pixel?x=50&y=75") in client.calls


# --------------------------------------------------------------------------- #
# --frame env-var fallback
# --------------------------------------------------------------------------- #


def test_get_frame_env_fallback(monkeypatch):
    monkeypatch.setenv("GPA_FRAME_ID", "3")
    path = "/api/v1/frames/3/pixel/1/2"
    client = _client(**{path: {"r": 0, "g": 0, "b": 0, "a": 255}})
    buf = io.StringIO()
    rc = pixel_mod.run_get(client=client, frame=None, x=1, y=2, print_stream=buf)
    assert rc == 0
    assert ("GET", path) in client.calls
