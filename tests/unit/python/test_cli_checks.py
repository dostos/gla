"""Per-check unit tests with a hand-rolled fake REST client."""

from __future__ import annotations

from typing import Any, Dict

import pytest

from gpa.cli.checks import (
    all_checks,
    get_check,
    known_names,
)
from gpa.cli.checks.empty_capture import EmptyCaptureCheck
from gpa.cli.checks.feedback_loops import FeedbackLoopsCheck
from gpa.cli.checks.missing_clear import MissingClearCheck
from gpa.cli.checks.nan_uniforms import NanUniformsCheck


# --------------------------------------------------------------------------- #
# Fake REST client — dict-backed, no HTTP at all.
# --------------------------------------------------------------------------- #


class FakeClient:
    """Maps a path → response dict.  Missing paths raise."""

    def __init__(self, responses: Dict[str, Any]):
        self._responses = responses
        self.calls: list[str] = []

    def get_json(self, path: str) -> Any:
        self.calls.append(path)
        if path not in self._responses:
            raise KeyError(f"No fake response for {path!r}")
        value = self._responses[path]
        if isinstance(value, Exception):
            raise value
        return value


# --------------------------------------------------------------------------- #
# Registry
# --------------------------------------------------------------------------- #


def test_builtin_checks_registered():
    names = known_names()
    assert "empty-capture" in names
    assert "feedback-loops" in names
    assert "nan-uniforms" in names
    assert "missing-clear" in names


def test_get_check_returns_instance():
    c = get_check("empty-capture")
    assert isinstance(c, EmptyCaptureCheck)
    assert get_check("does-not-exist") is None


def test_all_checks_ordered():
    instances = all_checks()
    names = [c.name for c in instances]
    # Order mirrors registration order in checks/__init__.py
    assert names == ["empty-capture", "feedback-loops", "nan-uniforms",
                     "missing-clear"]


# --------------------------------------------------------------------------- #
# empty-capture
# --------------------------------------------------------------------------- #


def test_empty_capture_warns_on_zero_draws():
    client = FakeClient({
        "/api/v1/frames/2/overview": {"draw_call_count": 0, "clear_count": 0},
    })
    result = EmptyCaptureCheck().run(client, frame_id=2)
    assert result.status == "warn"
    assert len(result.findings) == 1


def test_empty_capture_ok_when_draws_present():
    client = FakeClient({
        "/api/v1/frames/2/overview": {"draw_call_count": 3, "clear_count": 1},
    })
    result = EmptyCaptureCheck().run(client, frame_id=2)
    assert result.status == "ok"
    assert result.findings == []


# --------------------------------------------------------------------------- #
# feedback-loops
# --------------------------------------------------------------------------- #


def test_feedback_loops_warns_on_texture_collision():
    client = FakeClient({
        "/api/v1/frames/1/drawcalls?limit=200&offset=0": {
            "items": [{"id": 3}, {"id": 4}],
            "total": 2,
        },
        "/api/v1/frames/1/drawcalls/3/feedback-loops": {
            "fbo_color_attachment_tex": 7,
            "textures": [
                {"slot": 0, "texture_id": 7, "width": 512, "height": 512},
            ],
        },
        "/api/v1/frames/1/drawcalls/4/feedback-loops": {
            "fbo_color_attachment_tex": 0,
            "textures": [],
        },
    })
    result = FeedbackLoopsCheck().run(client, frame_id=1)
    assert result.status == "warn"
    assert len(result.findings) == 1
    f = result.findings[0]
    assert "draw call 3" in f.summary
    assert f.detail["slot"] == 0
    assert f.detail["texture_id"] == 7


def test_feedback_loops_ok_when_no_collision():
    client = FakeClient({
        "/api/v1/frames/1/drawcalls?limit=200&offset=0": {
            "items": [{"id": 0}],
            "total": 1,
        },
        "/api/v1/frames/1/drawcalls/0/feedback-loops": {
            "fbo_color_attachment_tex": 0,
            "textures": [],
        },
    })
    result = FeedbackLoopsCheck().run(client, frame_id=1)
    assert result.status == "ok"


def test_feedback_loops_with_dc_filter():
    client = FakeClient({
        "/api/v1/frames/1/drawcalls/5/feedback-loops": {
            "fbo_color_attachment_tex": 7,
            "textures": [{"slot": 2, "texture_id": 7}],
        },
    })
    result = FeedbackLoopsCheck().run(client, frame_id=1, dc_id=5)
    assert result.status == "warn"
    # Should NOT have listed the drawcalls page when dc_id is given.
    assert "/drawcalls?limit=" not in " ".join(client.calls)


# --------------------------------------------------------------------------- #
# nan-uniforms
# --------------------------------------------------------------------------- #


def test_nan_uniforms_warns():
    client = FakeClient({
        "/api/v1/frames/2/drawcalls?limit=200&offset=0": {
            "items": [{"id": 0}], "total": 1,
        },
        "/api/v1/frames/2/drawcalls/0/nan-uniforms": {
            "has_nan_uniforms": True,
            "nan_uniforms": [
                {"name": "uRoughness", "type": 0x8B51, "bad_components": [0]},
            ],
        },
    })
    result = NanUniformsCheck().run(client, frame_id=2)
    assert result.status == "warn"
    assert "uRoughness" in result.findings[0].summary
    assert "0x8B51" in result.findings[0].summary


def test_nan_uniforms_ok():
    client = FakeClient({
        "/api/v1/frames/2/drawcalls?limit=200&offset=0": {
            "items": [{"id": 0}], "total": 1,
        },
        "/api/v1/frames/2/drawcalls/0/nan-uniforms": {
            "has_nan_uniforms": False, "nan_uniforms": [],
        },
    })
    result = NanUniformsCheck().run(client, frame_id=2)
    assert result.status == "ok"


# --------------------------------------------------------------------------- #
# missing-clear
# --------------------------------------------------------------------------- #


def test_missing_clear_warns():
    client = FakeClient({
        "/api/v1/frames/1/overview": {
            "draw_call_count": 3, "clear_count": 0,
        },
    })
    result = MissingClearCheck().run(client, frame_id=1)
    assert result.status == "warn"


def test_missing_clear_ok_when_clears_present():
    client = FakeClient({
        "/api/v1/frames/1/overview": {
            "draw_call_count": 3, "clear_count": 1,
        },
    })
    result = MissingClearCheck().run(client, frame_id=1)
    assert result.status == "ok"


def test_missing_clear_ok_when_no_draws():
    # 0 draws ∧ 0 clears should NOT trigger this warning — empty-capture covers it.
    client = FakeClient({
        "/api/v1/frames/1/overview": {
            "draw_call_count": 0, "clear_count": 0,
        },
    })
    result = MissingClearCheck().run(client, frame_id=1)
    assert result.status == "ok"
