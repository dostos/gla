"""``gpa annotations`` — per-frame annotation namespace.

Subverbs:
    gpa annotations list [--frame N]
    gpa annotations add  [--frame N] (--file PATH | --body-json TEXT)

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
    """Register ``annotations`` (and its subverbs) on the parent CLI subparsers."""
    p = subparsers.add_parser(
        "annotations",
        help="Per-frame annotation sidecar (list, add)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Examples:\n"
            "  gpa annotations list                          # current frame\n"
            "  gpa annotations list --frame 7               # specific frame\n"
            "  gpa annotations add --body-json '{\"k\":1}'   # inline JSON\n"
            "  gpa annotations add --file meta.json         # from file\n"
        ),
    )
    p.add_argument(
        "--session",
        dest="session",
        type=Path,
        default=None,
        help="Session directory (overrides $GPA_SESSION and the current-session link)",
    )

    sub = p.add_subparsers(dest="annotations_cmd", required=True)

    # ---- list ----
    p_list = sub.add_parser("list", help="Get stored annotations for a frame (JSON)")
    p_list.add_argument("--frame", default=None,
                        help="Frame id (default: GPA_FRAME_ID env or latest)")

    # ---- add ----
    p_add = sub.add_parser("add", help="Post annotation JSON for a frame")
    p_add.add_argument("--frame", default=None,
                       help="Frame id (default: GPA_FRAME_ID env or latest)")
    body_group = p_add.add_mutually_exclusive_group(required=True)
    body_group.add_argument(
        "--file", dest="file_path", default=None, metavar="PATH",
        help="Path to a JSON file to POST as the body",
    )
    body_group.add_argument(
        "--body-json", dest="body_json", default=None, metavar="TEXT",
        help="Inline JSON string to POST as the body",
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


def run_list(
    *,
    session_dir: Optional[Path] = None,
    client: Optional[RestClient] = None,
    print_stream=None,
    frame: Optional[str] = None,
) -> int:
    """Implement ``gpa annotations list [--frame N]``."""
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
        data = client.get_json(f"/api/v1/frames/{fid}/annotations")
    except RestError as exc:
        print(f"[gpa] {exc}", file=sys.stderr)
        return 1

    _print_json(data, print_stream)
    return 0


def run_add(
    *,
    session_dir: Optional[Path] = None,
    client: Optional[RestClient] = None,
    print_stream=None,
    frame: Optional[str] = None,
    body_json: Optional[str] = None,
    file_path: Optional[str] = None,
) -> int:
    """Implement ``gpa annotations add [--frame N] (--file PATH | --body-json TEXT)``."""
    if print_stream is None:
        print_stream = sys.stdout

    # Resolve body.
    if body_json is not None:
        try:
            body = json.loads(body_json)
        except json.JSONDecodeError as exc:
            print(f"[gpa] invalid JSON in --body-json: {exc}", file=sys.stderr)
            return 2
    elif file_path is not None:
        try:
            with open(file_path) as fh:
                body = json.load(fh)
        except (OSError, json.JSONDecodeError) as exc:
            print(f"[gpa] could not read --file {file_path!r}: {exc}", file=sys.stderr)
            return 2
    else:
        print("[gpa] one of --file or --body-json is required", file=sys.stderr)
        return 2

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
        data = client.post_json(f"/api/v1/frames/{fid}/annotations", body)
    except RestError as exc:
        print(f"[gpa] {exc}", file=sys.stderr)
        return 1

    _print_json(data, print_stream)
    return 0


# --------------------------------------------------------------------------- #
# Top-level dispatcher (args-based)
# --------------------------------------------------------------------------- #


def run(args, *, client: Optional[RestClient] = None, print_stream=None) -> int:
    """Dispatch ``annotations`` subverbs from parsed ``args``."""
    session_dir: Optional[Path] = getattr(args, "session", None)
    annotations_cmd = getattr(args, "annotations_cmd", None)

    common = dict(session_dir=session_dir, client=client, print_stream=print_stream)

    if annotations_cmd == "list":
        return run_list(**common, frame=getattr(args, "frame", None))

    if annotations_cmd == "add":
        return run_add(
            **common,
            frame=getattr(args, "frame", None),
            body_json=getattr(args, "body_json", None),
            file_path=getattr(args, "file_path", None),
        )

    # Should not be reached since argparse validates required=True.
    print(f"[gpa] unknown annotations subcommand: {annotations_cmd!r}", file=sys.stderr)
    return 1
