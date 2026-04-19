"""``gpa annotate --frame N KEY=VALUE...`` — POST a flat-dict annotation."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import List, Optional

from gpa.cli.rest_client import RestClient, RestError
from gpa.cli.session import Session


def _parse_kv_pairs(pairs: List[str]) -> dict:
    """Parse ``KEY=VALUE`` strings into a dict.

    Values are JSON-parsed first so callers can pass ``count=12`` or
    ``flag=true`` without manual casting; a parse error falls back to
    treating the value as a literal string.
    """
    result = {}
    for p in pairs:
        if "=" not in p:
            raise ValueError(f"bad KEY=VALUE pair: {p!r}")
        k, v = p.split("=", 1)
        try:
            parsed = json.loads(v)
        except ValueError:
            parsed = v
        result[k] = parsed
    return result


def run(
    *,
    frame: int,
    pairs: List[str],
    session_dir: Optional[Path] = None,
    client: Optional[RestClient] = None,
    print_stream=None,
) -> int:
    if print_stream is None:
        print_stream = sys.stdout

    try:
        body = _parse_kv_pairs(pairs)
    except ValueError as exc:
        print(f"[gpa] {exc}", file=sys.stderr)
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

    try:
        resp = client.post_json(
            f"/api/v1/frames/{int(frame)}/annotations", body
        )
    except RestError as exc:
        print(f"[gpa] {exc}", file=sys.stderr)
        return 1

    print_stream.write(json.dumps(resp) + "\n")
    print_stream.flush()
    return 0
