"""Session model for the ``gpa`` CLI.

A *session* is a directory on disk holding all state for one engine instance:

    <dir>/
        socket       (unix socket the shim talks to, created by the engine)
        shm-name     (text file: POSIX /shm name the engine owns)
        token        (32-hex-char bearer token, chmod 0600)
        port         (text file: REST port the engine listens on)
        engine.pid   (text file: pid of the engine subprocess)
        engine.log   (stdout/stderr of the engine subprocess)

Single-session MVP: the most-recently-created session is pointed to by a
symlink at ``/tmp/gpa-session-current``.  Multi-session use requires setting
``$GPA_SESSION`` explicitly.
"""

from __future__ import annotations

import os
import secrets
import signal
import socket
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional


CURRENT_SESSION_LINK = "/tmp/gpa-session-current"

# Filenames that, if present in a directory, indicate an active or recent
# session lives there.  ``Session.create`` refuses to clobber any of these.
_SESSION_ARTIFACT_NAMES = (
    "engine.pid",
    "token",
    "shm-name",
    "socket",
    "engine.log",
    "port",
)


class SessionExistsError(FileExistsError):
    """Raised when ``Session.create`` is asked to use a dir already holding a session."""


@dataclass
class Session:
    """Filesystem-backed session directory.

    Use ``Session.create()`` to allocate a fresh session, or
    ``Session.discover()`` to load an existing one.
    """

    dir: Path

    # ----- Path accessors -------------------------------------------------

    @property
    def socket_path(self) -> Path:
        return self.dir / "socket"

    @property
    def shm_name_path(self) -> Path:
        return self.dir / "shm-name"

    @property
    def token_path(self) -> Path:
        return self.dir / "token"

    @property
    def port_path(self) -> Path:
        return self.dir / "port"

    @property
    def pid_path(self) -> Path:
        return self.dir / "engine.pid"

    @property
    def log_path(self) -> Path:
        return self.dir / "engine.log"

    # ----- File reads ------------------------------------------------------

    def read_token(self) -> str:
        return self.token_path.read_text().strip()

    def read_shm_name(self) -> str:
        return self.shm_name_path.read_text().strip()

    def read_port(self) -> int:
        return int(self.port_path.read_text().strip())

    def read_pid(self) -> Optional[int]:
        if not self.pid_path.exists():
            return None
        txt = self.pid_path.read_text().strip()
        return int(txt) if txt else None

    # ----- Env-export block -----------------------------------------------

    def env_exports(self) -> str:
        """Return shell-eval-able export statements for connecting a shim.

        Intentionally emits both the GPA_* names which the shim
        currently reads) and the user-facing ``GPA_*`` names from the spec.
        """
        token = self.read_token()
        shm = self.read_shm_name()
        port = self.read_port()
        sock = str(self.socket_path)
        lines = [
            f"export GPA_SESSION={self.dir}",
            f"export GPA_SOCKET_PATH={sock}",
            f"export GPA_SHM_NAME={shm}",
            f"export GPA_TOKEN={token}",
            f"export GPA_PORT={port}",
            # Legacy names for the existing shim / launcher.
            f"export GPA_SOCKET_PATH={sock}",
            f"export GPA_SHM_NAME={shm}",
            f"export GPA_TOKEN={token}",
        ]
        return "\n".join(lines) + "\n"

    def child_env(self, base: Optional[dict] = None) -> dict:
        """Return an env dict to launch a child under this session."""
        env = dict(base if base is not None else os.environ)
        env["GPA_SESSION"] = str(self.dir)
        env["GPA_SOCKET_PATH"] = str(self.socket_path)
        env["GPA_SHM_NAME"] = self.read_shm_name()
        env["GPA_TOKEN"] = self.read_token()
        env["GPA_PORT"] = str(self.read_port())
        # Shim-side names (what the C shim actually reads today).
        env["GPA_SOCKET_PATH"] = str(self.socket_path)
        env["GPA_SHM_NAME"] = self.read_shm_name()
        env["GPA_TOKEN"] = self.read_token()
        return env

    # ----- Lifecycle ------------------------------------------------------

    @classmethod
    def create(
        cls,
        dir: Optional[Path] = None,
        *,
        port: int = 18080,
        shm_name: Optional[str] = None,
    ) -> "Session":
        """Allocate a new session directory and seed token/shm-name/port.

        Idempotent for **empty** or **safe** existing directories:

        * ``dir`` does not exist  -> created.
        * ``dir`` exists & empty  -> reused.
        * ``dir`` exists & has unrelated files (no session artifacts) -> reused.
        * ``dir`` exists & holds session artifacts -> raises ``SessionExistsError``.

        Does *not* start the engine — callers must do so and write
        ``engine.pid`` themselves.
        """
        if dir is None:
            uid = os.getuid()
            ts = time.time_ns()
            dir = Path(f"/tmp/gpa-session-{uid}-{ts}")

        dir = Path(dir)

        if dir.exists():
            if not dir.is_dir():
                raise SessionExistsError(
                    f"{dir} exists and is not a directory."
                )
            existing = _existing_session_artifacts(dir)
            if existing:
                names = ", ".join(sorted(existing))
                raise SessionExistsError(
                    f"Session already exists at {dir} (found: {names}). "
                    f"Use `gpa stop --session {dir}` first, or pick a different path."
                )
            # Safe to reuse: empty or only contains unrelated files.
        else:
            dir.mkdir(parents=True, exist_ok=False)

        sess = cls(dir=dir)

        token = secrets.token_hex(16)  # 32 hex chars
        sess.token_path.write_text(token)
        os.chmod(sess.token_path, 0o600)

        if shm_name is None:
            shm_name = f"/gpa-{os.getuid()}-{time.time_ns()}"
        sess.shm_name_path.write_text(shm_name)

        sess.port_path.write_text(str(port))
        return sess

    @classmethod
    def discover(cls, explicit: Optional[Path] = None) -> Optional["Session"]:
        """Find the active session.

        Resolution order:
          1. ``explicit`` argument (from ``--session``)
          2. ``$GPA_SESSION`` env var
          3. ``/tmp/gpa-session-current`` symlink
        """
        candidate: Optional[Path] = None
        if explicit is not None:
            candidate = Path(explicit)
        elif os.environ.get("GPA_SESSION"):
            candidate = Path(os.environ["GPA_SESSION"])
        elif os.path.islink(CURRENT_SESSION_LINK) or os.path.exists(CURRENT_SESSION_LINK):
            try:
                candidate = Path(os.readlink(CURRENT_SESSION_LINK))
            except OSError:
                return None

        if candidate is None or not candidate.is_dir():
            return None
        sess = cls(dir=candidate)
        if not sess.token_path.exists():
            return None
        return sess

    def mark_current(self) -> None:
        """Point the ``/tmp/gpa-session-current`` symlink at this session."""
        try:
            if os.path.islink(CURRENT_SESSION_LINK) or os.path.exists(CURRENT_SESSION_LINK):
                os.unlink(CURRENT_SESSION_LINK)
        except OSError:
            pass
        try:
            os.symlink(str(self.dir), CURRENT_SESSION_LINK)
        except OSError:
            # Non-fatal: session is still usable via --session / $GPA_SESSION.
            pass

    # ----- Teardown -------------------------------------------------------

    def terminate_engine(self, *, wait_seconds: float = 3.0) -> bool:
        """SIGTERM the engine pid; SIGKILL if still alive after ``wait_seconds``.

        Returns True if the engine was (or is) stopped, False if no pid was
        recorded.
        """
        pid = self.read_pid()
        if pid is None:
            return False
        try:
            os.kill(pid, signal.SIGTERM)
        except ProcessLookupError:
            return True
        except PermissionError:
            return False

        deadline = time.monotonic() + wait_seconds
        while time.monotonic() < deadline:
            try:
                os.kill(pid, 0)
            except ProcessLookupError:
                return True
            time.sleep(0.1)

        try:
            os.kill(pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        return True

    def cleanup(self) -> None:
        """Remove socket, shared-memory segment, session dir, and current link."""
        # Socket (created by the engine; may or may not exist).
        try:
            if self.socket_path.exists() or self.socket_path.is_symlink():
                self.socket_path.unlink()
        except OSError:
            pass

        # POSIX shared memory.
        try:
            shm = self.read_shm_name()
        except FileNotFoundError:
            shm = None
        if shm:
            shm_fs = Path("/dev/shm") / shm.lstrip("/")
            try:
                if shm_fs.exists():
                    shm_fs.unlink()
            except OSError:
                pass

        # current-session symlink, only if it still points here.
        try:
            link_target = os.readlink(CURRENT_SESSION_LINK)
            if Path(link_target) == self.dir:
                os.unlink(CURRENT_SESSION_LINK)
        except OSError:
            pass

        # Session directory contents.
        if self.dir.exists():
            for child in self.dir.iterdir():
                try:
                    child.unlink()
                except OSError:
                    pass
            try:
                self.dir.rmdir()
            except OSError:
                pass


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #


def _existing_session_artifacts(dir: Path) -> list:
    """Return the subset of session-artifact filenames already present in ``dir``.

    A non-empty result means the directory already hosts a session and must
    not be clobbered by ``Session.create``.
    """
    found: list = []
    for name in _SESSION_ARTIFACT_NAMES:
        if (dir / name).exists() or (dir / name).is_symlink():
            found.append(name)
    return found


def find_free_port() -> int:
    """Bind an ephemeral port, then close — caller races to claim it.

    Best-effort helper for ``gpa start --port 0``.  There is an unavoidable
    race between this returning and the engine binding the port; callers must
    surface the underlying bind error if it loses.
    """
    s = socket.socket()
    try:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]
    finally:
        s.close()


# --------------------------------------------------------------------------- #
# Readiness helpers
# --------------------------------------------------------------------------- #


def wait_for_port(host: str, port: int, timeout: float = 3.0) -> bool:
    """Return True once ``host:port`` accepts a TCP connection, False on timeout."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            with socket.create_connection((host, port), timeout=0.25):
                return True
        except OSError:
            time.sleep(0.1)
    return False
