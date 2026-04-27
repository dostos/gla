"""Tests for the ``python -m gpa`` module entry point.

Asserts that ``python -m gpa`` dispatches to the user-facing CLI
(``gpa.cli.main.main``), not the engine launcher.  The engine launcher
remains independently accessible at ``python -m gpa.launcher``.
"""

from __future__ import annotations

import importlib
import io
import sys
from contextlib import redirect_stderr, redirect_stdout

import pytest


def test_main_module_imports_cli_main():
    """``gpa.__main__`` must import the CLI main (not the launcher)."""
    # Reload to make sure we observe the current __main__.py contents.
    import gpa.__main__ as gpa_main  # noqa: F401
    importlib.reload(gpa_main)

    from gpa.cli import main as cli_main

    # The exported `main` reference should be the CLI's `main` function,
    # which takes an optional argv list.  The launcher's main takes no
    # arguments — checking the signature is a faithful proxy.
    assert gpa_main.main is cli_main.main


def test_main_module_help_output(monkeypatch, capsys):
    """``python -m gpa --help`` should show CLI help, not launcher help."""
    import gpa.__main__ as gpa_main
    importlib.reload(gpa_main)

    # argparse exits with 0 on --help and writes to stdout.
    with pytest.raises(SystemExit) as excinfo:
        gpa_main.main(["--help"])
    assert excinfo.value.code == 0

    out = capsys.readouterr().out
    # The CLI parser advertises subcommands like 'start', 'stop', 'frames'.
    # The launcher does NOT — it only has --backend / --socket / --shm flags.
    assert "start" in out
    assert "frames" in out
    assert "--backend" not in out  # launcher flag must not leak through


def test_main_module_dispatches_subcommand(monkeypatch):
    """``main(["frames"])`` should invoke the CLI's frames handler.

    We don't have a real session so the call exits 2 (no session). What
    matters is that dispatch reached the CLI codepath and *not* the
    engine launcher (which would have tried to import ``_gpa_core``).
    """
    import gpa.__main__ as gpa_main
    importlib.reload(gpa_main)

    # Make sure no stale GPA_SESSION leaks in.
    monkeypatch.delenv("GPA_SESSION", raising=False)

    # Point the session-discovery link at a path that does not exist.
    from gpa.cli import session as session_mod
    monkeypatch.setattr(
        session_mod, "CURRENT_SESSION_LINK", "/tmp/no-such-gpa-session-link"
    )

    err = io.StringIO()
    with redirect_stderr(err):
        rc = gpa_main.main(["frames"])
    assert rc == 2
    assert "no active session" in err.getvalue()


def test_launcher_module_still_importable():
    """``python -m gpa.launcher`` must remain a valid entry point."""
    # We don't actually run the launcher (it would try to bind sockets and
    # spawn an engine thread). We just assert the module loads cleanly and
    # advertises a `main` function — which is what `python -m gpa.launcher`
    # invokes.
    import gpa.launcher as launcher_mod

    assert hasattr(launcher_mod, "main")
    assert callable(launcher_mod.main)
