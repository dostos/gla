"""Tests for ``gpa annotations`` CLI namespace."""
from __future__ import annotations

import io
import json
from pathlib import Path
from typing import Any, Dict, Optional

import pytest

from gpa.cli.commands import annotations as ann_mod


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


_CURRENT_FID = 7
_CURRENT_OV_PATH = "/api/v1/frames/current/overview"


def _client(**extra_paths) -> _CapturingClient:
    responses: Dict[str, Any] = {_CURRENT_OV_PATH: {"frame_id": _CURRENT_FID}}
    responses.update(extra_paths)
    return _CapturingClient(responses)


# --------------------------------------------------------------------------- #
# annotations list — smoke
# --------------------------------------------------------------------------- #


def test_list_hits_correct_url(monkeypatch):
    monkeypatch.delenv("GPA_FRAME_ID", raising=False)
    client = _client()
    buf = io.StringIO()
    rc = ann_mod.run_list(client=client, frame=None, print_stream=buf)
    assert rc == 0
    assert ("GET", f"/api/v1/frames/{_CURRENT_FID}/annotations") in client.calls


def test_list_output_is_json_passthrough(monkeypatch):
    monkeypatch.delenv("GPA_FRAME_ID", raising=False)
    payload = {"note": "some annotation"}
    path = f"/api/v1/frames/{_CURRENT_FID}/annotations"
    client = _client(**{path: payload})
    buf = io.StringIO()
    ann_mod.run_list(client=client, frame=None, print_stream=buf)
    assert json.loads(buf.getvalue()) == payload


# --------------------------------------------------------------------------- #
# annotations add — via --body-json
# --------------------------------------------------------------------------- #


def test_add_via_body_json(monkeypatch):
    monkeypatch.delenv("GPA_FRAME_ID", raising=False)
    client = _client()
    buf = io.StringIO()
    rc = ann_mod.run_add(
        client=client, frame=None, body_json='{"x": 1}', print_stream=buf,
    )
    assert rc == 0
    path = f"/api/v1/frames/{_CURRENT_FID}/annotations"
    assert any(c[0] == "POST" and c[1] == path and c[2] == {"x": 1}
               for c in client.calls)


# --------------------------------------------------------------------------- #
# annotations add — via --file
# --------------------------------------------------------------------------- #


def test_add_via_file(monkeypatch, tmp_path):
    monkeypatch.delenv("GPA_FRAME_ID", raising=False)
    data = {"key": "value"}
    json_file = tmp_path / "ann.json"
    json_file.write_text(json.dumps(data))

    client = _client()
    buf = io.StringIO()
    rc = ann_mod.run_add(
        client=client, frame=None, file_path=str(json_file), print_stream=buf,
    )
    assert rc == 0
    path = f"/api/v1/frames/{_CURRENT_FID}/annotations"
    assert any(c[0] == "POST" and c[1] == path and c[2] == data
               for c in client.calls)


# --------------------------------------------------------------------------- #
# annotations add — invalid JSON → exit 2
# --------------------------------------------------------------------------- #


def test_add_invalid_body_json_returns_2(monkeypatch):
    monkeypatch.delenv("GPA_FRAME_ID", raising=False)
    client = _client()
    buf = io.StringIO()
    rc = ann_mod.run_add(
        client=client, frame=None, body_json="NOT JSON", print_stream=buf,
    )
    assert rc == 2
