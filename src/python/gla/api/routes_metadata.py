"""Metadata sidecar endpoints for framework plugins.

Framework plugins (Three.js, Unity, Unreal, etc.) POST scene graph data for
a captured frame.  This data is stored in the MetadataStore and can be
retrieved for display or correlation with GPU draw calls.

Routes:
    POST /api/v1/frames/{frame_id}/metadata  — store metadata
    GET  /api/v1/frames/{frame_id}/metadata  — retrieve metadata summary
"""
from __future__ import annotations

from typing import Any, Dict

from fastapi import APIRouter, HTTPException, Request

from gla.api.app import safe_json_response

router = APIRouter(tags=["metadata"])


@router.post("/frames/{frame_id}/metadata", status_code=200)
def post_frame_metadata(
    frame_id: int,
    payload: Dict[str, Any],
    request: Request,
):
    """Store framework scene graph metadata for *frame_id*.

    The JSON body is an arbitrary object understood by the calling framework
    plugin.  Required top-level keys are optional — missing keys are silently
    defaulted.
    """
    store = request.app.state.metadata_store
    store.store(frame_id, payload)
    return safe_json_response({"status": "ok", "frame_id": frame_id})


@router.get("/frames/{frame_id}/metadata")
def get_frame_metadata(
    frame_id: int,
    request: Request,
):
    """Return a summary of stored metadata for *frame_id*.

    Raises 404 if no metadata has been posted for this frame.
    """
    store = request.app.state.metadata_store
    metadata = store.get(frame_id)
    if metadata is None:
        raise HTTPException(
            status_code=404,
            detail=f"No metadata found for frame {frame_id}",
        )

    return safe_json_response({
        "frame_id": frame_id,
        "framework": metadata.framework,
        "version": metadata.version,
        "object_count": len(metadata.objects),
        "material_count": len(metadata.materials),
        "render_pass_count": len(metadata.render_passes),
    })
