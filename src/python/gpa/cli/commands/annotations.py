"""``gpa annotations --frame N`` — GET the stored annotation payload."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Optional

from gpa.cli.rest_client import RestClient, RestError
from gpa.cli.session import Session


def run(
    *,
    frame: int,
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

    try:
        data = client.get_json(f"/api/v1/frames/{int(frame)}/annotations")
    except RestError as exc:
        print(f"[gpa] {exc}", file=sys.stderr)
        return 1

    print_stream.write(json.dumps(data, indent=2) + "\n")
    print_stream.flush()
    return 0
