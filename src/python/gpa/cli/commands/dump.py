"""``gpa dump <what>`` — raw REST data printed in text/json/compact form."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

from gpa.cli.rest_client import RestClient, RestError
from gpa.cli.session import Session


# --------------------------------------------------------------------------- #
# Formatting helpers
# --------------------------------------------------------------------------- #


def _compact_kv(data: Dict[str, Any]) -> str:
    """Render one dict as a single line of ``key=value key=value``."""
    parts = []
    for k, v in data.items():
        if isinstance(v, (list, dict)):
            parts.append(f"{k}={json.dumps(v, separators=(',', ':'))}")
        else:
            parts.append(f"{k}={v}")
    return " ".join(parts)


def _plain_table(rows: List[Dict[str, Any]], columns: List[str]) -> str:
    if not rows:
        return ""
    # Precompute widths for simple left-aligned tab-padded columns.
    widths = {c: len(c) for c in columns}
    for r in rows:
        for c in columns:
            widths[c] = max(widths[c], len(str(r.get(c, ""))))
    header = "  ".join(c.ljust(widths[c]) for c in columns)
    lines = [header]
    for r in rows:
        lines.append("  ".join(str(r.get(c, "")).ljust(widths[c]) for c in columns))
    return "\n".join(lines)


# --------------------------------------------------------------------------- #
# Individual dumpers
# --------------------------------------------------------------------------- #


def _dump_frame(client: RestClient, frame_id: int, fmt: str) -> str:
    data = client.get_json(f"/api/v1/frames/{frame_id}/overview")
    if fmt == "json":
        return json.dumps(data, indent=2)
    if fmt == "compact":
        return _compact_kv(data)
    # plain
    lines = [f"{k}\t{v}" for k, v in data.items()]
    return "\n".join(lines)


def _dump_drawcalls(client: RestClient, frame_id: int, fmt: str) -> str:
    data = client.get_json(
        f"/api/v1/frames/{frame_id}/drawcalls?limit=500&offset=0"
    )
    items = data.get("items", [])
    if fmt == "json":
        return json.dumps(data, indent=2)
    if fmt == "compact":
        return "\n".join(_compact_kv(i) for i in items)
    columns = ["id", "primitive_type", "vertex_count", "instance_count", "shader_id"]
    return _plain_table(items, columns)


def _dump_pixel(
    client: RestClient, frame_id: int, x: int, y: int, fmt: str
) -> str:
    data = client.get_json(f"/api/v1/frames/{frame_id}/pixel/{x}/{y}")
    if fmt == "json":
        return json.dumps(data, indent=2)
    if fmt == "compact":
        return _compact_kv(data)
    lines = [f"{k}\t{v}" for k, v in data.items()]
    return "\n".join(lines)


# --------------------------------------------------------------------------- #
# Removed subtargets — preserve the names so users get a helpful redirect
# rather than a generic "unknown target" error. The audit
# (docs/superpowers/specs/2026-04-27-bidirectional-narrow-queries-design.md)
# identified `dump drawcall|shader|textures|attachments` as the +$0.39/pair
# regression cause: agents called dump 6-8x per scenario and grep'd verbose
# JSON. The bidirectional-narrow commands replace them. Keep the names alive
# so a stale prompt or muscle-memory invocation fails LOUDLY (exit 3) with a
# concrete redirect message instead of silently doing the wrong thing.
# --------------------------------------------------------------------------- #


REMOVED_SUBTARGETS = {
    "drawcall": "use `gpa explain-draw <id>` instead",
    "shader": "use `gpa explain-draw <id> --field shader` instead",
    "textures": "use `gpa explain-draw <id> --field textures` instead",
    "attachments": (
        "use `gpa check-config --rule mipmap-on-npot-without-min-filter` "
        "(or another config rule) instead"
    ),
}


# --------------------------------------------------------------------------- #
# Entry point
# --------------------------------------------------------------------------- #


_DISPATCH = {
    "frame": ("frame", True, False, False),
    "drawcalls": ("drawcalls", True, False, False),
    "pixel": ("pixel", True, False, True),
}


def run(
    *,
    what: str,
    session_dir: Optional[Path] = None,
    frame: Optional[int] = None,
    dc: Optional[int] = None,
    x: Optional[int] = None,
    y: Optional[int] = None,
    fmt: str = "plain",
    client: Optional[RestClient] = None,
    print_stream=None,
) -> int:
    if print_stream is None:
        print_stream = sys.stdout

    # Removed subtargets — fail loud with a redirect to the narrow command.
    if what in REMOVED_SUBTARGETS:
        redirect = REMOVED_SUBTARGETS[what]
        print(
            f"[gpa] `dump {what}` was removed — {redirect}.",
            file=sys.stderr,
        )
        return 3

    if what not in _DISPATCH:
        known = ", ".join(sorted(_DISPATCH))
        print(f"[gpa] unknown dump target: {what!r}. Known: {known}", file=sys.stderr)
        return 1

    _, needs_frame, needs_dc, needs_xy = _DISPATCH[what]

    sess = Session.discover(explicit=session_dir)
    if sess is None:
        print("[gpa] no active session found", file=sys.stderr)
        return 2

    if client is None:
        try:
            client = RestClient.from_session(sess)
        except Exception as exc:  # noqa: BLE001
            print(f"[gpa] failed to connect to engine: {exc}", file=sys.stderr)
            return 1

    # Resolve frame id (default: latest).
    if needs_frame and frame is None:
        try:
            overview = client.get_json("/api/v1/frames/current/overview")
        except RestError as exc:
            print(f"[gpa] {exc}", file=sys.stderr)
            return 1
        frame_id = int(overview.get("frame_id", 0) or 0)
    else:
        frame_id = int(frame) if frame is not None else 0

    if needs_dc and dc is None:
        print(f"[gpa] dump {what} requires --dc N", file=sys.stderr)
        return 1
    if needs_xy and (x is None or y is None):
        print(f"[gpa] dump {what} requires --x and --y", file=sys.stderr)
        return 1

    try:
        if what == "frame":
            text = _dump_frame(client, frame_id, fmt)
        elif what == "drawcalls":
            text = _dump_drawcalls(client, frame_id, fmt)
        elif what == "pixel":
            text = _dump_pixel(client, frame_id, int(x), int(y), fmt)
        else:  # pragma: no cover
            return 1
    except RestError as exc:
        print(f"[gpa] {exc}", file=sys.stderr)
        return 1

    print_stream.write(text)
    if not text.endswith("\n"):
        print_stream.write("\n")
    print_stream.flush()
    return 0
