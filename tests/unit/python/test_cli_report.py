"""Integration tests for ``gpa report`` / ``gpa check`` against a live TestClient.

We plug Starlette's ``TestClient`` into ``RestClient`` via ``http_callable``
so we exercise the full FastAPI app without touching the network.
"""

from __future__ import annotations

import io
from pathlib import Path

import pytest

from gpa.cli.commands import check as check_cmd
from gpa.cli.commands import report as report_cmd
from gpa.cli.rest_client import RestClient, RestError
from gpa.cli.session import Session


@pytest.fixture
def session_dir(tmp_path) -> Path:
    """Minimal on-disk session (token + port + shm-name); no engine."""
    d = tmp_path / "sess"
    d.mkdir()
    (d / "token").write_text("test-token")
    (d / "port").write_text("18080")
    (d / "shm-name").write_text("/gpa-test")
    return d


@pytest.fixture
def injected_rest(client):  # uses ``client`` from conftest.py
    """RestClient that routes everything through the TestClient."""

    def http_callable(method, path, headers, body=None):
        if method == "GET":
            resp = client.get(path, headers=headers)
        elif method == "POST":
            resp = client.post(path, headers=headers, content=body)
        else:  # pragma: no cover
            raise AssertionError(f"unsupported method {method}")
        if resp.status_code >= 400:
            raise RestError(
                f"{method} {path} → HTTP {resp.status_code}",
                status=resp.status_code,
            )
        # TestClient returns bytes for empty bodies; handle both.
        if not resp.content:
            return None
        return resp.json()

    return RestClient(token="test-token", http_callable=http_callable)


# --------------------------------------------------------------------------- #
# report plain text
# --------------------------------------------------------------------------- #


def test_report_plain_text_against_live_app(
    session_dir, injected_rest, monkeypatch
):
    # Point discover at our fake session dir.
    monkeypatch.setenv("GPA_SESSION", str(session_dir))
    monkeypatch.delenv("NO_COLOR", raising=False)

    buf = io.StringIO()
    rc = report_cmd.run(
        frame=1, client=injected_rest, print_stream=buf
    )
    out = buf.getvalue()

    # Mock frame has 42 draw calls, a feedback loop (tex 7 ↔ attachment 7),
    # a NaN uniform (`uBad` component 1), and no clear (clear_count=0).
    assert "gpa report — frame 1" in out
    assert "42 draw calls captured" in out
    assert "feedback-loops" in out
    assert "nan-uniforms" in out
    assert "missing-clear" in out
    # empty-capture should pass.
    assert "empty-capture: ok" in out
    # Exit code 3 because warnings were found.
    assert rc == 3


def test_report_json(session_dir, injected_rest, monkeypatch):
    monkeypatch.setenv("GPA_SESSION", str(session_dir))
    buf = io.StringIO()
    rc = report_cmd.run(
        frame=1, json_output=True, client=injected_rest, print_stream=buf
    )
    import json as _json

    data = _json.loads(buf.getvalue())
    assert data["frame"] == 1
    assert data["session"] == str(session_dir)
    assert any(c["name"] == "feedback-loops" for c in data["checks"])
    assert data["warning_count"] >= 1
    assert rc == 3


def test_report_only_filter(session_dir, injected_rest, monkeypatch):
    monkeypatch.setenv("GPA_SESSION", str(session_dir))
    buf = io.StringIO()
    report_cmd.run(
        frame=1, only=["empty-capture"],
        client=injected_rest, print_stream=buf,
    )
    out = buf.getvalue()
    assert "empty-capture" in out
    assert "feedback-loops" not in out


def test_report_skip_filter(session_dir, injected_rest, monkeypatch):
    monkeypatch.setenv("GPA_SESSION", str(session_dir))
    buf = io.StringIO()
    report_cmd.run(
        frame=1, skip=["feedback-loops", "nan-uniforms"],
        client=injected_rest, print_stream=buf,
    )
    out = buf.getvalue()
    assert "feedback-loops" not in out
    assert "nan-uniforms" not in out
    assert "empty-capture" in out


def test_report_no_session_returns_2(tmp_path, monkeypatch):
    # Ensure discovery fails.
    monkeypatch.delenv("GPA_SESSION", raising=False)
    from gpa.cli import session as session_mod
    monkeypatch.setattr(session_mod, "CURRENT_SESSION_LINK",
                        str(tmp_path / "no-such-link"))
    buf = io.StringIO()
    rc = report_cmd.run(frame=1, print_stream=buf)
    assert rc == 2


# --------------------------------------------------------------------------- #
# check drill-down
# --------------------------------------------------------------------------- #


def test_check_feedback_loops_detailed(session_dir, injected_rest, monkeypatch):
    monkeypatch.setenv("GPA_SESSION", str(session_dir))
    buf = io.StringIO()
    rc = check_cmd.run(
        name="feedback-loops", frame=1,
        client=injected_rest, print_stream=buf,
    )
    out = buf.getvalue()
    assert "feedback-loops" in out
    # Draw call 0 in the mock is the one with the loop.
    assert "draw call 0" in out
    assert "texture_id=7" in out
    assert rc == 3


def test_check_empty_capture_ok(session_dir, injected_rest, monkeypatch):
    monkeypatch.setenv("GPA_SESSION", str(session_dir))
    buf = io.StringIO()
    rc = check_cmd.run(
        name="empty-capture", frame=1,
        client=injected_rest, print_stream=buf,
    )
    assert rc == 0
    assert "empty-capture: ok" in buf.getvalue()


def test_check_unknown_name(session_dir, injected_rest, monkeypatch):
    monkeypatch.setenv("GPA_SESSION", str(session_dir))
    buf = io.StringIO()
    rc = check_cmd.run(
        name="does-not-exist", frame=1,
        client=injected_rest, print_stream=buf,
    )
    assert rc == 1
