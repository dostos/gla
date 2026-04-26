"""``BrowserRunner`` — launch Chromium with the WebGL extension, poll for frames.

Phase 1 MVP per ``docs/superpowers/specs/2026-04-20-gpa-browser-eval-design.md``.

Design notes:

- Chromium is an external binary (no Python dep). Autodetection walks
  ``chromium``, ``chromium-browser``, ``google-chrome`` in that order.
- The launcher is **mockable**: ``BrowserRunOptions.launcher_fn`` accepts a
  ``Callable[[list[str]], subprocess.Popen]``. Defaults to :func:`spawn_chromium`.
  Unit tests inject a fake that writes a sentinel file + returns a stub popen.
- Static server: stdlib ``http.server`` on an ephemeral port, serving the
  *parent* of ``scenario_dir`` so the scenario is reachable at
  ``/<scenario_name>/index.html``.
- Completion signals (any one is sufficient):
    1. frame count > 0 AND at least one ``sources`` payload POSTed.
    2. annotations on *any* frame contain ``{"gpa_done": true}``.
    3. timeout.
"""

from __future__ import annotations

import http.server
import shutil
import socket
import socketserver
import subprocess
import threading
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from gpa.cli.session import Session


# --------------------------------------------------------------------------- #
# Errors
# --------------------------------------------------------------------------- #


class ChromiumNotFoundError(RuntimeError):
    """Raised when no chromium-compatible binary can be located."""


# --------------------------------------------------------------------------- #
# Chromium discovery / launch
# --------------------------------------------------------------------------- #


_CHROMIUM_CANDIDATES: List[str] = [
    "chromium",
    "chromium-browser",
    "google-chrome",
]


def autodetect_chromium(which: Optional[Callable[[str], Optional[str]]] = None) -> str:
    """Return an absolute path to a chromium-compatible binary.

    *which* is injectable for tests; defaults to :func:`shutil.which`.
    Raises :exc:`ChromiumNotFoundError` if nothing is found.
    """
    w = which if which is not None else shutil.which
    for cand in _CHROMIUM_CANDIDATES:
        path = w(cand)
        if path:
            return path
    raise ChromiumNotFoundError(
        "No chromium binary found on $PATH. Install one of: "
        + ", ".join(_CHROMIUM_CANDIDATES)
        + " (e.g. `apt install chromium-browser`)."
    )


def spawn_chromium(argv: List[str]) -> subprocess.Popen:
    """Default launcher: Popen with stdout muted, stderr captured to PIPE."""
    return subprocess.Popen(
        argv,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        stdin=subprocess.DEVNULL,
        close_fds=True,
    )


# --------------------------------------------------------------------------- #
# Static server
# --------------------------------------------------------------------------- #


class _QuietHandler(http.server.SimpleHTTPRequestHandler):
    """``SimpleHTTPRequestHandler`` that doesn't spam stderr for each request."""

    def log_message(self, *_args, **_kwargs) -> None:  # pragma: no cover - noise suppression
        return


class _ThreadingTCPServer(socketserver.ThreadingTCPServer):
    daemon_threads = True
    allow_reuse_address = True


def _start_static_server(
    serve_root: Path, port: int = 0
) -> "_StaticServerHandle":
    """Spin up a :mod:`http.server` thread rooted at *serve_root*.

    Returns a handle exposing ``port`` and ``shutdown()``. ``port=0`` picks
    an ephemeral port.
    """
    root_str = str(serve_root.resolve())

    def _handler_factory(*args, **kwargs):
        # Directory kwarg requires Python 3.7+.
        return _QuietHandler(*args, directory=root_str, **kwargs)

    server = _ThreadingTCPServer(("127.0.0.1", port), _handler_factory)
    actual_port = server.server_address[1]
    thread = threading.Thread(
        target=server.serve_forever, name=f"gpa-static-{actual_port}", daemon=True
    )
    thread.start()
    return _StaticServerHandle(server=server, thread=thread, port=actual_port)


@dataclass
class _StaticServerHandle:
    server: socketserver.TCPServer
    thread: threading.Thread
    port: int

    def shutdown(self) -> None:
        try:
            self.server.shutdown()
            self.server.server_close()
        except Exception:  # pragma: no cover - best-effort
            pass


# --------------------------------------------------------------------------- #
# Options / result
# --------------------------------------------------------------------------- #


@dataclass
class BrowserRunOptions:
    scenario_name: str
    scenario_dir: Path
    extension_dir: Path
    session: Session
    chromium_path: Optional[str] = None
    timeout_sec: int = 30
    keep_open: bool = False
    launcher_fn: Optional[Callable[[List[str]], subprocess.Popen]] = None
    static_port: int = 0  # 0 → ephemeral
    # Internals — mostly for tests.
    poll_interval_sec: float = 0.25


@dataclass
class BrowserRunResult:
    scenario_name: str
    frames_captured: int
    sources_captured: int
    timed_out: bool
    chromium_exit_code: Optional[int]
    duration_sec: float
    static_port: int
    url: str = ""
    gpa_done: bool = False


# --------------------------------------------------------------------------- #
# Runner
# --------------------------------------------------------------------------- #


class BrowserRunner:
    """Launch Chromium, serve the scenario, poll for capture completion."""

    def run(self, opts: BrowserRunOptions) -> BrowserRunResult:
        started = time.monotonic()

        # 1. Resolve chromium binary (autodetect if not supplied).
        chromium_path = opts.chromium_path or autodetect_chromium()

        # 2. Static server rooted at the parent of scenario_dir so the URL
        #    is http://localhost:<port>/<scenario_name>/index.html.
        serve_root = opts.scenario_dir.parent.resolve()
        static = _start_static_server(serve_root, port=opts.static_port)

        token = opts.session.read_token()
        engine_port = opts.session.read_port()
        url = (
            f"http://127.0.0.1:{static.port}/{opts.scenario_name}/index.html"
            f"?token={token}&port={engine_port}"
        )

        # 3. Build chromium argv. Ext-load + swiftshader; --headless=new
        # only when no DISPLAY (real extension content scripts require a
        # windowed run, see _build_chromium_argv comment).
        import tempfile as _tempfile
        user_data_dir = Path(_tempfile.mkdtemp(
            prefix=f"gpa-chrome-{opts.scenario_name}-",
        ))
        argv = self._build_chromium_argv(
            chromium_path=chromium_path,
            extension_dir=opts.extension_dir,
            url=url,
            user_data_dir=user_data_dir,
        )

        launcher = opts.launcher_fn or spawn_chromium
        proc = launcher(argv)

        frames_captured = 0
        sources_captured = 0
        timed_out = False
        gpa_done = False
        chromium_exit_code: Optional[int] = None

        try:
            # 4. Poll engine + annotations.
            deadline = started + opts.timeout_sec
            while time.monotonic() < deadline:
                # Check: did chromium die unexpectedly?
                rc = proc.poll()
                if rc is not None and rc != 0 and frames_captured == 0:
                    # Give the engine a moment to process any already-queued
                    # frames, but don't block forever.
                    chromium_exit_code = rc
                    break

                status = self._poll_status(opts.session)
                frames_captured = max(frames_captured, status["frame_count"])
                sources_captured = max(sources_captured, status["sources_count"])
                gpa_done = gpa_done or status["gpa_done"]

                if gpa_done:
                    break
                if frames_captured > 0 and sources_captured > 0:
                    break
                # Phase 1 MVP scenarios POST only trace-sources (no real
                # GL frames). Accept sources-only as a successful boot.
                if sources_captured > 0:
                    break

                time.sleep(opts.poll_interval_sec)
            else:
                timed_out = True

            if not timed_out and chromium_exit_code is None:
                # Normal exit path: the while loop broke out.
                pass
            elif timed_out:
                # One final status poll so we return the latest counts.
                status = self._poll_status(opts.session)
                frames_captured = max(frames_captured, status["frame_count"])
                sources_captured = max(sources_captured, status["sources_count"])

        finally:
            # 5. Teardown.
            if not opts.keep_open:
                chromium_exit_code = self._terminate_chromium(proc)
            else:
                # Record current exit code if already dead, else leave None.
                chromium_exit_code = proc.poll()
            static.shutdown()
            # Best-effort: drop the per-run profile dir.
            if not opts.keep_open:
                import shutil as _shutil
                try:
                    _shutil.rmtree(user_data_dir, ignore_errors=True)
                except Exception:
                    pass

        duration = time.monotonic() - started
        return BrowserRunResult(
            scenario_name=opts.scenario_name,
            frames_captured=frames_captured,
            sources_captured=sources_captured,
            timed_out=timed_out,
            chromium_exit_code=chromium_exit_code,
            duration_sec=duration,
            static_port=static.port,
            url=url,
            gpa_done=gpa_done,
        )

    # ------------------------------------------------------------------ #
    # Internals
    # ------------------------------------------------------------------ #

    @staticmethod
    def _build_chromium_argv(
        *, chromium_path: str, extension_dir: Path, url: str,
        user_data_dir: Optional[Path] = None,
    ) -> List[str]:
        ext = str(extension_dir.resolve())
        # Chromium MV3 extensions do NOT load in any --headless mode
        # (neither the legacy nor --headless=new; chrome.runtime is
        # undefined inside content scripts). For scenarios that depend
        # on the WebGL extension's content scripts (gpa-trace.js,
        # interceptor.js) we MUST run a real window. When a DISPLAY is
        # set (Xvfb is fine) we drop --headless and run windowed; when
        # there is no DISPLAY we fall back to --headless=new and accept
        # that extension-only features won't activate.
        import os as _os
        use_headless = not _os.environ.get("DISPLAY")
        argv: List[str] = [chromium_path]
        if use_headless:
            argv.append("--headless=new")
        argv.extend([
            "--no-sandbox",
            "--disable-gpu-sandbox",
            "--enable-unsafe-swiftshader",
            "--use-gl=swiftshader",
            f"--load-extension={ext}",
            f"--disable-extensions-except={ext}",
            "--no-first-run",
            "--no-default-browser-check",
            "--window-size=320,240",
        ])
        if user_data_dir is not None:
            argv.append(f"--user-data-dir={user_data_dir}")
        argv.append(url)
        return argv

    @staticmethod
    def _terminate_chromium(proc: subprocess.Popen) -> Optional[int]:
        """SIGTERM, wait 3s, then SIGKILL. Returns final exit code."""
        rc = proc.poll()
        if rc is not None:
            return rc
        try:
            proc.terminate()
        except Exception:
            pass
        try:
            return proc.wait(timeout=3.0)
        except subprocess.TimeoutExpired:
            try:
                proc.kill()
            except Exception:
                pass
            try:
                return proc.wait(timeout=2.0)
            except subprocess.TimeoutExpired:
                return None

    @staticmethod
    def _poll_status(session: Session) -> Dict[str, Any]:
        """Return ``{frame_count, sources_count, gpa_done}`` from the engine.

        All network errors are swallowed and returned as zeros — the
        engine may still be warming up.
        """
        try:
            port = session.read_port()
            token = session.read_token()
        except Exception:
            return {"frame_count": 0, "sources_count": 0, "gpa_done": False}

        base = f"http://127.0.0.1:{port}/api/v1"
        headers = {"Authorization": f"Bearer {token}"}

        frame_count = 0
        sources_count = 0
        gpa_done = False

        # --- Frame count (and latest id if any) --------------------------- #
        latest_id: Optional[int] = None
        try:
            import json

            req = urllib.request.Request(f"{base}/frames", headers=headers)
            with urllib.request.urlopen(req, timeout=0.5) as resp:
                data = json.loads(resp.read())
            if isinstance(data, dict) and "frames" in data and isinstance(
                data["frames"], list
            ):
                frames_list = data["frames"]
                frame_count = len(frames_list)
                if frames_list:
                    # frames may be ints or dicts with 'id'
                    last = frames_list[-1]
                    if isinstance(last, dict):
                        latest_id = last.get("id") or last.get("frame_id")
                    elif isinstance(last, int):
                        latest_id = last
            elif isinstance(data, list):
                frame_count = len(data)
                if data:
                    last = data[-1]
                    if isinstance(last, dict):
                        latest_id = last.get("id") or last.get("frame_id")
                    elif isinstance(last, int):
                        latest_id = last
        except (urllib.error.URLError, OSError, ValueError):
            pass

        # --- Sources count --------------------------------------------------
        # The trace-store has no public "count" endpoint and scenarios may
        # POST to frame_id=0 before any capture-driven frame exists. Probe a
        # short range of frame ids (0..8) on dc 0; any 200 → we have data.
        # Also probe the latest captured frame id if the /frames listing
        # reported one.
        probe_ids = list(range(9))
        if latest_id is not None and latest_id not in probe_ids:
            probe_ids.append(latest_id)
        for fid in probe_ids:
            try:
                import json

                req = urllib.request.Request(
                    f"{base}/frames/{fid}/drawcalls/0/sources",
                    headers=headers,
                )
                with urllib.request.urlopen(req, timeout=0.3) as resp:
                    if resp.status == 200:
                        data = json.loads(resp.read())
                        if isinstance(data, dict) and data:
                            sources_count = max(sources_count, 1)
                            break
            except (urllib.error.URLError, OSError, ValueError):
                continue

        # --- gpa_done annotation probe ------------------------------------ #
        if latest_id is not None:
            try:
                import json

                req = urllib.request.Request(
                    f"{base}/frames/{latest_id}/annotations",
                    headers=headers,
                )
                with urllib.request.urlopen(req, timeout=0.5) as resp:
                    data = json.loads(resp.read())
                # Annotations can be list of {key, value} or dict
                if isinstance(data, dict):
                    if data.get("gpa_done") is True:
                        gpa_done = True
                    ann = data.get("annotations")
                    if isinstance(ann, dict) and ann.get("gpa_done") is True:
                        gpa_done = True
                    elif isinstance(ann, list):
                        for entry in ann:
                            if (
                                isinstance(entry, dict)
                                and entry.get("key") == "gpa_done"
                                and entry.get("value") in (True, "true", 1, "1")
                            ):
                                gpa_done = True
                                break
            except (urllib.error.URLError, OSError, ValueError):
                pass

        return {
            "frame_count": frame_count,
            "sources_count": sources_count,
            "gpa_done": gpa_done,
        }
