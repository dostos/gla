"""``gpa frames`` — list captured frame ids for the active session."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Optional

from gpa.cli.rest_client import RestClient, RestError
from gpa.cli.session import Session


def run(
    *,
    session_dir: Optional[Path] = None,
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

    # Derive the frame list from /frames/current/overview — the engine does
    # not yet expose a plain list endpoint, but the overview surfaces
    # ``frame_id`` and a caller can repeatedly poll /frames/{id}/overview
    # backwards to enumerate.  We try /api/v1/frames first (legacy); if it
    # 404s, fall back to "latest only".
    ids: list[int] = []
    try:
        data = client.get_json("/api/v1/frames")
        if isinstance(data, dict) and isinstance(data.get("frames"), list):
            ids = [int(f) for f in data["frames"]]
        elif isinstance(data, list):
            ids = [int(f) for f in data]
    except RestError:
        try:
            ov = client.get_json("/api/v1/frames/current/overview")
            if isinstance(ov, dict):
                ids = [int(ov.get("frame_id", 0) or 0)]
        except RestError as exc:
            print(f"[gpa] {exc}", file=sys.stderr)
            return 1

    for fid in ids:
        print_stream.write(f"{fid}\n")
    print_stream.flush()
    return 0
