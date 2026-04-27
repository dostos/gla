"""Integration tests for ``gpa check-config`` CLI surface."""
from __future__ import annotations

import io
import json
from pathlib import Path

import pytest

from gpa.cli.commands import check_config as cc_cmd
from gpa.cli.rest_client import RestClient, RestError


# --------------------------------------------------------------------------- #
# Fixtures
# --------------------------------------------------------------------------- #


@pytest.fixture
def session_dir(tmp_path) -> Path:
    d = tmp_path / "sess"
    d.mkdir()
    (d / "token").write_text("test-token")
    (d / "port").write_text("18080")
    (d / "shm-name").write_text("/gpa-test")
    return d


@pytest.fixture
def injected_rest(client):
    """RestClient that routes through Starlette's TestClient."""
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
        if not resp.content:
            return None
        return resp.json()

    return RestClient(token="test-token", http_callable=http_callable)


# --------------------------------------------------------------------------- #
# --rules listing (no session needed)
# --------------------------------------------------------------------------- #


class TestRulesListing:
    def test_rules_flag_lists_all(self, monkeypatch, tmp_path):
        # No session needed; --rules short-circuits.
        from gpa.cli import session as session_mod
        monkeypatch.delenv("GPA_SESSION", raising=False)
        monkeypatch.setattr(
            session_mod, "CURRENT_SESSION_LINK",
            str(tmp_path / "no-such-link"),
        )
        buf = io.StringIO()
        rc = cc_cmd.run(rules=True, print_stream=buf)
        assert rc == 0
        out = buf.getvalue()
        assert "auto-clear-with-no-explicit-clear" in out
        assert "depth-write-without-depth-test" in out
        # All 8 rule ids should appear.
        from gpa.checks import default_engine
        for rid in default_engine().rule_ids():
            assert rid in out

    def test_rules_json(self, monkeypatch, tmp_path):
        from gpa.cli import session as session_mod
        monkeypatch.delenv("GPA_SESSION", raising=False)
        monkeypatch.setattr(
            session_mod, "CURRENT_SESSION_LINK",
            str(tmp_path / "no-such-link"),
        )
        buf = io.StringIO()
        rc = cc_cmd.run(rules=True, json_output=True, print_stream=buf)
        assert rc == 0
        data = json.loads(buf.getvalue())
        ids = {r["id"] for r in data["rules"]}
        assert len(ids) == 8


# --------------------------------------------------------------------------- #
# Live REST happy path
# --------------------------------------------------------------------------- #


class TestLiveCheckConfig:
    def test_default_human_output(
        self, session_dir, injected_rest, monkeypatch
    ):
        monkeypatch.setenv("GPA_SESSION", str(session_dir))
        buf = io.StringIO()
        rc = cc_cmd.run(
            frame="1", client=injected_rest, print_stream=buf,
        )
        out = buf.getvalue()
        assert "gpa check-config — frame 1" in out
        # The conftest mock has clear_count=0 and 1+ draws → auto-clear
        # fires at error severity. Default --severity warn includes it.
        assert "[ERROR]" in out
        assert "auto-clear-with-no-explicit-clear" in out
        # Findings present → exit code 2 per spec.
        assert rc == 2

    def test_json_output(
        self, session_dir, injected_rest, monkeypatch
    ):
        monkeypatch.setenv("GPA_SESSION", str(session_dir))
        buf = io.StringIO()
        rc = cc_cmd.run(
            frame="1", json_output=True,
            client=injected_rest, print_stream=buf,
        )
        data = json.loads(buf.getvalue())
        assert data["frame_id"] == 1
        assert isinstance(data["findings"], list)
        assert any(
            f["rule_id"] == "auto-clear-with-no-explicit-clear"
            for f in data["findings"]
        )
        assert rc == 2

    def test_severity_error_filters(
        self, session_dir, injected_rest, monkeypatch
    ):
        monkeypatch.setenv("GPA_SESSION", str(session_dir))
        buf = io.StringIO()
        rc = cc_cmd.run(
            frame="1", severity="error",
            client=injected_rest, print_stream=buf,
        )
        out = buf.getvalue()
        # At error severity only auto-clear fires; depth-write and others
        # should be absent.
        assert "auto-clear-with-no-explicit-clear" in out
        assert "depth-write-without-depth-test" not in out
        assert rc == 2

    def test_no_findings_at_error_when_clean(
        self, session_dir, injected_rest, monkeypatch, mock_query_engine
    ):
        # Tune the mock so no error rules fire (clear_count=1).
        ov = mock_query_engine.latest_frame_overview()
        ov.clear_count = 1
        # Recreate side_effect so frame_overview also returns clear_count=1
        from unittest.mock import MagicMock as _MM
        new_ov = _MM()
        new_ov.frame_id = 1
        new_ov.draw_call_count = 1
        new_ov.clear_count = 1
        new_ov.fb_width = 800
        new_ov.fb_height = 600
        new_ov.timestamp = 0.0
        mock_query_engine.frame_overview.side_effect = lambda fid: (
            new_ov if fid == 1 else None
        )
        mock_query_engine.latest_frame_overview.return_value = new_ov

        monkeypatch.setenv("GPA_SESSION", str(session_dir))
        buf = io.StringIO()
        rc = cc_cmd.run(
            frame="1", severity="error",
            client=injected_rest, print_stream=buf,
        )
        out = buf.getvalue()
        # No error-level findings → exit 0.
        assert "0 findings" in out
        assert rc == 0

    def test_rule_filter_passthrough(
        self, session_dir, injected_rest, monkeypatch
    ):
        monkeypatch.setenv("GPA_SESSION", str(session_dir))
        buf = io.StringIO()
        rc = cc_cmd.run(
            frame="1",
            rule="auto-clear-with-no-explicit-clear",
            severity="info",
            client=injected_rest, print_stream=buf,
        )
        out = buf.getvalue()
        assert "auto-clear-with-no-explicit-clear" in out
        # Other rules excluded.
        assert "depth-write-without-depth-test" not in out
        assert rc == 2

    def test_default_frame_resolves_to_latest(
        self, session_dir, injected_rest, monkeypatch
    ):
        monkeypatch.setenv("GPA_SESSION", str(session_dir))
        buf = io.StringIO()
        # No --frame, no stdin (use a TTY-faking IO).
        stdin = io.StringIO("")
        # Make .isatty() return True via wrapper.
        class _TTY(io.StringIO):
            def isatty(self):
                return True
        rc = cc_cmd.run(
            client=injected_rest, print_stream=buf, stdin_stream=_TTY(),
        )
        # Should have hit /frames/latest/check-config and rendered fine.
        assert "frame 1" in buf.getvalue()
        assert rc == 2


# --------------------------------------------------------------------------- #
# Error paths
# --------------------------------------------------------------------------- #


class TestErrorPaths:
    def test_unknown_rule_name_exit_3(
        self, session_dir, injected_rest, monkeypatch, capsys
    ):
        monkeypatch.setenv("GPA_SESSION", str(session_dir))
        buf = io.StringIO()
        rc = cc_cmd.run(
            frame="1", rule="not-a-real-rule",
            client=injected_rest, print_stream=buf,
        )
        assert rc == 3
        captured = capsys.readouterr()
        assert "unknown rule" in captured.err.lower()
        assert "gpa check-config --rules" in captured.err

    def test_no_session_exit_3(self, monkeypatch, tmp_path, capsys):
        from gpa.cli import session as session_mod
        monkeypatch.delenv("GPA_SESSION", raising=False)
        monkeypatch.setattr(
            session_mod, "CURRENT_SESSION_LINK",
            str(tmp_path / "no-such-link"),
        )
        buf = io.StringIO()
        rc = cc_cmd.run(frame="1", print_stream=buf)
        assert rc == 3
        captured = capsys.readouterr()
        assert "gpa start" in captured.err

    def test_invalid_frame_value_exit_3(
        self, session_dir, monkeypatch, capsys
    ):
        monkeypatch.setenv("GPA_SESSION", str(session_dir))
        buf = io.StringIO()
        rc = cc_cmd.run(frame="abc", print_stream=buf)
        assert rc == 3
        captured = capsys.readouterr()
        assert "--frame" in captured.err

    def test_invalid_severity_exit_3(
        self, session_dir, monkeypatch, capsys
    ):
        monkeypatch.setenv("GPA_SESSION", str(session_dir))
        buf = io.StringIO()
        rc = cc_cmd.run(frame="1", severity="critical", print_stream=buf)
        assert rc == 3
        captured = capsys.readouterr()
        assert "severity" in captured.err.lower()


# --------------------------------------------------------------------------- #
# stdin pipeline
# --------------------------------------------------------------------------- #


class TestStdinPipeline:
    def test_dash_frame_reads_stdin(
        self, session_dir, injected_rest, monkeypatch
    ):
        monkeypatch.setenv("GPA_SESSION", str(session_dir))
        buf = io.StringIO()
        # Two ids in stdin.
        stdin = io.StringIO("1\n1\n")
        rc = cc_cmd.run(
            frame="-", client=injected_rest,
            print_stream=buf, stdin_stream=stdin,
        )
        out = buf.getvalue()
        # Both runs fire; we should see frame 1 mentioned twice.
        assert out.count("frame 1") == 2
        assert rc == 2

    def test_dash_frame_empty_stdin_falls_back_to_latest(
        self, session_dir, injected_rest, monkeypatch
    ):
        monkeypatch.setenv("GPA_SESSION", str(session_dir))
        buf = io.StringIO()
        stdin = io.StringIO("")
        rc = cc_cmd.run(
            frame="-", client=injected_rest,
            print_stream=buf, stdin_stream=stdin,
        )
        # Should still produce one report from "latest".
        assert "frame 1" in buf.getvalue()
        assert rc == 2


# --------------------------------------------------------------------------- #
# argparse wiring (smoke)
# --------------------------------------------------------------------------- #


class TestArgparseWiring:
    def test_help_includes_examples(self, capsys):
        from gpa.cli.main import build_parser
        parser = build_parser()
        with pytest.raises(SystemExit) as e:
            parser.parse_args(["check-config", "--help"])
        assert e.value.code == 0
        out = capsys.readouterr().out
        # 4+ worked examples per cli-for-agents principle.
        assert "Examples:" in out
        assert "gpa check-config --frame 142 --json" in out
        assert "gpa check-config --severity error" in out
        assert "gpa check-config --rules" in out
        assert "color-space-encoding-mismatch" in out

    def test_subcommand_parses_typed_args(self):
        from gpa.cli.main import build_parser
        parser = build_parser()
        args = parser.parse_args([
            "check-config", "--frame", "7", "--severity", "error",
            "--rule", "a,b", "--json",
        ])
        assert args.cmd == "check-config"
        assert args.frame == "7"
        assert args.severity == "error"
        assert args.rule == "a,b"
        assert args.json_output is True

    def test_dash_frame_accepted(self):
        from gpa.cli.main import build_parser
        parser = build_parser()
        args = parser.parse_args(["check-config", "--frame", "-"])
        assert args.frame == "-"
