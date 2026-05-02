"""``gpa drawcalls`` — draw-call inspection namespace.

Subverbs:
    gpa drawcalls list         [--frame N] [--limit N] [--offset N]
    gpa drawcalls get          [--frame N] --dc N
    gpa drawcalls shader       [--frame N] --dc N
    gpa drawcalls textures     [--frame N] --dc N
    gpa drawcalls vertices     [--frame N] --dc N
    gpa drawcalls attachments  [--frame N] --dc N
    gpa drawcalls nan-uniforms [--frame N] --dc N
    gpa drawcalls feedback-loops [--frame N] --dc N
    gpa drawcalls explain      [--frame N] --dc N
    gpa drawcalls diff         [--frame N] --a N --b N [--scope state|uniforms|textures|all]
    gpa drawcalls sources get  [--frame N] --dc N
    gpa drawcalls sources set  [--frame N] --dc N (--file PATH | --body-json TEXT)

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
    """Register ``drawcalls`` (and its subverbs) on the parent CLI subparsers."""
    p = subparsers.add_parser(
        "drawcalls",
        help="Draw-call inspection (list, get, shader, textures, …)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Examples:\n"
            "  gpa drawcalls list                           # JSON list for current frame\n"
            "  gpa drawcalls list --frame 7 --limit 20     # paginated\n"
            "  gpa drawcalls get --dc 4                    # single draw call\n"
            "  gpa drawcalls shader --dc 4                 # shader info\n"
            "  gpa drawcalls textures --dc 4               # bound textures\n"
            "  gpa drawcalls vertices --dc 4               # vertex data\n"
            "  gpa drawcalls attachments --dc 4            # framebuffer attachments\n"
            "  gpa drawcalls nan-uniforms --dc 4           # NaN/Inf uniforms\n"
            "  gpa drawcalls feedback-loops --dc 4         # feedback-loop hazards\n"
            "  gpa drawcalls explain --dc 4                # full explanation\n"
            "  gpa drawcalls diff --a 3 --b 5              # delta between two draws\n"
            "  gpa drawcalls sources get --dc 4            # source mappings\n"
            "  gpa drawcalls sources set --dc 4 --body-json '{\"v\":\"...\"}'\n"
        ),
    )
    p.add_argument(
        "--session",
        dest="session",
        type=Path,
        default=None,
        help="Session directory (overrides $GPA_SESSION and the current-session link)",
    )

    sub = p.add_subparsers(dest="drawcalls_cmd", required=True)

    # ---- list ----
    p_list = sub.add_parser("list", help="List draw calls for a frame (JSON)")
    p_list.add_argument("--frame", default=None,
                        help="Frame id (default: GPA_FRAME_ID env or latest)")
    p_list.add_argument("--limit", type=int, default=None,
                        help="Maximum number of draw calls to return")
    p_list.add_argument("--offset", type=int, default=None,
                        help="Start offset for pagination")

    # ---- get ----
    p_get = sub.add_parser("get", help="Get a single draw call (JSON)")
    p_get.add_argument("--frame", default=None,
                       help="Frame id (default: GPA_FRAME_ID env or latest)")
    p_get.add_argument("--dc", type=int, required=True,
                       help="Draw call id")

    # ---- shader ----
    p_shader = sub.add_parser("shader", help="Shader info for a draw call")
    p_shader.add_argument("--frame", default=None,
                          help="Frame id (default: GPA_FRAME_ID env or latest)")
    p_shader.add_argument("--dc", type=int, required=True,
                          help="Draw call id")

    # ---- textures ----
    p_tex = sub.add_parser("textures", help="Bound textures for a draw call")
    p_tex.add_argument("--frame", default=None,
                       help="Frame id (default: GPA_FRAME_ID env or latest)")
    p_tex.add_argument("--dc", type=int, required=True,
                       help="Draw call id")

    # ---- vertices ----
    p_verts = sub.add_parser("vertices", help="Vertex data for a draw call")
    p_verts.add_argument("--frame", default=None,
                         help="Frame id (default: GPA_FRAME_ID env or latest)")
    p_verts.add_argument("--dc", type=int, required=True,
                         help="Draw call id")

    # ---- attachments ----
    p_att = sub.add_parser("attachments", help="Framebuffer attachments for a draw call")
    p_att.add_argument("--frame", default=None,
                       help="Frame id (default: GPA_FRAME_ID env or latest)")
    p_att.add_argument("--dc", type=int, required=True,
                       help="Draw call id")

    # ---- nan-uniforms ----
    p_nan = sub.add_parser("nan-uniforms", help="NaN/Inf uniforms for a draw call")
    p_nan.add_argument("--frame", default=None,
                       help="Frame id (default: GPA_FRAME_ID env or latest)")
    p_nan.add_argument("--dc", type=int, required=True,
                       help="Draw call id")

    # ---- feedback-loops ----
    p_fb = sub.add_parser("feedback-loops", help="Feedback-loop hazards for a draw call")
    p_fb.add_argument("--frame", default=None,
                      help="Frame id (default: GPA_FRAME_ID env or latest)")
    p_fb.add_argument("--dc", type=int, required=True,
                      help="Draw call id")

    # ---- explain ----
    p_explain = sub.add_parser("explain", help="Full explanation of a draw call")
    p_explain.add_argument("--frame", default=None,
                           help="Frame id (default: GPA_FRAME_ID env or latest)")
    p_explain.add_argument("--dc", type=int, required=True,
                           help="Draw call id")

    # ---- diff ----
    p_diff = sub.add_parser("diff", help="State/uniform/texture delta between two draw calls")
    p_diff.add_argument("--frame", default=None,
                        help="Frame id (default: GPA_FRAME_ID env or latest)")
    p_diff.add_argument("--a", type=int, required=True,
                        help="First draw call id")
    p_diff.add_argument("--b", type=int, required=True,
                        help="Second draw call id")
    p_diff.add_argument(
        "--scope",
        default="all",
        choices=("state", "uniforms", "textures", "all"),
        help="What to diff (default: all)",
    )

    # ---- sources (sub-sub-noun) ----
    p_sources = sub.add_parser("sources", help="Source-mapping ops on a draw call")
    sources_sub = p_sources.add_subparsers(dest="sources_cmd", required=True)

    p_src_get = sources_sub.add_parser("get", help="Get source mappings")
    p_src_get.add_argument("--frame", default=None,
                           help="Frame id (default: GPA_FRAME_ID env or latest)")
    p_src_get.add_argument("--dc", type=int, required=True,
                           help="Draw call id")

    p_src_set = sources_sub.add_parser("set", help="Set source mappings")
    p_src_set.add_argument("--frame", default=None,
                           help="Frame id (default: GPA_FRAME_ID env or latest)")
    p_src_set.add_argument("--dc", type=int, required=True,
                           help="Draw call id")
    body_group = p_src_set.add_mutually_exclusive_group(required=True)
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


# Sentinel object used when a client is injected directly (tests / MCP callers).
_INJECTED_SENTINEL = object()


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
    limit: Optional[int] = None,
    offset: Optional[int] = None,
) -> int:
    """Implement ``gpa drawcalls list``."""
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

    path = f"/api/v1/frames/{fid}/drawcalls"
    params = []
    if limit is not None:
        params.append(f"limit={limit}")
    if offset is not None:
        params.append(f"offset={offset}")
    if params:
        path += "?" + "&".join(params)

    try:
        data = client.get_json(path)
    except RestError as exc:
        print(f"[gpa] {exc}", file=sys.stderr)
        return 1

    _print_json(data, print_stream)
    return 0


def run_get(
    *,
    session_dir: Optional[Path] = None,
    client: Optional[RestClient] = None,
    print_stream=None,
    frame: Optional[str] = None,
    dc: int,
) -> int:
    """Implement ``gpa drawcalls get --dc N``."""
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
        data = client.get_json(f"/api/v1/frames/{fid}/drawcalls/{dc}")
    except RestError as exc:
        print(f"[gpa] {exc}", file=sys.stderr)
        return 1

    _print_json(data, print_stream)
    return 0


def _run_dc_subpath(
    subpath: str,
    *,
    session_dir: Optional[Path],
    client: Optional[RestClient],
    print_stream,
    frame: Optional[str],
    dc: int,
) -> int:
    """Generic handler for draw-call sub-resource GETs.

    Calls GET /api/v1/frames/{fid}/drawcalls/{dc}/{subpath}.
    """
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
        data = client.get_json(f"/api/v1/frames/{fid}/drawcalls/{dc}/{subpath}")
    except RestError as exc:
        print(f"[gpa] {exc}", file=sys.stderr)
        return 1

    _print_json(data, print_stream)
    return 0


def run_shader(
    *,
    session_dir: Optional[Path] = None,
    client: Optional[RestClient] = None,
    print_stream=None,
    frame: Optional[str] = None,
    dc: int,
) -> int:
    """Implement ``gpa drawcalls shader --dc N``."""
    return _run_dc_subpath(
        "shader",
        session_dir=session_dir, client=client,
        print_stream=print_stream, frame=frame, dc=dc,
    )


def run_textures(
    *,
    session_dir: Optional[Path] = None,
    client: Optional[RestClient] = None,
    print_stream=None,
    frame: Optional[str] = None,
    dc: int,
) -> int:
    """Implement ``gpa drawcalls textures --dc N``."""
    return _run_dc_subpath(
        "textures",
        session_dir=session_dir, client=client,
        print_stream=print_stream, frame=frame, dc=dc,
    )


def run_vertices(
    *,
    session_dir: Optional[Path] = None,
    client: Optional[RestClient] = None,
    print_stream=None,
    frame: Optional[str] = None,
    dc: int,
) -> int:
    """Implement ``gpa drawcalls vertices --dc N``."""
    return _run_dc_subpath(
        "vertices",
        session_dir=session_dir, client=client,
        print_stream=print_stream, frame=frame, dc=dc,
    )


def run_attachments(
    *,
    session_dir: Optional[Path] = None,
    client: Optional[RestClient] = None,
    print_stream=None,
    frame: Optional[str] = None,
    dc: int,
) -> int:
    """Implement ``gpa drawcalls attachments --dc N``."""
    return _run_dc_subpath(
        "attachments",
        session_dir=session_dir, client=client,
        print_stream=print_stream, frame=frame, dc=dc,
    )


def run_nan_uniforms(
    *,
    session_dir: Optional[Path] = None,
    client: Optional[RestClient] = None,
    print_stream=None,
    frame: Optional[str] = None,
    dc: int,
) -> int:
    """Implement ``gpa drawcalls nan-uniforms --dc N``."""
    return _run_dc_subpath(
        "nan-uniforms",
        session_dir=session_dir, client=client,
        print_stream=print_stream, frame=frame, dc=dc,
    )


def run_feedback_loops(
    *,
    session_dir: Optional[Path] = None,
    client: Optional[RestClient] = None,
    print_stream=None,
    frame: Optional[str] = None,
    dc: int,
) -> int:
    """Implement ``gpa drawcalls feedback-loops --dc N``."""
    return _run_dc_subpath(
        "feedback-loops",
        session_dir=session_dir, client=client,
        print_stream=print_stream, frame=frame, dc=dc,
    )


def run_explain(
    *,
    session_dir: Optional[Path] = None,
    client: Optional[RestClient] = None,
    print_stream=None,
    frame: Optional[str] = None,
    dc: int,
) -> int:
    """Implement ``gpa drawcalls explain --dc N``.

    Note: uses /draws/ (not /drawcalls/) in the path — API quirk.
    """
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
        data = client.get_json(f"/api/v1/frames/{fid}/draws/{dc}/explain")
    except RestError as exc:
        print(f"[gpa] {exc}", file=sys.stderr)
        return 1

    _print_json(data, print_stream)
    return 0


def run_diff(
    *,
    session_dir: Optional[Path] = None,
    client: Optional[RestClient] = None,
    print_stream=None,
    frame: Optional[str] = None,
    a: int,
    b: int,
    scope: str = "all",
) -> int:
    """Implement ``gpa drawcalls diff --a N --b N``.

    Note: uses /draws/diff (not /drawcalls/diff) — API quirk.
    Default scope is 'all' (broader than the legacy diff-draws default of 'state').
    """
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

    path = f"/api/v1/frames/{fid}/draws/diff?a={int(a)}&b={int(b)}&scope={scope}"
    try:
        data = client.get_json(path)
    except RestError as exc:
        print(f"[gpa] {exc}", file=sys.stderr)
        return 1

    _print_json(data, print_stream)
    return 0


def run_sources_get(
    *,
    session_dir: Optional[Path] = None,
    client: Optional[RestClient] = None,
    print_stream=None,
    frame: Optional[str] = None,
    dc: int,
) -> int:
    """Implement ``gpa drawcalls sources get --dc N``."""
    return _run_dc_subpath(
        "sources",
        session_dir=session_dir, client=client,
        print_stream=print_stream, frame=frame, dc=dc,
    )


def run_sources_set(
    *,
    session_dir: Optional[Path] = None,
    client: Optional[RestClient] = None,
    print_stream=None,
    frame: Optional[str] = None,
    dc: int,
    body_json: Optional[str] = None,
    file_path: Optional[str] = None,
) -> int:
    """Implement ``gpa drawcalls sources set --dc N (--file PATH | --body-json TEXT)``."""
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
        data = client.post_json(f"/api/v1/frames/{fid}/drawcalls/{dc}/sources", body)
    except RestError as exc:
        print(f"[gpa] {exc}", file=sys.stderr)
        return 1

    _print_json(data, print_stream)
    return 0


# --------------------------------------------------------------------------- #
# Top-level dispatcher (args-based)
# --------------------------------------------------------------------------- #


def run(args, *, client: Optional[RestClient] = None, print_stream=None) -> int:
    """Dispatch ``drawcalls`` subverbs from parsed ``args``."""
    session_dir: Optional[Path] = getattr(args, "session", None)
    drawcalls_cmd = getattr(args, "drawcalls_cmd", None)

    common = dict(session_dir=session_dir, client=client, print_stream=print_stream)

    if drawcalls_cmd == "list":
        return run_list(
            **common,
            frame=getattr(args, "frame", None),
            limit=getattr(args, "limit", None),
            offset=getattr(args, "offset", None),
        )

    if drawcalls_cmd == "get":
        return run_get(**common, frame=getattr(args, "frame", None), dc=args.dc)

    if drawcalls_cmd == "shader":
        return run_shader(**common, frame=getattr(args, "frame", None), dc=args.dc)

    if drawcalls_cmd == "textures":
        return run_textures(**common, frame=getattr(args, "frame", None), dc=args.dc)

    if drawcalls_cmd == "vertices":
        return run_vertices(**common, frame=getattr(args, "frame", None), dc=args.dc)

    if drawcalls_cmd == "attachments":
        return run_attachments(**common, frame=getattr(args, "frame", None), dc=args.dc)

    if drawcalls_cmd == "nan-uniforms":
        return run_nan_uniforms(**common, frame=getattr(args, "frame", None), dc=args.dc)

    if drawcalls_cmd == "feedback-loops":
        return run_feedback_loops(**common, frame=getattr(args, "frame", None), dc=args.dc)

    if drawcalls_cmd == "explain":
        return run_explain(**common, frame=getattr(args, "frame", None), dc=args.dc)

    if drawcalls_cmd == "diff":
        return run_diff(
            **common,
            frame=getattr(args, "frame", None),
            a=args.a,
            b=args.b,
            scope=getattr(args, "scope", "all"),
        )

    if drawcalls_cmd == "sources":
        sources_cmd = getattr(args, "sources_cmd", None)
        if sources_cmd == "get":
            return run_sources_get(**common, frame=getattr(args, "frame", None), dc=args.dc)
        if sources_cmd == "set":
            return run_sources_set(
                **common,
                frame=getattr(args, "frame", None),
                dc=args.dc,
                body_json=getattr(args, "body_json", None),
                file_path=getattr(args, "file_path", None),
            )
        print(f"[gpa] unknown sources subcommand: {sources_cmd!r}", file=sys.stderr)
        return 1

    # Should not be reached since argparse validates required=True.
    print(f"[gpa] unknown drawcalls subcommand: {drawcalls_cmd!r}", file=sys.stderr)
    return 1
