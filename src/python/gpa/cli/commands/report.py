"""``gpa report`` — run every registered check and print a summary.

This is the command an agent is expected to run first in any session. Its
plain-text output is deliberately tight (≤300 tokens clean, ≤600 with
warnings) so agents don't burn context just reading diagnostics.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Iterable, List, Optional

from gpa.cli import checks as checks_mod
from gpa.cli.checks import CheckResult
from gpa.cli.formatting import (
    drill_line,
    err_line,
    ok_line,
    use_color,
    warn_line,
)
from gpa.cli.rest_client import RestClient, RestError
from gpa.cli.session import Session


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #


def _resolve_frame_id(client: RestClient, frame: Optional[int]) -> Optional[int]:
    """Return the effective frame id. ``None`` if no frame is available."""
    if frame is not None:
        return int(frame)
    try:
        overview = client.get_json("/api/v1/frames/current/overview")
    except RestError:
        return None
    if not isinstance(overview, dict):
        return None
    return int(overview.get("frame_id", 0) or 0)


def _select_checks(only: Iterable[str] = (), skip: Iterable[str] = ()):
    only_set = {s.strip() for s in only if s.strip()}
    skip_set = {s.strip() for s in skip if s.strip()}
    result = []
    for c in checks_mod.all_checks():
        if only_set and c.name not in only_set:
            continue
        if c.name in skip_set:
            continue
        result.append(c)
    return result


def _run_checks(client: RestClient, frame_id: int, selected) -> List[CheckResult]:
    results: List[CheckResult] = []
    for c in selected:
        try:
            results.append(c.run(client, frame_id=frame_id))
        except RestError as exc:
            results.append(
                CheckResult(name=c.name, status="error", error=str(exc))
            )
        except Exception as exc:  # noqa: BLE001
            results.append(
                CheckResult(name=c.name, status="error", error=str(exc))
            )
    return results


# --------------------------------------------------------------------------- #
# Output formatters
# --------------------------------------------------------------------------- #


def _format_text(
    *,
    frame_id: int,
    draw_call_count: int,
    session_dir: Path,
    results: List[CheckResult],
    colored: bool,
) -> str:
    lines: List[str] = []
    lines.append(
        f"gpa report — frame {frame_id} (session {session_dir})"
    )
    lines.append(f"{draw_call_count} draw calls captured")
    lines.append("")

    # Warnings/errors first, in registered order.
    warning_count = 0
    for r in results:
        if r.status == "warn":
            warning_count += 1
            summary = (
                r.findings[0].summary if r.findings
                else f"{len(r.findings)} finding(s)"
            )
            # Header: one-line count + first-finding summary
            findings_count = len(r.findings)
            header = (
                f"{findings_count} finding"
                if findings_count == 1
                else f"{findings_count} findings"
            )
            lines.append(warn_line(r.name, header, enabled=colored))
            for f in r.findings:
                lines.append(f"  {f.summary}")
            # One drill hint per distinct dc_id (preserving first-seen
            # order). If a finding has no dc_id (per-frame check), emit a
            # single hint without --dc.
            seen_dcs: List[int] = []
            saw_no_dc = False
            for f in r.findings:
                did = f.detail.get("dc_id")
                if did is None:
                    saw_no_dc = True
                else:
                    did_int = int(did)
                    if did_int not in seen_dcs:
                        seen_dcs.append(did_int)
            if saw_no_dc and not seen_dcs:
                lines.append(drill_line(r.name, frame_id, enabled=colored))
            for did_int in seen_dcs:
                lines.append(
                    drill_line(r.name, frame_id, did_int, enabled=colored)
                )
            lines.append("")
        elif r.status == "error":
            warning_count += 1
            lines.append(
                err_line(r.name, r.error or "check failed", enabled=colored)
            )
            lines.append("")

    # Passing checks next, collapsed.
    for r in results:
        if r.status == "ok":
            lines.append(ok_line(r.name, enabled=colored))

    lines.append("")
    if warning_count == 0:
        lines.append("0 warnings. GPA found no state-level issues in this frame.")
        lines.append(
            "If the symptom is still visible, the bug is outside GPA's capture layer"
        )
        lines.append(
            "(framework logic, shader math, or driver-specific behavior) — read the"
        )
        lines.append("app/framework source or reason through the shader.")
    else:
        plural = "" if warning_count == 1 else "s"
        lines.append(
            f"{warning_count} warning{plural} found. These describe observable GL state. If drilling into a"
        )
        lines.append(
            "warning reveals a clear fix, act on it. Otherwise the root cause is"
        )
        lines.append(
            "likely upstream — read the app/framework source for why the state ended"
        )
        lines.append("up this way.")
    return "\n".join(lines) + "\n"


def _format_json(
    *,
    frame_id: int,
    session_dir: Path,
    results: List[CheckResult],
) -> str:
    warning_count = sum(1 for r in results if r.status != "ok")
    payload = {
        "frame": frame_id,
        "session": str(session_dir),
        "checks": [r.to_dict() for r in results],
        "warning_count": warning_count,
    }
    return json.dumps(payload, indent=2) + "\n"


# --------------------------------------------------------------------------- #
# Entry point
# --------------------------------------------------------------------------- #


def run(
    *,
    session_dir: Optional[Path] = None,
    frame: Optional[int] = None,
    json_output: bool = False,
    only: Optional[List[str]] = None,
    skip: Optional[List[str]] = None,
    client: Optional[RestClient] = None,
    print_stream=None,
) -> int:
    if print_stream is None:
        print_stream = sys.stdout

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

    frame_id = _resolve_frame_id(client, frame)
    if frame_id is None:
        # No frame available at all — treat as empty capture, exit 4.
        print("[gpa] no frames captured yet", file=sys.stderr)
        return 4

    try:
        overview = client.get_json(f"/api/v1/frames/{frame_id}/overview")
    except RestError as exc:
        print(f"[gpa] frame overview unavailable: {exc}", file=sys.stderr)
        return 1
    draw_call_count = int(overview.get("draw_call_count", 0) or 0)

    selected = _select_checks(only or [], skip or [])
    results = _run_checks(client, frame_id, selected)

    if json_output:
        print_stream.write(_format_json(
            frame_id=frame_id, session_dir=sess.dir, results=results
        ))
    else:
        colored = use_color(print_stream)
        print_stream.write(_format_text(
            frame_id=frame_id,
            draw_call_count=draw_call_count,
            session_dir=sess.dir,
            results=results,
            colored=colored,
        ))
    print_stream.flush()

    # Exit-code precedence:
    #   4 — capture empty (no draws, regardless of other warnings)
    #   3 — at least one warning/error
    #   0 — all clean
    if draw_call_count == 0:
        return 4
    if any(r.status != "ok" for r in results):
        return 3
    return 0
