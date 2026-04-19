"""Integration tests for ``gpa report`` / ``gpa check`` against a live TestClient.

We plug Starlette's ``TestClient`` into ``RestClient`` via ``http_callable``
so we exercise the full FastAPI app without touching the network.
"""

from __future__ import annotations

import io
from pathlib import Path

import pytest

from gpa.cli.checks import CheckResult, Finding
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


# --------------------------------------------------------------------------- #
# Drill-down hints in report output
# --------------------------------------------------------------------------- #


def _render(results, *, frame_id=2, draw_call_count=10, colored=False):
    """Render ``_format_text`` with a synthetic results list."""
    return report_cmd._format_text(
        frame_id=frame_id,
        draw_call_count=draw_call_count,
        session_dir=Path("/tmp/sess"),
        results=results,
        colored=colored,
    )


def test_report_emits_drill_hints_per_dc():
    results = [
        CheckResult(
            name="feedback-loops",
            status="warn",
            findings=[
                Finding(
                    summary="draw call 3: texture 7 bound as sampler (slot 0) AND COLOR_ATTACHMENT0",
                    detail={"dc_id": 3, "texture_id": 7},
                ),
            ],
        ),
        CheckResult(
            name="nan-uniforms",
            status="warn",
            findings=[
                Finding(
                    summary="draw call 3: uRoughness (type=0x8B51), components [0]",
                    detail={"dc_id": 3, "uniform": "uRoughness"},
                ),
                Finding(
                    summary="draw call 5: uSpec (type=0x8B52), components [2, 3]",
                    detail={"dc_id": 5, "uniform": "uSpec"},
                ),
            ],
        ),
    ]
    out = _render(results, frame_id=2)
    assert "→ drill: gpa check feedback-loops --frame 2 --dc 3" in out
    assert "→ drill: gpa check nan-uniforms --frame 2 --dc 3" in out
    assert "→ drill: gpa check nan-uniforms --frame 2 --dc 5" in out
    # Old footer is gone.
    assert "Run `gpa check" not in out


def test_report_hint_no_dc_for_frame_level_checks():
    results = [
        CheckResult(
            name="missing-clear",
            status="warn",
            findings=[
                Finding(
                    summary="no glClear before first draw",
                    detail={"frame_id": 2, "clear_count": 0},
                ),
            ],
        ),
    ]
    out = _render(results, frame_id=2)
    assert "→ drill: gpa check missing-clear --frame 2" in out
    # No --dc flag should appear on the hint line.
    hint_lines = [ln for ln in out.splitlines() if "drill:" in ln]
    assert len(hint_lines) == 1
    assert "--dc" not in hint_lines[0]


def test_report_hint_dedupes_by_dc():
    results = [
        CheckResult(
            name="nan-uniforms",
            status="warn",
            findings=[
                Finding(
                    summary="draw call 5: uA (type=0x8B51), components [0]",
                    detail={"dc_id": 5, "uniform": "uA"},
                ),
                Finding(
                    summary="draw call 5: uB (type=0x8B51), components [1]",
                    detail={"dc_id": 5, "uniform": "uB"},
                ),
            ],
        ),
    ]
    out = _render(results, frame_id=2)
    hint_lines = [ln for ln in out.splitlines() if "drill:" in ln]
    assert len(hint_lines) == 1
    assert "gpa check nan-uniforms --frame 2 --dc 5" in hint_lines[0]


def test_report_no_hints_in_json_mode(session_dir, injected_rest, monkeypatch):
    monkeypatch.setenv("GPA_SESSION", str(session_dir))
    buf = io.StringIO()
    report_cmd.run(
        frame=1, json_output=True, client=injected_rest, print_stream=buf
    )
    out = buf.getvalue()
    assert "drill" not in out
