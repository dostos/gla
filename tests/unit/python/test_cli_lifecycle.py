"""Integration-ish tests for the ``gpa`` CLI lifecycle commands.

The engine launcher is replaced with a fake subprocess that:
  * binds the requested port (so ``wait_for_port`` succeeds),
  * writes an "I am alive" marker into the session log,
  * exits cleanly on SIGTERM.
"""

from __future__ import annotations

import io
import os
import socket
import subprocess
import sys
import textwrap
import time
from pathlib import Path
from typing import List
from unittest.mock import patch

import pytest

from gpa.cli import main as cli_main
from gpa.cli import session as session_mod
from gpa.cli.commands import env as env_cmd
from gpa.cli.commands import run as run_cmd
from gpa.cli.commands import start as start_cmd
from gpa.cli.commands import stop as stop_cmd
from gpa.cli.session import Session


# --------------------------------------------------------------------------- #
# Fake engine helpers
# --------------------------------------------------------------------------- #


FAKE_ENGINE_SCRIPT = textwrap.dedent(
    """
    import signal
    import socket
    import sys
    import time

    port = int(sys.argv[1])
    srv = socket.socket()
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind(("127.0.0.1", port))
    srv.listen(8)
    srv.settimeout(0.25)

    running = {"go": True}

    def _stop(*_):
        running["go"] = False

    signal.signal(signal.SIGTERM, _stop)
    signal.signal(signal.SIGINT, _stop)

    # Accept + close in a loop so wait_for_port succeeds quickly.
    while running["go"]:
        try:
            c, _ = srv.accept()
            c.close()
        except socket.timeout:
            pass
    """
)


def _free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


@pytest.fixture
def fake_spawn(monkeypatch, tmp_path):
    """Replace ``_spawn_engine`` with a version that launches FAKE_ENGINE_SCRIPT."""

    def fake(sess: Session, *, daemon: bool):
        script = tmp_path / "fake_engine.py"
        script.write_text(FAKE_ENGINE_SCRIPT)
        proc = subprocess.Popen(
            [sys.executable, str(script), str(sess.read_port())],
            stdout=open(sess.log_path, "ab"),
            stderr=subprocess.STDOUT,
            stdin=subprocess.DEVNULL,
        )
        sess.pid_path.write_text(str(proc.pid))
        return proc

    monkeypatch.setattr(start_cmd, "_spawn_engine", fake)
    monkeypatch.setattr(run_cmd, "_spawn_engine", fake)
    return fake


@pytest.fixture
def isolated_current_link(monkeypatch, tmp_path):
    link = tmp_path / "gpa-session-current"
    monkeypatch.setattr(session_mod, "CURRENT_SESSION_LINK", str(link))
    monkeypatch.delenv("GPA_SESSION", raising=False)
    return link


# --------------------------------------------------------------------------- #
# Lifecycle round-trip
# --------------------------------------------------------------------------- #


def test_start_stop_roundtrip(tmp_path, fake_spawn, isolated_current_link):
    sess_dir = tmp_path / "sess"
    port = _free_port()

    buf = io.StringIO()
    rc = start_cmd.run(session_dir=sess_dir, daemon=False, port=port, print_stream=buf)
    assert rc == 0, buf.getvalue()
    assert sess_dir.is_dir()
    assert (sess_dir / "engine.pid").exists()
    assert f"export GPA_PORT={port}" in buf.getvalue()
    assert os.readlink(str(isolated_current_link)) == str(sess_dir)

    # Env discovery while running.
    env_buf = io.StringIO()
    rc_env = env_cmd.run(print_stream=env_buf)
    assert rc_env == 0
    assert f"export GPA_PORT={port}" in env_buf.getvalue()

    # Stop removes everything.
    rc_stop = stop_cmd.run()
    assert rc_stop == 0
    assert not sess_dir.exists()
    assert not isolated_current_link.exists()


def test_start_accepts_pre_created_empty_dir(tmp_path, fake_spawn, isolated_current_link):
    """Regression: Round 10 eval runner pre-created the session dir; start must
    not reject it with FileExistsError."""
    sess_dir = tmp_path / "pre-made"
    sess_dir.mkdir(parents=True)  # what the runner did

    port = _free_port()
    buf = io.StringIO()
    rc = start_cmd.run(session_dir=sess_dir, daemon=False, port=port, print_stream=buf)
    assert rc == 0, buf.getvalue()
    assert (sess_dir / "engine.pid").exists()

    # Cleanup so the test leaves nothing behind.
    stop_cmd.run()


def test_start_rejects_dir_with_existing_session(tmp_path, fake_spawn, isolated_current_link, capsys):
    sess_dir = tmp_path / "live"
    sess_dir.mkdir(parents=True)
    (sess_dir / "engine.pid").write_text("99999")

    port = _free_port()
    rc = start_cmd.run(session_dir=sess_dir, daemon=False, port=port)
    assert rc == 1
    err = capsys.readouterr().err
    assert "Session already exists" in err
    assert "gpa stop" in err


def test_stop_with_no_session_returns_2(isolated_current_link, monkeypatch):
    monkeypatch.delenv("GPA_SESSION", raising=False)
    assert stop_cmd.run() == 2


def test_env_with_no_session_returns_2(isolated_current_link, monkeypatch):
    monkeypatch.delenv("GPA_SESSION", raising=False)
    buf = io.StringIO()
    assert env_cmd.run(print_stream=buf) == 2


# --------------------------------------------------------------------------- #
# gpa run
# --------------------------------------------------------------------------- #


def test_run_launches_child_and_cleans_up(tmp_path, fake_spawn, isolated_current_link):
    sess_dir = tmp_path / "run-sess"
    port = _free_port()
    rc = run_cmd.run(["/bin/true"], session_dir=sess_dir, port=port)
    assert rc == 0
    # Session directory cleaned after child exits.
    assert not sess_dir.exists()


def test_run_propagates_child_exit(tmp_path, fake_spawn, isolated_current_link):
    sess_dir = tmp_path / "run-sess2"
    port = _free_port()
    rc = run_cmd.run(["/bin/false"], session_dir=sess_dir, port=port)
    assert rc == 1
    assert not sess_dir.exists()


def test_run_sets_child_env(tmp_path, fake_spawn, isolated_current_link):
    sess_dir = tmp_path / "run-sess3"
    port = _free_port()
    marker = tmp_path / "env.dump"
    # /bin/sh is portable enough for this test host.
    cmd = ["/bin/sh", "-c", f'echo "$GPA_TOKEN|$LD_PRELOAD|$GPA_SOCKET_PATH" > {marker}']
    rc = run_cmd.run(cmd, session_dir=sess_dir, port=port)
    assert rc == 0

    token, ld_preload, shim_sock = marker.read_text().strip().split("|")
    assert len(token) == 32
    assert "libgpa_gl.so" in ld_preload
    assert shim_sock.endswith("/socket")


def test_run_missing_command_returns_error(tmp_path, fake_spawn, isolated_current_link):
    rc = run_cmd.run([], session_dir=tmp_path / "empty", port=_free_port())
    assert rc == 1


# --------------------------------------------------------------------------- #
# argparse surface
# --------------------------------------------------------------------------- #


def test_main_dispatches_start(monkeypatch):
    called = {}

    def fake_start(**kwargs):
        called.update(kwargs)
        return 0

    monkeypatch.setattr(start_cmd, "run", fake_start)
    rc = cli_main.main(["start", "--session", "/tmp/x", "--port", "9999", "--no-daemon"])
    assert rc == 0
    assert called["session_dir"] == Path("/tmp/x")
    assert called["port"] == 9999
    assert called["daemon"] is False


def test_main_dispatches_run_with_double_dash(monkeypatch):
    called = {}

    def fake_run(command, **kwargs):
        called["command"] = command
        called.update(kwargs)
        return 0

    monkeypatch.setattr(run_cmd, "run", fake_run)
    rc = cli_main.main(
        ["run", "--port", "9000", "--", "/bin/echo", "hello", "world"]
    )
    assert rc == 0
    assert called["command"] == ["/bin/echo", "hello", "world"]
    assert called["port"] == 9000
