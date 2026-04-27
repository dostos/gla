"""Unit tests for ``gpa.browser.runner`` (Phase 1 MVP).

Chromium is not installed on the dev machine, so every test here mocks
the launcher. The goal is to exercise the orchestration — argv
construction, autodetection, polling, teardown — without any real
browser.
"""

from __future__ import annotations

import subprocess
import threading
import time
import types
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from gpa.browser.runner import (
    BrowserRunOptions,
    BrowserRunner,
    ChromiumNotFoundError,
    autodetect_chromium,
    spawn_chromium,
)
from gpa.cli.session import Session


# --------------------------------------------------------------------------- #
# Fakes
# --------------------------------------------------------------------------- #


class _StubProc:
    """Minimal subprocess.Popen stand-in."""

    def __init__(self, *, exit_code=None, alive=True):
        self._alive = alive
        self._exit_code = exit_code
        self.terminated = False
        self.killed = False

    def poll(self):
        return None if self._alive else self._exit_code

    def terminate(self):
        self.terminated = True
        self._alive = False
        if self._exit_code is None:
            self._exit_code = 0

    def kill(self):
        self.killed = True
        self._alive = False
        if self._exit_code is None:
            self._exit_code = -9

    def wait(self, timeout=None):
        self._alive = False
        if self._exit_code is None:
            self._exit_code = 0
        return self._exit_code


def _make_session(tmp_path: Path, port: int = 18080) -> Session:
    return Session.create(dir=tmp_path / "sess", port=port)


def _make_opts(
    tmp_path: Path,
    *,
    launcher_fn=None,
    timeout_sec=1,
    keep_open=False,
    chromium_path="/fake/chromium",
) -> BrowserRunOptions:
    scen_root = tmp_path / "eval-browser"
    scen_dir = scen_root / "r21_stub"
    scen_dir.mkdir(parents=True)
    (scen_dir / "index.html").write_text("<html></html>")
    ext_dir = tmp_path / "extension"
    ext_dir.mkdir()
    (ext_dir / "manifest.json").write_text("{}")
    sess = _make_session(tmp_path)
    return BrowserRunOptions(
        scenario_name="r21_stub",
        scenario_dir=scen_dir,
        extension_dir=ext_dir,
        session=sess,
        chromium_path=chromium_path,
        timeout_sec=timeout_sec,
        keep_open=keep_open,
        launcher_fn=launcher_fn,
        poll_interval_sec=0.05,
    )


# --------------------------------------------------------------------------- #
# Autodetection
# --------------------------------------------------------------------------- #


def test_runner_autodetects_chromium_from_path():
    """First non-None result from shutil.which wins."""
    calls = []

    def fake_which(name):
        calls.append(name)
        if name == "chromium":
            return None
        if name == "chromium-browser":
            return "/usr/bin/chromium-browser"
        return "/usr/bin/google-chrome"

    path = autodetect_chromium(which=fake_which)
    assert path == "/usr/bin/chromium-browser"
    # chromium is tried before chromium-browser
    assert calls[:2] == ["chromium", "chromium-browser"]


def test_runner_raises_if_chromium_not_found():
    with pytest.raises(ChromiumNotFoundError) as ei:
        autodetect_chromium(which=lambda _n: None)
    assert "install" in str(ei.value).lower() or "chromium" in str(ei.value).lower()


# --------------------------------------------------------------------------- #
# Launcher injection
# --------------------------------------------------------------------------- #


def test_runner_launches_via_injected_fn(tmp_path):
    """A mock launcher_fn is called with a correct chromium argv."""
    captured_argv = []
    sentinel = tmp_path / "fake-chromium-fired"

    def mock_launcher(argv):
        captured_argv.append(argv)
        sentinel.write_text("\n".join(argv))
        return _StubProc(alive=True)

    opts = _make_opts(tmp_path, launcher_fn=mock_launcher,
                      timeout_sec=1)

    # Stub the polling so it returns nothing → runner will timeout quickly.
    with patch.object(BrowserRunner, "_poll_status",
                      return_value={"frame_count": 0,
                                    "sources_count": 0,
                                    "gpa_done": False}):
        runner = BrowserRunner()
        result = runner.run(opts)

    assert sentinel.exists()
    assert len(captured_argv) == 1
    argv = captured_argv[0]
    assert argv[0] == "/fake/chromium"
    assert any(a.startswith("--load-extension=") for a in argv)
    assert "--enable-unsafe-swiftshader" in argv
    # URL is the last arg; should include scenario + token query
    url = argv[-1]
    assert "/r21_stub/index.html" in url
    assert "token=" in url
    assert "port=" in url
    # It timed out (poll returned zeros throughout).
    assert result.timed_out is True


# --------------------------------------------------------------------------- #
# Polling → completion
# --------------------------------------------------------------------------- #


def test_runner_polls_until_frame_captured(tmp_path):
    """After some polls return zeros, the runner sees a frame + sources."""
    calls = {"n": 0}

    def fake_poll(self, session):  # noqa: ARG001
        calls["n"] += 1
        if calls["n"] < 3:
            return {"frame_count": 0, "sources_count": 0, "gpa_done": False}
        return {"frame_count": 1, "sources_count": 1, "gpa_done": False}

    proc = _StubProc(alive=True)

    def launcher(argv):  # noqa: ARG001
        return proc

    opts = _make_opts(tmp_path, launcher_fn=launcher, timeout_sec=5)
    with patch.object(BrowserRunner, "_poll_status", new=fake_poll):
        result = BrowserRunner().run(opts)

    assert result.timed_out is False
    assert result.frames_captured == 1
    assert result.sources_captured == 1
    # Chromium was terminated (keep_open default False).
    assert proc.terminated is True


def test_runner_times_out(tmp_path):
    """With no frames ever captured, runner returns timed_out=True."""
    proc = _StubProc(alive=True)

    def launcher(argv):  # noqa: ARG001
        return proc

    opts = _make_opts(tmp_path, launcher_fn=launcher, timeout_sec=1)
    started = time.monotonic()
    with patch.object(BrowserRunner, "_poll_status",
                      return_value={"frame_count": 0,
                                    "sources_count": 0,
                                    "gpa_done": False}):
        result = BrowserRunner().run(opts)
    elapsed = time.monotonic() - started

    assert result.timed_out is True
    assert result.frames_captured == 0
    # Bounded by roughly timeout_sec + a small teardown grace.
    assert elapsed < 3.0


def test_runner_completes_on_gpa_done(tmp_path):
    """gpa_done annotation alone ends the poll loop."""
    polls = {"n": 0}

    def fake_poll(self, session):  # noqa: ARG001
        polls["n"] += 1
        if polls["n"] == 1:
            return {"frame_count": 0, "sources_count": 0, "gpa_done": False}
        return {"frame_count": 0, "sources_count": 0, "gpa_done": True}

    proc = _StubProc(alive=True)

    def launcher(argv):  # noqa: ARG001
        return proc

    opts = _make_opts(tmp_path, launcher_fn=launcher, timeout_sec=5)
    with patch.object(BrowserRunner, "_poll_status", new=fake_poll):
        result = BrowserRunner().run(opts)

    assert result.gpa_done is True
    assert result.timed_out is False


# --------------------------------------------------------------------------- #
# Teardown
# --------------------------------------------------------------------------- #


def test_runner_tears_down_chromium_on_exit(tmp_path):
    proc = _StubProc(alive=True)

    def launcher(argv):  # noqa: ARG001
        return proc

    opts = _make_opts(tmp_path, launcher_fn=launcher,
                      timeout_sec=1, keep_open=False)
    with patch.object(BrowserRunner, "_poll_status",
                      return_value={"frame_count": 0,
                                    "sources_count": 0,
                                    "gpa_done": False}):
        BrowserRunner().run(opts)

    assert proc.terminated is True


def test_runner_keeps_chromium_open_when_requested(tmp_path):
    proc = _StubProc(alive=True)

    def launcher(argv):  # noqa: ARG001
        return proc

    opts = _make_opts(tmp_path, launcher_fn=launcher,
                      timeout_sec=1, keep_open=True)
    with patch.object(BrowserRunner, "_poll_status",
                      return_value={"frame_count": 0,
                                    "sources_count": 0,
                                    "gpa_done": False}):
        BrowserRunner().run(opts)

    assert proc.terminated is False


# --------------------------------------------------------------------------- #
# spawn_chromium (the default launcher) — sanity shape
# --------------------------------------------------------------------------- #


def test_spawn_chromium_uses_subprocess_popen(tmp_path):
    """spawn_chromium calls subprocess.Popen with DEVNULL stdout."""
    captured = {}

    class FakePopen:
        def __init__(self, argv, **kwargs):
            captured["argv"] = argv
            captured["kwargs"] = kwargs

    with patch("gpa.browser.runner.subprocess.Popen", FakePopen):
        spawn_chromium(["/bin/true", "--foo"])

    assert captured["argv"] == ["/bin/true", "--foo"]
    assert captured["kwargs"]["stdout"] == subprocess.DEVNULL
    assert captured["kwargs"]["stderr"] == subprocess.PIPE


# --------------------------------------------------------------------------- #
# Static-server plugin-alias mount
# --------------------------------------------------------------------------- #


def test_static_server_serves_plugin_alias(tmp_path):
    """`_start_static_server(extra_files=…)` exposes off-tree files at fixed URLs.

    Used by ``BrowserRunner`` to ship the three.js link plugin (which lives
    in ``src/python/gpa/framework/`` rather than under any scenario dir).
    """
    import urllib.request

    from gpa.browser.runner import _start_static_server

    # Prepare a serve_root that does NOT contain the plugin file.
    serve_root = tmp_path / "serve"
    serve_root.mkdir()
    (serve_root / "index.html").write_text("<html>hi</html>")

    plugin_src = tmp_path / "framework" / "threejs_link_plugin.js"
    plugin_src.parent.mkdir()
    plugin_body = "// plugin under test\nexport const x = 1;\n"
    plugin_src.write_text(plugin_body)

    handle = _start_static_server(
        serve_root,
        port=0,
        extra_files={"/_plugins/threejs-link.js": plugin_src},
    )
    try:
        # 1) Alias path returns the plugin verbatim with JS content-type.
        url = f"http://127.0.0.1:{handle.port}/_plugins/threejs-link.js"
        with urllib.request.urlopen(url, timeout=2.0) as resp:
            data = resp.read().decode()
            ctype = resp.headers.get("Content-Type", "")
        assert data == plugin_body
        assert "javascript" in ctype

        # 2) Regular files in serve_root still work (no alias swallow).
        url2 = f"http://127.0.0.1:{handle.port}/index.html"
        with urllib.request.urlopen(url2, timeout=2.0) as resp:
            assert b"<html>hi</html>" in resp.read()
    finally:
        handle.shutdown()
