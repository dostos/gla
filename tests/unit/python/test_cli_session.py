"""Unit tests for ``gpa.cli.session.Session``."""

from __future__ import annotations

import os
import stat
from pathlib import Path

import pytest

from gpa.cli import session as session_mod
from gpa.cli.session import Session, SessionExistsError


def test_create_populates_directory(tmp_path: Path) -> None:
    target = tmp_path / "sess"
    sess = Session.create(dir=target, port=12345)

    assert sess.dir == target
    assert target.is_dir()

    # token: 32 hex chars, mode 0600.
    token = sess.read_token()
    assert len(token) == 32
    assert all(c in "0123456789abcdef" for c in token)
    mode = stat.S_IMODE(os.stat(sess.token_path).st_mode)
    assert mode == 0o600

    # shm name, port recorded.
    assert sess.read_shm_name().startswith("/gpa-")
    assert sess.read_port() == 12345


def test_create_auto_allocates_dir(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)  # cosmetic; dir comes from /tmp
    sess = Session.create(port=18080)
    try:
        assert sess.dir.exists()
        assert sess.dir.name.startswith("gpa-session-")
        assert str(sess.dir).startswith("/tmp/")
    finally:
        sess.cleanup()


def test_create_accepts_empty_existing_dir(tmp_path: Path) -> None:
    """An empty pre-created directory must be reused, not rejected."""
    target = tmp_path / "pre-made"
    target.mkdir()
    sess = Session.create(dir=target, port=12345)
    assert sess.dir == target
    assert sess.token_path.exists()
    assert sess.read_port() == 12345


def test_create_accepts_dir_with_unrelated_files(tmp_path: Path) -> None:
    """Dir with non-session files (leftover scratch / .gitkeep / etc.) is reusable."""
    target = tmp_path / "pre-made-with-stuff"
    target.mkdir()
    (target / "scratch.txt").write_text("hello")
    (target / ".keep").write_text("")
    sess = Session.create(dir=target, port=23456)
    assert sess.dir == target
    assert sess.token_path.exists()
    assert (target / "scratch.txt").read_text() == "hello"


def test_create_rejects_existing_engine_pid(tmp_path: Path) -> None:
    """An engine.pid file means a session lives there — must refuse."""
    target = tmp_path / "live-session"
    target.mkdir()
    (target / "engine.pid").write_text("123")

    with pytest.raises(SessionExistsError) as ei:
        Session.create(dir=target, port=1)

    msg = str(ei.value)
    assert "Session already exists" in msg
    assert str(target) in msg
    assert "gpa stop" in msg


def test_create_rejects_existing_token(tmp_path: Path) -> None:
    target = tmp_path / "tokened"
    target.mkdir()
    (target / "token").write_text("deadbeef" * 4)
    with pytest.raises(SessionExistsError):
        Session.create(dir=target, port=1)


def test_create_rejects_existing_socket_file(tmp_path: Path) -> None:
    target = tmp_path / "with-socket"
    target.mkdir()
    (target / "socket").touch()
    with pytest.raises(SessionExistsError):
        Session.create(dir=target, port=1)


def test_create_rejects_when_target_is_a_file(tmp_path: Path) -> None:
    target = tmp_path / "i-am-a-file"
    target.write_text("not a dir")
    with pytest.raises(SessionExistsError):
        Session.create(dir=target, port=1)


def test_find_free_port_returns_bindable_port() -> None:
    import socket as _socket

    port = session_mod.find_free_port()
    assert 1024 < port < 65536
    # We should be able to bind it (ephemeral port we just released).
    s = _socket.socket()
    try:
        s.bind(("127.0.0.1", port))
    finally:
        s.close()


def test_env_exports_block(tmp_path: Path) -> None:
    sess = Session.create(dir=tmp_path / "s", port=9000)
    block = sess.env_exports()

    for key in (
        "GPA_SESSION",
        "GPA_SOCKET_PATH",
        "GPA_SHM_NAME",
        "GPA_TOKEN",
        "GPA_PORT",
        "GPA_SOCKET_PATH",
        "GPA_SHM_NAME",
        "GPA_TOKEN",
    ):
        assert f"export {key}=" in block
    assert f"export GPA_PORT=9000" in block


def test_child_env_contains_session_vars(tmp_path: Path) -> None:
    sess = Session.create(dir=tmp_path / "s", port=9000)
    env = sess.child_env({"PATH": "/usr/bin"})
    assert env["PATH"] == "/usr/bin"
    assert env["GPA_SESSION"] == str(sess.dir)
    assert env["GPA_TOKEN"] == sess.read_token()
    assert env["GPA_SOCKET_PATH"] == str(sess.socket_path)


def test_discover_prefers_explicit(tmp_path: Path) -> None:
    sess = Session.create(dir=tmp_path / "a", port=1)
    found = Session.discover(explicit=sess.dir)
    assert found is not None
    assert found.dir == sess.dir


def test_discover_env_var(tmp_path: Path, monkeypatch) -> None:
    sess = Session.create(dir=tmp_path / "b", port=1)
    monkeypatch.setenv("GPA_SESSION", str(sess.dir))
    # make sure the current-session link doesn't win
    monkeypatch.setattr(session_mod, "CURRENT_SESSION_LINK", str(tmp_path / "nope"))
    found = Session.discover()
    assert found is not None
    assert found.dir == sess.dir


def test_discover_returns_none_when_nothing(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.delenv("GPA_SESSION", raising=False)
    monkeypatch.setattr(
        session_mod, "CURRENT_SESSION_LINK", str(tmp_path / "no-link")
    )
    assert Session.discover() is None


def test_discover_via_current_symlink(tmp_path: Path, monkeypatch) -> None:
    sess = Session.create(dir=tmp_path / "c", port=1)
    link = tmp_path / "current"
    monkeypatch.setattr(session_mod, "CURRENT_SESSION_LINK", str(link))
    monkeypatch.delenv("GPA_SESSION", raising=False)
    os.symlink(str(sess.dir), str(link))

    found = Session.discover()
    assert found is not None
    assert found.dir == sess.dir


def test_mark_current_creates_symlink(tmp_path: Path, monkeypatch) -> None:
    sess = Session.create(dir=tmp_path / "d", port=1)
    link = tmp_path / "current"
    monkeypatch.setattr(session_mod, "CURRENT_SESSION_LINK", str(link))
    sess.mark_current()
    assert os.readlink(str(link)) == str(sess.dir)

    # Second call replaces an existing link.
    sess2 = Session.create(dir=tmp_path / "e", port=1)
    sess2.mark_current()
    assert os.readlink(str(link)) == str(sess2.dir)


def test_cleanup_removes_dir_and_shm(tmp_path: Path, monkeypatch) -> None:
    sess = Session.create(dir=tmp_path / "f", port=1)
    # Touch the socket path so cleanup exercises the unlink branch.
    sess.socket_path.touch()
    # Redirect the current-link path to a tmp location we can safely unlink.
    link = tmp_path / "current"
    monkeypatch.setattr(session_mod, "CURRENT_SESSION_LINK", str(link))
    os.symlink(str(sess.dir), str(link))

    sess.cleanup()
    assert not sess.dir.exists()
    assert not link.exists()


def test_terminate_engine_no_pid(tmp_path: Path) -> None:
    sess = Session.create(dir=tmp_path / "g", port=1)
    assert sess.terminate_engine() is False


def test_terminate_engine_already_dead(tmp_path: Path) -> None:
    sess = Session.create(dir=tmp_path / "h", port=1)
    # Use a pid that is vanishingly unlikely to be live.
    sess.pid_path.write_text("999999")
    # ProcessLookupError path returns True.
    assert sess.terminate_engine(wait_seconds=0.1) is True


def test_wait_for_port_timeout(tmp_path: Path) -> None:
    # Picking a (probably) closed port — returns False within timeout.
    assert session_mod.wait_for_port("127.0.0.1", 1, timeout=0.2) is False


def test_wait_for_port_succeeds() -> None:
    import socket as _socket

    srv = _socket.socket()
    srv.bind(("127.0.0.1", 0))
    srv.listen(1)
    port = srv.getsockname()[1]
    try:
        assert session_mod.wait_for_port("127.0.0.1", port, timeout=1.0) is True
    finally:
        srv.close()
