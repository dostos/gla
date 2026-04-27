"""``gpa trace {uniform|texture|value}`` — reverse-lookup value attribution.

Hits the engine's trace endpoints to resolve a captured value back to
the app-level JS fields that currently hold it. Plain-text output is
agent-friendly; ``--json`` emits the raw REST response.

See ``docs/superpowers/specs/2026-04-20-gpa-trace-design.md``.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional
from urllib.parse import quote

from gpa.cli.rest_client import RestClient, RestError
from gpa.cli.session import Session


# ---------------------------------------------------------------------------
# Frame resolution
# ---------------------------------------------------------------------------

def _resolve_frame(client: RestClient, frame: Optional[int]) -> Optional[int]:
    if frame is not None:
        return int(frame)
    try:
        ov = client.get_json("/api/v1/frames/current/overview")
    except RestError:
        return None
    if not isinstance(ov, dict):
        return None
    try:
        return int(ov.get("frame_id", 0) or 0)
    except (TypeError, ValueError):
        return None


# ---------------------------------------------------------------------------
# Output formatting
# ---------------------------------------------------------------------------

def format_text(resp: Dict[str, Any]) -> str:
    """Render the trace response as the spec's plain-text block."""
    field = resp.get("field")
    value = resp.get("value")
    frame_id = resp.get("frame_id")
    dc_id = resp.get("dc_id")
    candidates = resp.get("candidates") or []
    call_site = resp.get("call_site")
    hint = resp.get("hint")

    header_prefix = field if field else "value"
    coords: List[str] = []
    if frame_id is not None:
        coords.append(f"frame {frame_id}")
    if dc_id is not None:
        coords.append(f"dc {dc_id}")
    coord_str = f" ({', '.join(coords)})" if coords else ""
    value_str = _fmt_value(value)

    lines = [f"{header_prefix}{coord_str} = {value_str}"]

    if call_site:
        lines.append(f"  set at: {call_site}")

    if candidates:
        lines.append("  candidates:")
        # Determine column widths for nicer alignment.
        tier_w = max(len(c.get("confidence", "high")) for c in candidates)
        path_w = max(len(str(c.get("path", ""))) for c in candidates)
        path_w = min(path_w, 60)  # hard cap so long paths don't blow the table
        for c in candidates:
            tier = c.get("confidence", "high")
            path = str(c.get("path", ""))
            hops = c.get("distance_hops", 0)
            hop_s = f"{hops} hop" if hops == 1 else f"{hops} hops"
            lines.append(
                f"    [{tier:<{tier_w}}] {path:<{path_w}}  ({hop_s})"
            )
    elif hint:
        lines.append(f"  hint: {hint}")
    else:
        lines.append("  (no candidates)")

    return "\n".join(lines) + "\n"


def _fmt_value(v: Any) -> str:
    if v is None:
        return "<unknown>"
    if isinstance(v, float):
        # Preserve the reader's expected precision without going full float-repr.
        return f"{v:g}"
    if isinstance(v, (list, tuple)):
        return "[" + ", ".join(_fmt_value(x) for x in v) + "]"
    return str(v)


# ---------------------------------------------------------------------------
# Per-subcommand runners
# ---------------------------------------------------------------------------

def _emit(resp: Dict[str, Any], *, json_output: bool, print_stream) -> None:
    if json_output:
        print_stream.write(json.dumps(resp, indent=2) + "\n")
    else:
        print_stream.write(format_text(resp))
    print_stream.flush()


def _connect(
    *,
    session_dir: Optional[Path],
    client: Optional[RestClient],
) -> tuple:
    """Return ``(client, exit_code_if_error_or_None)``."""
    if client is not None:
        return client, None
    sess = Session.discover(explicit=session_dir)
    if sess is None:
        print("[gpa] no active session found", file=sys.stderr)
        return None, 2
    try:
        return RestClient.from_session(sess), None
    except Exception as exc:  # noqa: BLE001
        print(f"[gpa] failed to connect to engine: {exc}", file=sys.stderr)
        return None, 1


def _require_dc(dc: Optional[int]) -> int:
    if dc is None:
        raise ValueError("--dc is required for this subcommand")
    return int(dc)


def run_uniform(
    *,
    name: str,
    frame: Optional[int] = None,
    dc: Optional[int] = None,
    session_dir: Optional[Path] = None,
    json_output: bool = False,
    client: Optional[RestClient] = None,
    print_stream=None,
) -> int:
    if print_stream is None:
        print_stream = sys.stdout
    client, err = _connect(session_dir=session_dir, client=client)
    if err is not None:
        return err
    try:
        dc_id = _require_dc(dc)
    except ValueError as exc:
        print(f"[gpa] {exc}", file=sys.stderr)
        return 2

    frame_id = _resolve_frame(client, frame)
    if frame_id is None:
        print("[gpa] no frames captured yet", file=sys.stderr)
        return 4

    path = (
        f"/api/v1/frames/{frame_id}/drawcalls/{dc_id}"
        f"/trace/uniform/{quote(name, safe='')}"
    )
    try:
        resp = client.get_json(path)
    except RestError as exc:
        print(f"[gpa] {exc}", file=sys.stderr)
        return 1
    _emit(resp, json_output=json_output, print_stream=print_stream)
    return 0


def run_value(
    *,
    literal: str,
    frame: Optional[int] = None,
    dc: Optional[int] = None,
    session_dir: Optional[Path] = None,
    json_output: bool = False,
    client: Optional[RestClient] = None,
    print_stream=None,
) -> int:
    if print_stream is None:
        print_stream = sys.stdout
    client, err = _connect(session_dir=session_dir, client=client)
    if err is not None:
        return err

    frame_id = _resolve_frame(client, frame)
    if frame_id is None:
        print("[gpa] no frames captured yet", file=sys.stderr)
        return 4

    if dc is None:
        path = (
            f"/api/v1/frames/{frame_id}/trace/value"
            f"?query={quote(str(literal), safe='')}"
        )
    else:
        path = (
            f"/api/v1/frames/{frame_id}/drawcalls/{int(dc)}"
            f"/trace/value?query={quote(str(literal), safe='')}"
        )
    try:
        resp = client.get_json(path)
    except RestError as exc:
        print(f"[gpa] {exc}", file=sys.stderr)
        return 1
    _emit(resp, json_output=json_output, print_stream=print_stream)
    return 0


# ---------------------------------------------------------------------------
# Public entry — called by cli/main.py
# ---------------------------------------------------------------------------

def run(
    *,
    subcommand: str,
    target: str,
    frame: Optional[int] = None,
    dc: Optional[int] = None,
    session_dir: Optional[Path] = None,
    json_output: bool = False,
    client: Optional[RestClient] = None,
    print_stream=None,
) -> int:
    if subcommand == "uniform":
        return run_uniform(
            name=target, frame=frame, dc=dc, session_dir=session_dir,
            json_output=json_output, client=client, print_stream=print_stream,
        )
    if subcommand == "value":
        return run_value(
            literal=target, frame=frame, dc=dc, session_dir=session_dir,
            json_output=json_output, client=client, print_stream=print_stream,
        )
    print(f"[gpa] unknown trace subcommand: {subcommand!r}", file=sys.stderr)
    return 2
