"""``gpa control`` — capture engine control namespace.

Subverbs:
    gpa control status   — get current engine running state
    gpa control pause    — pause frame capture
    gpa control resume   — resume frame capture
    gpa control step     — advance capture by one frame

These subverbs are NOT per-frame; no ``--frame`` argument.

All output is compact JSON (pass-through of the API response).

Exit codes:
    0  success
    1  REST / transport error
    2  no active session found
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Optional

from gpa.cli.rest_client import RestClient, RestError
from gpa.cli.session import Session


# --------------------------------------------------------------------------- #
# Subparser registration
# --------------------------------------------------------------------------- #


def add_subparser(subparsers) -> None:
    """Register ``control`` (and its subverbs) on the parent CLI subparsers."""
    p = subparsers.add_parser(
        "control",
        help="Engine capture control (status, pause, resume, step)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Examples:\n"
            "  gpa control status    # engine running state\n"
            "  gpa control pause     # pause frame capture\n"
            "  gpa control resume    # resume frame capture\n"
            "  gpa control step      # advance one frame while paused\n"
        ),
    )
    p.add_argument(
        "--session",
        dest="session",
        type=Path,
        default=None,
        help="Session directory (overrides $GPA_SESSION and the current-session link)",
    )

    sub = p.add_subparsers(dest="control_cmd", required=True)

    sub.add_parser("status", help="Get current engine running state (JSON)")
    sub.add_parser("pause", help="Pause frame capture (JSON)")
    sub.add_parser("resume", help="Resume frame capture (JSON)")
    sub.add_parser("step", help="Advance capture by one frame (JSON)")


# --------------------------------------------------------------------------- #
# Session / client helper
# --------------------------------------------------------------------------- #


_INJECTED_SENTINEL = object()


def _get_session_and_client(
    session_dir: Optional[Path],
    client: Optional[RestClient],
) -> tuple:
    """Resolve session and build client. Returns (session, client) or (None, None) on error."""
    if client is not None:
        return _INJECTED_SENTINEL, client
    sess = Session.discover(explicit=session_dir)
    if sess is None:
        return None, None
    try:
        client = RestClient.from_session(sess)
    except Exception as exc:  # noqa: BLE001
        print(f"[gpa] failed to connect to engine: {exc}", file=sys.stderr)
        return sess, None
    return sess, client


# --------------------------------------------------------------------------- #
# Output helper
# --------------------------------------------------------------------------- #


def _print_json(data, print_stream) -> None:
    """Dump data as compact JSON to print_stream."""
    print_stream.write(json.dumps(data) + "\n")
    print_stream.flush()


# --------------------------------------------------------------------------- #
# Subverb implementations (kwargs-only, injectable client)
# --------------------------------------------------------------------------- #


def run_status(
    *,
    session_dir: Optional[Path] = None,
    client: Optional[RestClient] = None,
    print_stream=None,
) -> int:
    """Implement ``gpa control status``."""
    if print_stream is None:
        print_stream = sys.stdout

    sess, client = _get_session_and_client(session_dir, client)
    if sess is None:
        print("[gpa] no active session found", file=sys.stderr)
        return 2
    if client is None:
        return 1

    try:
        data = client.get_json("/api/v1/control/status")
    except RestError as exc:
        print(f"[gpa] {exc}", file=sys.stderr)
        return 1

    _print_json(data, print_stream)
    return 0


def run_pause(
    *,
    session_dir: Optional[Path] = None,
    client: Optional[RestClient] = None,
    print_stream=None,
) -> int:
    """Implement ``gpa control pause``."""
    if print_stream is None:
        print_stream = sys.stdout

    sess, client = _get_session_and_client(session_dir, client)
    if sess is None:
        print("[gpa] no active session found", file=sys.stderr)
        return 2
    if client is None:
        return 1

    try:
        data = client.post_json("/api/v1/control/pause", {})
    except RestError as exc:
        print(f"[gpa] {exc}", file=sys.stderr)
        return 1

    _print_json(data, print_stream)
    return 0


def run_resume(
    *,
    session_dir: Optional[Path] = None,
    client: Optional[RestClient] = None,
    print_stream=None,
) -> int:
    """Implement ``gpa control resume``."""
    if print_stream is None:
        print_stream = sys.stdout

    sess, client = _get_session_and_client(session_dir, client)
    if sess is None:
        print("[gpa] no active session found", file=sys.stderr)
        return 2
    if client is None:
        return 1

    try:
        data = client.post_json("/api/v1/control/resume", {})
    except RestError as exc:
        print(f"[gpa] {exc}", file=sys.stderr)
        return 1

    _print_json(data, print_stream)
    return 0


def run_step(
    *,
    session_dir: Optional[Path] = None,
    client: Optional[RestClient] = None,
    print_stream=None,
) -> int:
    """Implement ``gpa control step``."""
    if print_stream is None:
        print_stream = sys.stdout

    sess, client = _get_session_and_client(session_dir, client)
    if sess is None:
        print("[gpa] no active session found", file=sys.stderr)
        return 2
    if client is None:
        return 1

    try:
        data = client.post_json("/api/v1/control/step", {})
    except RestError as exc:
        print(f"[gpa] {exc}", file=sys.stderr)
        return 1

    _print_json(data, print_stream)
    return 0


# --------------------------------------------------------------------------- #
# Top-level dispatcher (args-based)
# --------------------------------------------------------------------------- #


def run(args, *, client: Optional[RestClient] = None, print_stream=None) -> int:
    """Dispatch ``control`` subverbs from parsed ``args``."""
    session_dir: Optional[Path] = getattr(args, "session", None)
    control_cmd = getattr(args, "control_cmd", None)

    common = dict(session_dir=session_dir, client=client, print_stream=print_stream)

    if control_cmd == "status":
        return run_status(**common)
    if control_cmd == "pause":
        return run_pause(**common)
    if control_cmd == "resume":
        return run_resume(**common)
    if control_cmd == "step":
        return run_step(**common)

    # Should not be reached since argparse validates required=True.
    print(f"[gpa] unknown control subcommand: {control_cmd!r}", file=sys.stderr)
    return 1
