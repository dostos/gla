"""``gpa diff`` — frame-vs-frame diff namespace.

Subverbs:
    gpa diff frames --a N --b N [--depth summary|drawcalls|pixels]

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
    """Register ``diff`` (and its subverbs) on the parent CLI subparsers."""
    p = subparsers.add_parser(
        "diff",
        help="Frame-vs-frame diff",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Examples:\n"
            "  gpa diff frames --a 3 --b 5                    # summary diff\n"
            "  gpa diff frames --a 3 --b 5 --depth drawcalls  # per-draw breakdown\n"
            "  gpa diff frames --a 3 --b 5 --depth pixels     # pixel-level diff\n"
        ),
    )
    p.add_argument(
        "--session",
        dest="session",
        type=Path,
        default=None,
        help="Session directory (overrides $GPA_SESSION and the current-session link)",
    )

    sub = p.add_subparsers(dest="diff_cmd", required=True)

    # ---- frames ----
    p_frames = sub.add_parser("frames", help="Compare two captured frames (JSON)")
    p_frames.add_argument("--a", type=int, required=True,
                          help="First frame id")
    p_frames.add_argument("--b", type=int, required=True,
                          help="Second frame id")
    p_frames.add_argument(
        "--depth",
        default="summary",
        choices=("summary", "drawcalls", "pixels"),
        help="Diff depth (default: summary)",
    )


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


def run_frames(
    *,
    session_dir: Optional[Path] = None,
    client: Optional[RestClient] = None,
    print_stream=None,
    a: int,
    b: int,
    depth: str = "summary",
) -> int:
    """Implement ``gpa diff frames --a N --b N [--depth ...]``."""
    if print_stream is None:
        print_stream = sys.stdout

    sess, client = _get_session_and_client(session_dir, client)
    if sess is None:
        print("[gpa] no active session found", file=sys.stderr)
        return 2
    if client is None:
        return 1

    path = f"/api/v1/diff/{int(a)}/{int(b)}?depth={depth}"
    try:
        data = client.get_json(path)
    except RestError as exc:
        print(f"[gpa] {exc}", file=sys.stderr)
        return 1

    _print_json(data, print_stream)
    return 0


# --------------------------------------------------------------------------- #
# Top-level dispatcher (args-based)
# --------------------------------------------------------------------------- #


def run(args, *, client: Optional[RestClient] = None, print_stream=None) -> int:
    """Dispatch ``diff`` subverbs from parsed ``args``."""
    session_dir: Optional[Path] = getattr(args, "session", None)
    diff_cmd = getattr(args, "diff_cmd", None)

    common = dict(session_dir=session_dir, client=client, print_stream=print_stream)

    if diff_cmd == "frames":
        return run_frames(
            **common,
            a=args.a,
            b=args.b,
            depth=getattr(args, "depth", "summary"),
        )

    # Should not be reached since argparse validates required=True.
    print(f"[gpa] unknown diff subcommand: {diff_cmd!r}", file=sys.stderr)
    return 1
