"""Tests for ``gpa control`` CLI namespace."""
from __future__ import annotations

import io
import json
from typing import Any, Dict, Optional

import pytest

from gpa.cli.commands import control as control_mod


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
        self.calls.append(("POST", path))
        return self._responses.get(path, {"ok": True})


def _client(**extra_paths) -> _CapturingClient:
    responses: Dict[str, Any] = {}
    responses.update(extra_paths)
    return _CapturingClient(responses)


# --------------------------------------------------------------------------- #
# control status
# --------------------------------------------------------------------------- #


def test_status_hits_correct_url():
    payload = {"running": True}
    client = _client(**{"/api/v1/control/status": payload})
    buf = io.StringIO()
    rc = control_mod.run_status(client=client, print_stream=buf)
    assert rc == 0
    assert ("GET", "/api/v1/control/status") in client.calls
    assert json.loads(buf.getvalue()) == payload


# --------------------------------------------------------------------------- #
# control pause
# --------------------------------------------------------------------------- #


def test_pause_hits_correct_url():
    client = _client()
    buf = io.StringIO()
    rc = control_mod.run_pause(client=client, print_stream=buf)
    assert rc == 0
    assert ("POST", "/api/v1/control/pause") in client.calls


# --------------------------------------------------------------------------- #
# control resume
# --------------------------------------------------------------------------- #


def test_resume_hits_correct_url():
    client = _client()
    buf = io.StringIO()
    rc = control_mod.run_resume(client=client, print_stream=buf)
    assert rc == 0
    assert ("POST", "/api/v1/control/resume") in client.calls


# --------------------------------------------------------------------------- #
# control step
# --------------------------------------------------------------------------- #


def test_step_hits_correct_url():
    client = _client()
    buf = io.StringIO()
    rc = control_mod.run_step(client=client, print_stream=buf)
    assert rc == 0
    assert ("POST", "/api/v1/control/step") in client.calls
