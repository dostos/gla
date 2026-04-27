"""``gpa frames`` — list captured frame ids for the active session.

Calls the ``GET /api/v1/frames`` endpoint, which returns
``{"frames": [int, ...], "count": int}``.  When the session is empty the
endpoint returns an empty list and we exit 0 with no stdout output (so
``gpa frames | wc -l`` is a clean "is anything captured yet?" probe).

Exit codes:
    0  success (including empty session)
    1  REST / transport error
    2  no active session found
"""

from __future__ import annotations

import json
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
    json_output: bool = False,
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

    if json_output:
        print_stream.write(json.dumps({"frames": ids, "count": len(ids)}) + "\n")
    else:
        for fid in ids:
            print_stream.write(f"{fid}\n")
    print_stream.flush()
    return 0
