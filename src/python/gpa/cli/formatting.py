"""Small plain-text formatting helpers for the ``gpa`` CLI.

Intentionally dependency-free — the CLI should not drag in a color library
just to emit a few ANSI escapes.
"""

from __future__ import annotations

import os
import sys
from typing import TextIO


# ANSI escape sequences.  Kept inline rather than pulled from a third-party
# palette so we don't grow a new dep.
_RESET = "\x1b[0m"
_YELLOW = "\x1b[33m"
_GREEN = "\x1b[32m"
_RED = "\x1b[31m"
_DIM = "\x1b[2m"


WARN_MARK = "\u26a0"   # ⚠
OK_MARK = "\u2713"     # ✓
ERR_MARK = "\u2717"    # ✗


def use_color(stream: TextIO = None) -> bool:
    """Return True iff colour output is appropriate for ``stream``.

    Rules:
      * ``NO_COLOR`` env var set (any value) disables colour.
      * Otherwise require an actual TTY on ``stream`` (defaults to stdout).
    """
    if "NO_COLOR" in os.environ:
        return False
    if stream is None:
        stream = sys.stdout
    try:
        return stream.isatty()
    except Exception:
        return False


def color(text: str, code: str, *, enabled: bool) -> str:
    if not enabled:
        return text
    return f"{code}{text}{_RESET}"


def warn_line(check: str, summary: str, *, enabled: bool = False) -> str:
    mark = color(WARN_MARK, _YELLOW, enabled=enabled)
    return f"{mark} {check}: {summary}"


def ok_line(check: str, *, enabled: bool = False) -> str:
    mark = color(OK_MARK, _GREEN, enabled=enabled)
    return f"{mark} {check}: ok"


def err_line(check: str, message: str, *, enabled: bool = False) -> str:
    mark = color(ERR_MARK, _RED, enabled=enabled)
    return f"{mark} {check}: {message}"


def dim(text: str, *, enabled: bool = False) -> str:
    return color(text, _DIM, enabled=enabled)


def drill_line(
    check: str,
    frame_id: int,
    dc_id: int | None = None,
    *,
    enabled: bool = False,
) -> str:
    """One-liner telling the agent the exact next command to run.

    Emitted under each warning in ``gpa report`` plain-text output so the
    caller doesn't have to guess the check name and draw-call id.
    """
    cmd = f"gpa check {check} --frame {frame_id}"
    if dc_id is not None:
        cmd += f" --dc {dc_id}"
    arrow = color("\u2192", _DIM, enabled=enabled)
    return f"  {arrow} drill: {cmd}"
