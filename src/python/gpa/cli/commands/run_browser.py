"""``gpa run-browser`` — run a browser-mode eval scenario.

Phase 1 MVP: launches Chromium with the WebGL extension against a scenario
HTML page and polls the engine for captured frames + reflection sources.

Exit codes:
  0 clean run (frames captured or gpa_done)
  1 generic error (scenario not found, missing index.html, etc.)
  2 no session could be created or discovered
  4 timed out with zero frames captured
  5 chromium binary not found
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Optional

from gpa.browser import (
    BrowserRunner,
    BrowserRunOptions,
    BrowserRunResult,
    ChromiumNotFoundError,
)
from gpa.cli.commands.start import _spawn_engine
from gpa.cli.session import Session, wait_for_port


DEFAULT_SCENARIO_ROOT = Path("tests/eval-browser")
DEFAULT_EXTENSION_DIR = Path("src/shims/webgl/extension")


def _resolve_scenario_dir(name: str, *, root: Optional[Path] = None) -> Path:
    root = root or Path(os.environ.get("GPA_BROWSER_SCENARIO_ROOT",
                                       str(DEFAULT_SCENARIO_ROOT)))
    return (root / name).resolve()


def _resolve_extension_dir() -> Path:
    return Path(os.environ.get(
        "GPA_BROWSER_EXTENSION_DIR", str(DEFAULT_EXTENSION_DIR)
    )).resolve()


def run(
    *,
    scenario: str,
    timeout: int = 30,
    chromium_path: Optional[str] = None,
    keep_open: bool = False,
    session_dir: Optional[Path] = None,
    port: int = 18080,
    runner: Optional[BrowserRunner] = None,
    print_stream=None,
) -> int:
    """Implement ``gpa run-browser``."""
    if print_stream is None:
        print_stream = sys.stderr

    # ---- Scenario validation -------------------------------------------- #
    scenario_dir = _resolve_scenario_dir(scenario)
    if not scenario_dir.is_dir():
        print(
            f"[gpa] scenario not found: {scenario!r} (looked in {scenario_dir})",
            file=print_stream,
        )
        return 1

    index_html = scenario_dir / "index.html"
    if not index_html.exists():
        print(
            f"[gpa] scenario {scenario!r}: missing index.html at {index_html}",
            file=print_stream,
        )
        return 1

    extension_dir = _resolve_extension_dir()
    if not extension_dir.is_dir():
        print(
            f"[gpa] extension dir not found: {extension_dir}",
            file=print_stream,
        )
        return 1

    # ---- Session (create or discover) ----------------------------------- #
    sess: Optional[Session]
    owns_session = False
    if session_dir is not None:
        sess = Session.discover(session_dir) or Session(dir=session_dir)
        if not sess.token_path.exists():
            print(
                f"[gpa] session dir has no token: {session_dir}",
                file=print_stream,
            )
            return 2
    else:
        sess = Session.discover()
        if sess is None:
            try:
                sess = Session.create(port=port)
            except Exception as exc:
                print(f"[gpa] failed to create session: {exc}",
                      file=print_stream)
                return 2
            try:
                _spawn_engine(sess, daemon=False)
            except Exception as exc:
                print(f"[gpa] failed to spawn engine: {exc}",
                      file=print_stream)
                sess.cleanup()
                return 1
            if not wait_for_port("127.0.0.1", sess.read_port(), timeout=3.0):
                print(
                    f"[gpa] engine did not become ready; see {sess.log_path}",
                    file=print_stream,
                )
                sess.terminate_engine()
                sess.cleanup()
                return 1
            sess.mark_current()
            owns_session = True

    assert sess is not None
    print(f"[gpa] session {sess.dir}", file=print_stream)

    # ---- Invoke runner -------------------------------------------------- #
    opts = BrowserRunOptions(
        scenario_name=scenario,
        scenario_dir=scenario_dir,
        extension_dir=extension_dir,
        session=sess,
        chromium_path=chromium_path,
        timeout_sec=timeout,
        keep_open=keep_open,
    )

    r = runner or BrowserRunner()
    result: Optional[BrowserRunResult] = None
    rc = 0
    try:
        try:
            result = r.run(opts)
        except ChromiumNotFoundError as exc:
            print(f"[gpa] {exc}", file=print_stream)
            rc = 5
            return rc
        except FileNotFoundError as exc:
            print(f"[gpa] {exc}", file=print_stream)
            rc = 1
            return rc

        # ---- Summary + exit code -------------------------------------- #
        print(
            f"[gpa] scenario={result.scenario_name} "
            f"frames={result.frames_captured} "
            f"sources={result.sources_captured} "
            f"gpa_done={result.gpa_done} "
            f"timed_out={result.timed_out} "
            f"duration={result.duration_sec:.1f}s",
            file=print_stream,
        )

        if result.timed_out and result.frames_captured == 0:
            rc = 4
        else:
            rc = 0
        return rc
    finally:
        if owns_session and not keep_open:
            sess.terminate_engine()
            sess.cleanup()
