"""``gpa start`` — create a session and spawn the engine daemon."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from typing import Optional

from gpa.cli.session import Session, SessionExistsError, wait_for_port


def _spawn_engine(sess: Session, *, daemon: bool) -> subprocess.Popen:
    """Spawn ``python -m gpa.launcher`` bound to ``sess`` and return the Popen.

    When ``daemon`` is true, the child is started in its own session so it
    outlives this process.  Otherwise it inherits our process group so it
    dies with us (used by ``gpa run``).
    """
    cmd = [
        sys.executable,
        "-m",
        "gpa.launcher",
        "--socket",
        str(sess.socket_path),
        "--shm",
        sess.read_shm_name(),
        "--port",
        str(sess.read_port()),
        "--token",
        sess.read_token(),
    ]
    log_file = open(sess.log_path, "ab")
    popen_kwargs = {
        "stdout": log_file,
        "stderr": log_file,
        "stdin": subprocess.DEVNULL,
        "close_fds": True,
    }
    if daemon:
        popen_kwargs["start_new_session"] = True
    proc = subprocess.Popen(cmd, **popen_kwargs)
    sess.pid_path.write_text(str(proc.pid))
    return proc


def run(
    session_dir: Optional[Path] = None,
    *,
    daemon: bool = True,
    port: int = 18080,
    print_stream=None,
) -> int:
    """Implement ``gpa start``.  Returns the process exit code."""
    if print_stream is None:
        print_stream = sys.stdout

    try:
        sess = Session.create(dir=session_dir, port=port)
    except SessionExistsError as exc:
        print(f"[gpa] {exc}", file=sys.stderr)
        return 1

    try:
        _spawn_engine(sess, daemon=daemon)
    except Exception as exc:  # pragma: no cover - defensive
        print(f"[gpa] failed to spawn engine: {exc}", file=sys.stderr)
        sess.cleanup()
        return 1

    ready = wait_for_port("127.0.0.1", sess.read_port(), timeout=3.0)
    if not ready:
        print(
            f"[gpa] engine did not become ready on port {sess.read_port()} "
            f"within 3s; see {sess.log_path}",
            file=sys.stderr,
        )
        sess.terminate_engine()
        sess.cleanup()
        return 1

    sess.mark_current()
    print(f"# gpa session: {sess.dir}", file=print_stream)
    print_stream.write(sess.env_exports())
    print_stream.flush()
    return 0
