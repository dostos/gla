"""``gpa scene-find <predicate>`` — predicate-driven scene-graph search.

Finds scene-graph nodes matching every supplied predicate (CSV-AND form),
each annotated with the draw-call IDs whose ``debug_groups`` resolve to
the node. Requires a Tier-3 plugin's annotation to be present.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

from gpa.cli.rest_client import RestClient, RestError
from gpa.cli.session import Session


_KNOWN_PREDICATES_HINT = (
    "material:{transparent|opaque}, material-name:NAME, "
    "name-contains:S, type:T, uniform-has-nan, texture:missing"
)


def add_subparser(subparsers) -> None:
    epilog = (
        "Examples:\n"
        "  gpa scene-find material:transparent              # 1) simplest\n"
        "  gpa scene-find material:transparent,uniform-has-nan   # 2) AND\n"
        "  gpa scene-find type:Mesh,name-contains:visor --json    # 3) JSON\n"
        "  gpa scene-find material-name:Glass --json \\\n"
        "    | jq -r '.matches[].draw_call_ids[]' \\\n"
        "    | xargs -I% gpa explain-draw %                       # 4) pipeline\n"
        "  gpa scene-find name-contains:Helmet --frame 7 --limit 3\n"
        "                                                         # 5) bounded\n"
    )
    p = subparsers.add_parser(
        "scene-find",
        help="Predicate-driven scene-graph search (returns matches + draw IDs)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=epilog,
    )
    p.add_argument(
        "predicates", nargs="+",
        help=(
            "One or more CSV-AND predicates. Known: " + _KNOWN_PREDICATES_HINT
        ),
    )
    p.add_argument(
        "--session", dest="session", type=Path, default=None,
        help="Session directory (overrides $GPA_SESSION and the link)",
    )
    p.add_argument(
        "--frame", dest="frame", default=None,
        help="Frame id (default: latest).",
    )
    p.add_argument(
        "--limit", dest="limit", type=int, default=10,
        help="Cap matches (default 10; refuses unbounded queries)",
    )
    p.add_argument(
        "--json", dest="json_output", action="store_true",
        help="Emit machine-readable JSON instead of plain text",
    )


def _format_human(payload: Dict[str, Any]) -> str:
    lines: List[str] = []
    fid = payload.get("frame_id")
    pred = payload.get("predicate")
    matches = payload.get("matches") or []
    limit = payload.get("limit")
    lines.append(
        f"scene-find frame {fid}  predicate={pred}  matches={len(matches)} "
        f"(limit {limit})"
    )
    if not matches:
        lines.append("")
        if not payload.get("annotation_present"):
            lines.append(
                "(no scene-graph annotation found — install a Tier-3 plugin; "
                "see docs/superpowers/specs/"
                "2026-04-18-framework-integration-design.md)"
            )
        else:
            lines.append("(no nodes matched)")
        return "\n".join(lines) + "\n"
    lines.append("")
    for m in matches:
        path = m.get("path")
        ntype = m.get("type") or ""
        material = m.get("material_name") or "(no material)"
        ids = m.get("draw_call_ids") or []
        lines.append(
            f"  {path:<40s}  {ntype:<8s}  {material:<28s}  draws={ids}"
        )
    if payload.get("truncated"):
        lines.append("  … (truncated at --limit; raise --limit for more)")
    return "\n".join(lines) + "\n"


def run(
    *,
    predicates: List[str],
    session_dir: Optional[Path] = None,
    frame: Optional[str] = None,
    limit: int = 10,
    json_output: bool = False,
    client: Optional[RestClient] = None,
    print_stream=None,
) -> int:
    if print_stream is None:
        print_stream = sys.stdout

    if not predicates:
        print(
            "Error: scene-find requires at least one predicate.\n"
            "  gpa scene-find material:transparent",
            file=sys.stderr,
        )
        return 2
    if limit <= 0:
        print(
            "Error: --limit must be positive (refuses unbounded scans).",
            file=sys.stderr,
        )
        return 2
    if frame is not None:
        try:
            int(frame)
        except ValueError:
            print(
                f"Error: --frame must be an integer, got {frame!r}.\n"
                "  gpa scene-find type:Mesh --frame 7",
                file=sys.stderr,
            )
            return 2

    sess = Session.discover(explicit=session_dir)
    if sess is None:
        print(
            "Error: no active GPA session. Run 'gpa start' first.",
            file=sys.stderr,
        )
        return 2

    if client is None:
        try:
            client = RestClient.from_session(sess)
        except Exception as exc:  # noqa: BLE001
            print(f"[gpa] failed to connect to engine: {exc}", file=sys.stderr)
            return 1

    fid_part = "latest" if frame is None else int(frame)
    qparts: List[str] = [f"limit={int(limit)}"]
    for p in predicates:
        from urllib.parse import quote
        qparts.append(f"predicate={quote(p, safe=':,-_+%')}")
    path = f"/api/v1/frames/{fid_part}/scene/find?" + "&".join(qparts)
    try:
        payload = client.get_json(path)
    except RestError as exc:
        if exc.status == 400:
            print(
                f"[gpa] {exc}\n  Known predicates: {_KNOWN_PREDICATES_HINT}\n"
                "  Example: gpa scene-find material:transparent,name-contains:visor",
                file=sys.stderr,
            )
            return 2
        print(f"[gpa] {exc}", file=sys.stderr)
        return 1
    if not isinstance(payload, dict):
        print(f"[gpa] unexpected response shape: {type(payload).__name__}",
              file=sys.stderr)
        return 1

    matches = payload.get("matches") or []
    if not matches and not payload.get("annotation_present"):
        # No annotation at all — clear directive to install plugin.
        print(
            f"[gpa] no scene-graph annotation for frame {payload.get('frame_id')}"
            " — need a Tier-3 plugin. See "
            "docs/superpowers/specs/"
            "2026-04-18-framework-integration-design.md.",
            file=sys.stderr,
        )
        return 1

    if json_output:
        print_stream.write(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    else:
        print_stream.write(_format_human(payload))
    print_stream.flush()
    return 0 if matches else 1
