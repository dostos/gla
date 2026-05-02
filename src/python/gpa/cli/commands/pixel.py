"""``gpa pixel`` — pixel inspection namespace.

Subverbs:
    gpa pixel get     [--frame N] --x N --y N    — read raw pixel colour
    gpa pixel explain [--frame N] --x N --y N    — pixel→draw→node trace

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

from gpa.cli.frame_resolver import resolve_frame
from gpa.cli.rest_client import RestClient, RestError
from gpa.cli.session import Session


# --------------------------------------------------------------------------- #
# Subparser registration
# --------------------------------------------------------------------------- #


def add_subparser(subparsers) -> None:
    """Register ``pixel`` (and its subverbs) on the parent CLI subparsers."""
    p = subparsers.add_parser(
        "pixel",
        help="Pixel inspection (get colour, explain contributing draws)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Examples:\n"
            "  gpa pixel get --x 100 --y 200             # RGBA at (100,200), latest frame\n"
            "  gpa pixel get --frame 5 --x 0 --y 0       # specific frame\n"
            "  gpa pixel explain --x 100 --y 200         # pixel→draw→node trace\n"
        ),
    )
    p.add_argument(
        "--session",
        dest="session",
        type=Path,
        default=None,
        help="Session directory (overrides $GPA_SESSION and the current-session link)",
    )

    sub = p.add_subparsers(dest="pixel_cmd", required=True)

    # ---- get ----
    p_get = sub.add_parser("get", help="Read raw pixel colour (JSON)")
    p_get.add_argument("--frame", default=None,
                       help="Frame id (default: GPA_FRAME_ID env or latest)")
    p_get.add_argument("--x", type=int, required=True, help="Pixel x coordinate")
    p_get.add_argument("--y", type=int, required=True, help="Pixel y coordinate")

    # ---- explain ----
    p_explain = sub.add_parser("explain", help="Pixel→draw→node trace (JSON)")
    p_explain.add_argument("--frame", default=None,
                           help="Frame id (default: GPA_FRAME_ID env or latest)")
    p_explain.add_argument("--x", type=int, required=True, help="Pixel x coordinate")
    p_explain.add_argument("--y", type=int, required=True, help="Pixel y coordinate")


# --------------------------------------------------------------------------- #
# Session / client helper
# --------------------------------------------------------------------------- #


_INJECTED_SENTINEL = object()


def _get_session_and_client(
    session_dir: Optional[Path],
    client: Optional[RestClient],
) -> tuple:
    """Resolve session and build client. Returns (session, client) or (None, None) on error.

    If a client is already injected (e.g., in tests), skip session discovery.
    """
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


def run_get(
    *,
    session_dir: Optional[Path] = None,
    client: Optional[RestClient] = None,
    print_stream=None,
    frame: Optional[str] = None,
    x: int,
    y: int,
) -> int:
    """Implement ``gpa pixel get --x N --y N``."""
    if print_stream is None:
        print_stream = sys.stdout

    sess, client = _get_session_and_client(session_dir, client)
    if sess is None:
        print("[gpa] no active session found", file=sys.stderr)
        return 2
    if client is None:
        return 1

    try:
        fid = resolve_frame(client=client, explicit=frame)
    except Exception as exc:  # noqa: BLE001
        print(f"[gpa] could not resolve frame: {exc}", file=sys.stderr)
        return 1

    try:
        data = client.get_json(f"/api/v1/frames/{fid}/pixel/{x}/{y}")
    except RestError as exc:
        print(f"[gpa] {exc}", file=sys.stderr)
        return 1

    _print_json(data, print_stream)
    return 0


def run_explain(
    *,
    session_dir: Optional[Path] = None,
    client: Optional[RestClient] = None,
    print_stream=None,
    frame: Optional[str] = None,
    x: int,
    y: int,
) -> int:
    """Implement ``gpa pixel explain --x N --y N``."""
    if print_stream is None:
        print_stream = sys.stdout

    sess, client = _get_session_and_client(session_dir, client)
    if sess is None:
        print("[gpa] no active session found", file=sys.stderr)
        return 2
    if client is None:
        return 1

    try:
        fid = resolve_frame(client=client, explicit=frame)
    except Exception as exc:  # noqa: BLE001
        print(f"[gpa] could not resolve frame: {exc}", file=sys.stderr)
        return 1

    try:
        data = client.get_json(f"/api/v1/frames/{fid}/explain-pixel?x={x}&y={y}")
    except RestError as exc:
        print(f"[gpa] {exc}", file=sys.stderr)
        return 1

    _print_json(data, print_stream)
    return 0


# --------------------------------------------------------------------------- #
# Top-level dispatcher (args-based)
# --------------------------------------------------------------------------- #


def run(args, *, client: Optional[RestClient] = None, print_stream=None) -> int:
    """Dispatch ``pixel`` subverbs from parsed ``args``."""
    session_dir: Optional[Path] = getattr(args, "session", None)
    pixel_cmd = getattr(args, "pixel_cmd", None)

    common = dict(session_dir=session_dir, client=client, print_stream=print_stream)

    if pixel_cmd == "get":
        return run_get(**common, frame=getattr(args, "frame", None), x=args.x, y=args.y)

    if pixel_cmd == "explain":
        return run_explain(**common, frame=getattr(args, "frame", None), x=args.x, y=args.y)

    # Should not be reached since argparse validates required=True.
    print(f"[gpa] unknown pixel subcommand: {pixel_cmd!r}", file=sys.stderr)
    return 1
