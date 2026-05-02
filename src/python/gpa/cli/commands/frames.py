"""``gpa frames`` — frame inspection namespace.

Subverbs:
    gpa frames list [--json] [--text]        list captured frame ids
    gpa frames overview [--frame N]          frame overview (JSON)
    gpa frames check-config [--frame N] ...  config rule check on a frame

Bare ``gpa frames`` is a deprecated alias for ``gpa frames list``.

Exit codes:
    0  success (including empty session)
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
    """Register ``frames`` (and its subverbs) on the parent CLI ``subparsers``."""
    p = subparsers.add_parser(
        "frames",
        help="Frame inspection (list, overview, check-config)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Examples:\n"
            "  gpa frames list                          # JSON list of frame ids\n"
            "  gpa frames list --text                   # one id per line\n"
            "  gpa frames overview                      # current frame overview\n"
            "  gpa frames overview --frame 7            # specific frame\n"
            "  gpa frames check-config --frame 7        # config check on a frame\n"
        ),
    )
    p.add_argument(
        "--session",
        dest="session",
        type=Path,
        default=None,
        help="Session directory (overrides $GPA_SESSION and the current-session link)",
    )
    # NOTE: required=False so bare ``gpa frames`` reaches the dispatcher and
    # gets routed to the deprecated alias for ``frames list``.
    sub = p.add_subparsers(dest="frames_cmd", required=False)

    # ---- list ----
    p_list = sub.add_parser("list", help="List captured frame ids")
    p_list.add_argument(
        "--json", dest="json_output", action="store_true",
        help=argparse.SUPPRESS,
    )
    p_list.add_argument(
        "--text", dest="text_output", action="store_true",
        help="Plain text (one id per line) instead of JSON",
    )

    # ---- overview ----
    p_overview = sub.add_parser("overview", help="Frame overview (JSON)")
    p_overview.add_argument(
        "--frame", default=None,
        help="Frame id (default: GPA_FRAME_ID env or latest)",
    )

    # ---- check-config ----
    p_cc = sub.add_parser(
        "check-config",
        help="Run check-config rules on a frame",
    )
    p_cc.add_argument(
        "--frame", default=None,
        help="Frame id (default: GPA_FRAME_ID env or latest)",
    )
    p_cc.add_argument(
        "--severity", default="warn",
        choices=("error", "warn", "info"),
        help="Minimum severity to report (default: warn)",
    )
    p_cc.add_argument(
        "--rules", action="store_true",
        help="List all known rules with severity + 1-line description, then exit",
    )
    p_cc.add_argument(
        "--rule", default=None,
        help="Comma-separated rule ids to run (default: all enabled)",
    )
    p_cc.add_argument(
        "--json", dest="json_output", action="store_true",
        help="Emit machine-readable JSON instead of plain text",
    )


# --------------------------------------------------------------------------- #
# Subverb implementations
# --------------------------------------------------------------------------- #


def _get_session_and_client(
    session_dir: Optional[Path],
    client: Optional[RestClient],
) -> tuple:
    """Resolve session and build client. Returns (session, client) or (None, None) on error."""
    sess = Session.discover(explicit=session_dir)
    if sess is None:
        return None, None
    if client is None:
        try:
            client = RestClient.from_session(sess)
        except Exception as exc:  # noqa: BLE001
            print(f"[gpa] failed to connect to engine: {exc}", file=sys.stderr)
            return sess, None
    return sess, client


def run_list(
    *,
    session_dir: Optional[Path] = None,
    client: Optional[RestClient] = None,
    print_stream=None,
    text_output: bool = False,
    json_output: bool = False,
) -> int:
    """Implement ``gpa frames list``.

    Default output is JSON. ``--text`` opts out to one id per line.
    ``--json`` forces JSON (legacy compat; JSON is already the default).
    ``--text`` takes precedence over ``--json`` if both are given.
    """
    if print_stream is None:
        print_stream = sys.stdout

    sess, client = _get_session_and_client(session_dir, client)
    if sess is None:
        print("[gpa] no active session found", file=sys.stderr)
        return 2

    if client is None:
        return 1

    ids: list[int] = []
    try:
        data = client.get_json("/api/v1/frames")
        if isinstance(data, dict) and isinstance(data.get("frames"), list):
            ids = [int(f) for f in data["frames"]]
        elif isinstance(data, list):
            # Defensive: legacy shape in case an old engine still serves a
            # bare JSON array.  Newer engines wrap the list in {"frames":…}.
            ids = [int(f) for f in data]
    except RestError as exc:
        # Fall back to "latest only" only if the engine genuinely does not
        # expose /api/v1/frames (HTTP 404).  Other errors propagate.
        if getattr(exc, "status", None) == 404:
            try:
                ov = client.get_json("/api/v1/frames/current/overview")
                if isinstance(ov, dict):
                    fid = int(ov.get("frame_id", 0) or 0)
                    ids = [fid]
            except RestError as exc2:
                print(f"[gpa] {exc2}", file=sys.stderr)
                return 1
        else:
            print(f"[gpa] {exc}", file=sys.stderr)
            return 1

    # text_output takes precedence over json_output; if neither, default to JSON.
    use_text = text_output
    if use_text:
        for fid in ids:
            print_stream.write(f"{fid}\n")
    else:
        print_stream.write(json.dumps({"frames": ids, "count": len(ids)}) + "\n")
    print_stream.flush()
    return 0


def run_overview(
    *,
    session_dir: Optional[Path] = None,
    client: Optional[RestClient] = None,
    print_stream=None,
    frame: Optional[str] = None,
) -> int:
    """Implement ``gpa frames overview [--frame N]``."""
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
        data = client.get_json(f"/api/v1/frames/{fid}/overview")
    except RestError as exc:
        print(f"[gpa] {exc}", file=sys.stderr)
        return 1

    print_stream.write(json.dumps(data, default=str) + "\n")
    print_stream.flush()
    return 0


def run_check_config(
    *,
    session_dir: Optional[Path] = None,
    client: Optional[RestClient] = None,
    print_stream=None,
    frame: Optional[str] = None,
    severity: str = "warn",
    rules: bool = False,
    rule: Optional[str] = None,
    json_output: bool = False,
    stdin_stream=None,
) -> int:
    """Implement ``gpa frames check-config`` by delegating to check_config.run()."""
    from gpa.cli.commands import check_config as check_config_cmd
    return check_config_cmd.run(
        session_dir=session_dir,
        frame=frame,
        severity=severity,
        rules=rules,
        rule=rule,
        json_output=json_output,
        client=client,
        print_stream=print_stream,
        stdin_stream=stdin_stream,
    )


# --------------------------------------------------------------------------- #
# Top-level dispatcher (args-based)
# --------------------------------------------------------------------------- #


def run(args, *, client: Optional[RestClient] = None, print_stream=None) -> int:
    """Dispatch ``frames`` subverbs from parsed ``args``."""
    session_dir: Optional[Path] = getattr(args, "session", None)
    frames_cmd = getattr(args, "frames_cmd", None)

    if frames_cmd is None:
        # Deprecated bare ``gpa frames`` — alias for ``frames list``.
        print(
            "warning: bare 'gpa frames' is deprecated; use 'gpa frames list'",
            file=sys.stderr,
        )
        return run_list(
            session_dir=session_dir,
            client=client,
            print_stream=print_stream,
            text_output=getattr(args, "text_output", False),
            json_output=getattr(args, "json_output", False),
        )

    if frames_cmd == "list":
        return run_list(
            session_dir=session_dir,
            client=client,
            print_stream=print_stream,
            text_output=getattr(args, "text_output", False),
            json_output=getattr(args, "json_output", False),
        )

    if frames_cmd == "overview":
        return run_overview(
            session_dir=session_dir,
            client=client,
            print_stream=print_stream,
            frame=getattr(args, "frame", None),
        )

    if frames_cmd == "check-config":
        return run_check_config(
            session_dir=session_dir,
            client=client,
            print_stream=print_stream,
            frame=getattr(args, "frame", None),
            severity=getattr(args, "severity", "warn"),
            rules=getattr(args, "rules", False),
            rule=getattr(args, "rule", None),
            json_output=getattr(args, "json_output", False),
        )

    # Should not be reached since argparse validates choices.
    print(f"[gpa] unknown frames subcommand: {frames_cmd!r}", file=sys.stderr)
    return 1
