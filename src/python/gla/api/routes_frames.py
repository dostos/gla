"""Frame overview and framebuffer endpoints."""
from dataclasses import asdict
from typing import Any, Dict

from fastapi import APIRouter, HTTPException, Request

router = APIRouter(tags=["frames"])


@router.get("/frames/current/overview")
def get_current_frame_overview(request: Request) -> Dict[str, Any]:
    """Return an overview of the most recently captured frame."""
    provider = request.app.state.provider
    overview = provider.get_latest_overview()
    if overview is None:
        raise HTTPException(status_code=404, detail="No frame captured yet")
    d = asdict(overview)
    # Keep the JSON key names the routes have always used
    d["framebuffer_width"] = d.pop("fb_width")
    d["framebuffer_height"] = d.pop("fb_height")
    return d


@router.get("/frames/{frame_id}/overview")
def get_frame_overview(frame_id: int, request: Request) -> Dict[str, Any]:
    """Return an overview for the specified frame."""
    provider = request.app.state.provider
    overview = provider.get_frame_overview(frame_id)
    if overview is None:
        raise HTTPException(status_code=404, detail=f"Frame {frame_id} not found")
    d = asdict(overview)
    d["framebuffer_width"] = d.pop("fb_width")
    d["framebuffer_height"] = d.pop("fb_height")
    return d


@router.get("/frames/{frame_id}/framebuffer")
def get_framebuffer(frame_id: int, request: Request) -> Dict[str, Any]:
    """Return the colour buffer for a frame as base64-encoded raw RGBA bytes."""
    raise HTTPException(status_code=501, detail="Framebuffer readback not yet implemented")


@router.get("/frames/{frame_id}/framebuffer/depth")
def get_framebuffer_depth(frame_id: int, request: Request) -> Dict[str, Any]:
    """Return the depth buffer for a frame as base64-encoded raw float32 bytes."""
    raise HTTPException(status_code=501, detail="Framebuffer depth readback not yet implemented")
