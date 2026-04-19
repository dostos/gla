"""``gpa check <name>`` — drill-down into a single diagnostic."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Optional

from gpa.cli import checks as checks_mod
from gpa.cli.formatting import err_line, ok_line, use_color, warn_line
from gpa.cli.rest_client import RestClient, RestError
from gpa.cli.session import Session


def _format_detail(finding_detail: dict) -> str:
    parts = []
    for k, v in finding_detail.items():
        parts.append(f"{k}={v}")
    return "  ".join(parts)


def run(
    *,
    name: str,
    session_dir: Optional[Path] = None,
    frame: Optional[int] = None,
    dc: Optional[int] = None,
    json_output: bool = False,
    client: Optional[RestClient] = None,
    print_stream=None,
) -> int:
    if print_stream is None:
        print_stream = sys.stdout

    check = checks_mod.get_check(name)
    if check is None:
        known = ", ".join(checks_mod.known_names())
        print(
            f"[gpa] unknown check: {name!r}. Known: {known}",
            file=sys.stderr,
        )
        return 1

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
    if frame is None:
        try:
            overview = client.get_json("/api/v1/frames/current/overview")
        except RestError as exc:
            print(f"[gpa] {exc}", file=sys.stderr)
            return 1
        frame_id = int(overview.get("frame_id", 0) or 0)
    else:
        frame_id = int(frame)

    try:
        result = check.run(client, frame_id=frame_id, dc_id=dc)
    except RestError as exc:
        print(f"[gpa] {exc}", file=sys.stderr)
        return 1
    except Exception as exc:  # noqa: BLE001
        print(f"[gpa] check {name} failed: {exc}", file=sys.stderr)
        return 1

    if json_output:
        payload = {
            "frame": frame_id,
            "check": name,
            **result.to_dict(),
        }
        print_stream.write(json.dumps(payload, indent=2) + "\n")
        print_stream.flush()
    else:
        colored = use_color(print_stream)
        if result.status == "ok":
            print_stream.write(ok_line(name, enabled=colored) + "\n")
        elif result.status == "error":
            print_stream.write(
                err_line(name, result.error or "check failed", enabled=colored) + "\n"
            )
        else:
            plural = "" if len(result.findings) == 1 else "s"
            print_stream.write(
                warn_line(
                    name,
                    f"{len(result.findings)} finding{plural}",
                    enabled=colored,
                )
                + "\n"
            )
            for f in result.findings:
                print_stream.write(f"  {f.summary}\n")
                if f.detail:
                    print_stream.write(f"    {_format_detail(f.detail)}\n")
        print_stream.flush()

    if result.status == "warn":
        return 3
    if result.status == "error":
        return 1
    return 0
