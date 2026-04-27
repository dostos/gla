"""Tests for the ``gpa frames`` CLI command.

Exercises the updated command end-to-end against an in-process REST app
(no real engine).  Verifies plain output, --json output, empty session,
and the missing-session exit code (2).
"""

from __future__ import annotations

import io
import json
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


class TestFramesCli:
    def test_basic_invocation_lists_one_id(self, session_dir, monkeypatch):
        monkeypatch.setenv("GPA_SESSION", str(session_dir))
        qe = _make_qe(latest_id=1, valid_ids={1})
        http = _make_test_client(qe)
        buf = io.StringIO()
        rc = frames_cmd.run(client=_injected(http), print_stream=buf)
        assert rc == 0
        assert buf.getvalue() == "1\n"

    def test_multiple_frames_one_per_line(self, session_dir, monkeypatch):
        monkeypatch.setenv("GPA_SESSION", str(session_dir))
        qe = _make_qe(latest_id=4, valid_ids={2, 3, 4})
        http = _make_test_client(qe)
        buf = io.StringIO()
        rc = frames_cmd.run(client=_injected(http), print_stream=buf)
        assert rc == 0
        assert buf.getvalue() == "2\n3\n4\n"

    def test_json_output(self, session_dir, monkeypatch):
        monkeypatch.setenv("GPA_SESSION", str(session_dir))
        qe = _make_qe(latest_id=3, valid_ids={1, 2, 3})
        http = _make_test_client(qe)
        buf = io.StringIO()
        rc = frames_cmd.run(
            client=_injected(http), print_stream=buf, json_output=True,
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
        rc = frames_cmd.run(client=_injected(http), print_stream=buf)
        assert rc == 0
        assert buf.getvalue() == ""

    def test_empty_session_json_output(self, session_dir, monkeypatch):
        """Empty session in JSON mode emits ``{"frames": [], "count": 0}``."""
        monkeypatch.setenv("GPA_SESSION", str(session_dir))
        qe = _make_qe(latest_id=None, valid_ids=set())
        http = _make_test_client(qe)
        buf = io.StringIO()
        rc = frames_cmd.run(
            client=_injected(http), print_stream=buf, json_output=True,
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
        rc = frames_cmd.run()
        assert rc == 2
