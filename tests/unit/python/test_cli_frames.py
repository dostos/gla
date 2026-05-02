"""Tests for the ``gpa frames`` CLI command.

Exercises the updated command end-to-end against an in-process REST app
(no real engine).  Verifies plain output, --json output, empty session,
and the missing-session exit code (2).

New tests cover the noun-verb subparser surface:
  gpa frames list [--json] [--text]
  gpa frames overview [--frame N]
  gpa frames check-config [--frame N] [--json]
  bare ``gpa frames`` (deprecated alias for list)
"""

from __future__ import annotations

import io
import json
import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from starlette.testclient import TestClient

from gpa.api.app import create_app
from gpa.backends.native import NativeBackend
from gpa.cli.commands import frames as frames_cmd
from gpa.cli.rest_client import RestClient, RestError

from conftest import AUTH_TOKEN, _make_overview


@pytest.fixture
def session_dir(tmp_path) -> Path:
    d = tmp_path / "sess"
    d.mkdir()
    (d / "token").write_text(AUTH_TOKEN)
    (d / "port").write_text("18080")
    (d / "shm-name").write_text("/gpa-test")
    return d


@pytest.fixture
def injected_rest(client) -> RestClient:
    """RestClient routed through the conftest Starlette TestClient."""
    def http_callable(method, path, headers, body=None):
        if method == "GET":
            resp = client.get(path, headers=headers)
        else:  # pragma: no cover
            raise AssertionError(f"unsupported method {method}")
        if resp.status_code >= 400:
            raise RestError(
                f"{method} {path} → HTTP {resp.status_code}",
                status=resp.status_code,
            )
        if not resp.content:
            return None
        return resp.json()
    return RestClient(token=AUTH_TOKEN, http_callable=http_callable)


def _make_qe(latest_id: int, valid_ids: set) -> MagicMock:
    qe = MagicMock()
    if latest_id is None:
        qe.latest_frame_overview.return_value = None
        qe.frame_overview.side_effect = lambda fid: None
        return qe
    ov = _make_overview(frame_id=latest_id)
    qe.latest_frame_overview.return_value = ov
    qe.frame_overview.side_effect = lambda fid: (
        _make_overview(frame_id=fid) if fid in valid_ids else None
    )
    return qe


def _make_test_client(qe: MagicMock) -> TestClient:
    provider = NativeBackend(qe, engine=None)
    app = create_app(provider=provider, auth_token=AUTH_TOKEN)
    return TestClient(app, raise_server_exceptions=True)


def _injected(http_client: TestClient) -> RestClient:
    def http_callable(method, path, headers, body=None):
        if method == "GET":
            resp = http_client.get(path, headers=headers)
        else:  # pragma: no cover
            raise AssertionError(f"unsupported method {method}")
        if resp.status_code >= 400:
            raise RestError(
                f"{method} {path} → HTTP {resp.status_code}",
                status=resp.status_code,
            )
        if not resp.content:
            return None
        return resp.json()
    return RestClient(token=AUTH_TOKEN, http_callable=http_callable)


# --------------------------------------------------------------------------- #
# Legacy top-level run() API — preserved for backward compat
# --------------------------------------------------------------------------- #

class TestFramesCli:
    def test_basic_invocation_lists_one_id(self, session_dir, monkeypatch):
        monkeypatch.setenv("GPA_SESSION", str(session_dir))
        qe = _make_qe(latest_id=1, valid_ids={1})
        http = _make_test_client(qe)
        buf = io.StringIO()
        rc = frames_cmd.run_list(client=_injected(http), print_stream=buf, text_output=True, json_output=False)
        assert rc == 0
        assert buf.getvalue() == "1\n"

    def test_multiple_frames_one_per_line(self, session_dir, monkeypatch):
        monkeypatch.setenv("GPA_SESSION", str(session_dir))
        qe = _make_qe(latest_id=4, valid_ids={2, 3, 4})
        http = _make_test_client(qe)
        buf = io.StringIO()
        rc = frames_cmd.run_list(client=_injected(http), print_stream=buf, text_output=True, json_output=False)
        assert rc == 0
        assert buf.getvalue() == "2\n3\n4\n"

    def test_json_output(self, session_dir, monkeypatch):
        monkeypatch.setenv("GPA_SESSION", str(session_dir))
        qe = _make_qe(latest_id=3, valid_ids={1, 2, 3})
        http = _make_test_client(qe)
        buf = io.StringIO()
        rc = frames_cmd.run_list(
            client=_injected(http), print_stream=buf, text_output=False, json_output=True,
        )
        assert rc == 0
        data = json.loads(buf.getvalue())
        assert data == {"frames": [1, 2, 3], "count": 3}

    def test_empty_session_clean_exit(self, session_dir, monkeypatch):
        """No frames captured → empty output, exit 0 (not an error)."""
        monkeypatch.setenv("GPA_SESSION", str(session_dir))
        qe = _make_qe(latest_id=None, valid_ids=set())
        http = _make_test_client(qe)
        buf = io.StringIO()
        rc = frames_cmd.run_list(client=_injected(http), print_stream=buf, text_output=True, json_output=False)
        assert rc == 0
        assert buf.getvalue() == ""

    def test_empty_session_json_output(self, session_dir, monkeypatch):
        """Empty session in JSON mode emits ``{"frames": [], "count": 0}``."""
        monkeypatch.setenv("GPA_SESSION", str(session_dir))
        qe = _make_qe(latest_id=None, valid_ids=set())
        http = _make_test_client(qe)
        buf = io.StringIO()
        rc = frames_cmd.run_list(
            client=_injected(http), print_stream=buf, text_output=False, json_output=True,
        )
        assert rc == 0
        data = json.loads(buf.getvalue())
        assert data == {"frames": [], "count": 0}

    def test_missing_session_exit_2(self, tmp_path, monkeypatch):
        """No active session → exit 2."""
        from gpa.cli import session as session_mod
        monkeypatch.delenv("GPA_SESSION", raising=False)
        monkeypatch.setattr(
            session_mod, "CURRENT_SESSION_LINK",
            str(tmp_path / "no-such-link"),
        )
        rc = frames_cmd.run_list(text_output=True, json_output=False)
        assert rc == 2


# --------------------------------------------------------------------------- #
# New subverb: frames list
# --------------------------------------------------------------------------- #

class TestFramesList:
    def test_list_default_json(self, session_dir, monkeypatch):
        """``frames list`` with no flags defaults to JSON output."""
        monkeypatch.setenv("GPA_SESSION", str(session_dir))
        qe = _make_qe(latest_id=3, valid_ids={1, 2, 3})
        http = _make_test_client(qe)
        buf = io.StringIO()
        rc = frames_cmd.run_list(
            client=_injected(http), print_stream=buf,
            text_output=False, json_output=False,
        )
        assert rc == 0
        data = json.loads(buf.getvalue())
        assert data == {"frames": [1, 2, 3], "count": 3}

    def test_list_json_flag(self, session_dir, monkeypatch):
        """``frames list --json`` returns JSON envelope."""
        monkeypatch.setenv("GPA_SESSION", str(session_dir))
        qe = _make_qe(latest_id=2, valid_ids={1, 2})
        http = _make_test_client(qe)
        buf = io.StringIO()
        rc = frames_cmd.run_list(
            client=_injected(http), print_stream=buf,
            text_output=False, json_output=True,
        )
        assert rc == 0
        data = json.loads(buf.getvalue())
        assert data["count"] == 2
        assert set(data["frames"]) == {1, 2}

    def test_list_text_flag(self, session_dir, monkeypatch):
        """``frames list --text`` returns one id per line."""
        monkeypatch.setenv("GPA_SESSION", str(session_dir))
        qe = _make_qe(latest_id=3, valid_ids={1, 2, 3})
        http = _make_test_client(qe)
        buf = io.StringIO()
        rc = frames_cmd.run_list(
            client=_injected(http), print_stream=buf,
            text_output=True, json_output=False,
        )
        assert rc == 0
        lines = [l for l in buf.getvalue().splitlines() if l.strip()]
        assert lines == ["1", "2", "3"]

    def test_list_text_overrides_json(self, session_dir, monkeypatch):
        """If both --text and --json, --text wins (text is the opt-in)."""
        monkeypatch.setenv("GPA_SESSION", str(session_dir))
        qe = _make_qe(latest_id=1, valid_ids={1})
        http = _make_test_client(qe)
        buf = io.StringIO()
        rc = frames_cmd.run_list(
            client=_injected(http), print_stream=buf,
            text_output=True, json_output=True,
        )
        assert rc == 0
        # Should be plain text, not JSON.
        assert buf.getvalue().strip() == "1"


# --------------------------------------------------------------------------- #
# New subverb: frames overview
# --------------------------------------------------------------------------- #

class TestFramesOverview:
    def test_overview_latest(self, session_dir, monkeypatch):
        """``frames overview`` with no --frame falls back to REST current."""
        monkeypatch.setenv("GPA_SESSION", str(session_dir))
        monkeypatch.delenv("GPA_FRAME_ID", raising=False)
        qe = _make_qe(latest_id=5, valid_ids={5})
        http = _make_test_client(qe)
        buf = io.StringIO()
        rc = frames_cmd.run_overview(
            client=_injected(http), print_stream=buf, frame=None,
        )
        assert rc == 0
        data = json.loads(buf.getvalue())
        assert data["frame_id"] == 5

    def test_overview_specific_frame(self, session_dir, monkeypatch):
        """``frames overview --frame 7`` calls the right URL."""
        monkeypatch.setenv("GPA_SESSION", str(session_dir))
        monkeypatch.delenv("GPA_FRAME_ID", raising=False)
        qe = _make_qe(latest_id=10, valid_ids={7, 10})
        http = _make_test_client(qe)
        buf = io.StringIO()
        rc = frames_cmd.run_overview(
            client=_injected(http), print_stream=buf, frame="7",
        )
        assert rc == 0
        data = json.loads(buf.getvalue())
        assert data["frame_id"] == 7

    def test_overview_env_frame(self, session_dir, monkeypatch):
        """GPA_FRAME_ID env var is used when --frame is not given."""
        monkeypatch.setenv("GPA_SESSION", str(session_dir))
        monkeypatch.setenv("GPA_FRAME_ID", "3")
        qe = _make_qe(latest_id=5, valid_ids={3, 5})
        http = _make_test_client(qe)
        buf = io.StringIO()
        rc = frames_cmd.run_overview(
            client=_injected(http), print_stream=buf, frame=None,
        )
        assert rc == 0
        data = json.loads(buf.getvalue())
        assert data["frame_id"] == 3


# --------------------------------------------------------------------------- #
# New subverb: frames check-config
# --------------------------------------------------------------------------- #

class TestFramesCheckConfig:
    def test_check_config_delegates(self, session_dir, injected_rest, monkeypatch):
        """``frames check-config --frame 1`` delegates to check_config.run()."""
        monkeypatch.setenv("GPA_SESSION", str(session_dir))
        buf = io.StringIO()
        stdin = io.StringIO("")  # prevent pytest stdin capture error
        rc = frames_cmd.run_check_config(
            client=injected_rest,
            print_stream=buf,
            session_dir=session_dir,
            frame="1",  # frame 1 is the only valid frame in the conftest mock
            severity="warn",
            rules=False,
            rule=None,
            json_output=True,
            stdin_stream=stdin,
        )
        # The REST endpoint returns 200 with a findings payload.
        assert rc in (0, 2)  # 0 = no findings, 2 = findings present
        out = buf.getvalue().strip()
        assert out  # something was written

    def test_check_config_no_frame(self, session_dir, injected_rest, monkeypatch):
        """``frames check-config`` without --frame uses latest."""
        monkeypatch.setenv("GPA_SESSION", str(session_dir))
        buf = io.StringIO()
        stdin = io.StringIO("")  # prevent pytest stdin capture error
        rc = frames_cmd.run_check_config(
            client=injected_rest,
            print_stream=buf,
            session_dir=session_dir,
            frame=None,
            severity="warn",
            rules=False,
            rule=None,
            json_output=True,
            stdin_stream=stdin,
        )
        assert rc in (0, 2)


# --------------------------------------------------------------------------- #
# Deprecated bare ``gpa frames`` alias
# --------------------------------------------------------------------------- #

class TestBareFramesAlias:
    def test_bare_frames_prints_deprecation_to_stderr(
        self, session_dir, monkeypatch, capsys
    ):
        """Bare ``gpa frames`` emits deprecation warning to stderr."""
        import argparse
        monkeypatch.setenv("GPA_SESSION", str(session_dir))
        qe = _make_qe(latest_id=1, valid_ids={1})
        http = _make_test_client(qe)
        buf = io.StringIO()

        # Simulate bare ``gpa frames`` by passing args with frames_cmd=None
        args = argparse.Namespace(
            frames_cmd=None,
            session=session_dir,
            json_output=False,
            text_output=False,
        )
        rc = frames_cmd.run(args, client=_injected(http), print_stream=buf)
        assert rc == 0
        captured = capsys.readouterr()
        assert "deprecated" in captured.err.lower()
        assert "gpa frames list" in captured.err

    def test_bare_frames_still_lists_frames(
        self, session_dir, monkeypatch, capsys
    ):
        """Bare ``gpa frames`` still lists frames (alias behavior)."""
        import argparse
        monkeypatch.setenv("GPA_SESSION", str(session_dir))
        qe = _make_qe(latest_id=2, valid_ids={1, 2})
        http = _make_test_client(qe)
        buf = io.StringIO()

        args = argparse.Namespace(
            frames_cmd=None,
            session=session_dir,
            json_output=False,
            text_output=False,
        )
        rc = frames_cmd.run(args, client=_injected(http), print_stream=buf)
        assert rc == 0
        # Default is JSON now.
        data = json.loads(buf.getvalue())
        assert data["count"] == 2
