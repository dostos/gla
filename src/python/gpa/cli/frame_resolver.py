"""Resolve --frame for CLI commands.

Precedence:
1. Explicit --frame value (int or 'latest')
2. ``GPA_FRAME_ID`` env var (when --frame omitted)
3. REST ``current`` overview

Explicit 'latest' deliberately bypasses the env var: when an agent
passes --frame latest, it wants the current frame, not a stale pin.
"""
from __future__ import annotations

import os
from typing import Optional, Union, Protocol


class _SupportsGetJson(Protocol):
    def get_json(self, path: str): ...


def resolve_frame(
    *, client: _SupportsGetJson,
    explicit: Optional[Union[int, str]],
) -> int:
    if explicit is not None:
        if explicit == "latest":
            return _fetch_current(client)
        return int(explicit)
    env = os.environ.get("GPA_FRAME_ID", "").strip()
    if env:
        return int(env)
    return _fetch_current(client)


def _fetch_current(client: _SupportsGetJson) -> int:
    overview = client.get_json("/api/v1/frames/current/overview")
    return int(overview["frame_id"])
