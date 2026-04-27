"""``GET /api/v1/frames`` — list every frame id retrievable in this session.

Returns a JSON object ``{"frames": [int, ...]}`` so future fields (cursor,
counts, etc.) can be added without breaking clients.  Empty session yields
``{"frames": []}``.

Read-only.  Uses :meth:`FrameProvider.list_frame_ids`.
"""

from __future__ import annotations

from fastapi import APIRouter, Request

from gpa.api.app import safe_json_response

router = APIRouter(tags=["frames"])


@router.get("/frames")
def list_frames(request: Request):
    """Return every frame id the active session can serve."""
    provider = request.app.state.provider
    try:
        ids = list(provider.list_frame_ids())
    except NotImplementedError:
        # Backends that legitimately don't support enumeration return an
        # empty list rather than 501; callers fall back to ``latest``.
        ids = []
    # Coerce to ints — defensive against backends that return numpy / etc.
    ids = [int(i) for i in ids]
    return safe_json_response({"frames": ids, "count": len(ids)})
