"""Frame overview endpoints."""
from dataclasses import asdict
from typing import Union

from fastapi import APIRouter, HTTPException, Request

from gpa.api.app import resolve_frame_id, safe_json_response

router = APIRouter(tags=["frames"])


@router.get("/frames/current/overview")
def get_current_frame_overview(request: Request):
    """Return an overview of the most recently captured frame."""
    provider = request.app.state.provider
    overview = provider.get_latest_overview()
    if overview is None:
        raise HTTPException(status_code=404, detail="No frame captured yet")
    d = asdict(overview)
    # Keep the JSON key names the routes have always used
    d["framebuffer_width"] = d.pop("fb_width")
    d["framebuffer_height"] = d.pop("fb_height")
    return safe_json_response(d)


@router.get("/frames/{frame_id}/overview")
def get_frame_overview(frame_id: Union[int, str], request: Request):
    """Return an overview for the specified frame."""
    provider = request.app.state.provider
    frame_id = resolve_frame_id(frame_id, provider)
    overview = provider.get_frame_overview(frame_id)
    if overview is None:
        raise HTTPException(status_code=404, detail=f"Frame {frame_id} not found")
    d = asdict(overview)
    d["framebuffer_width"] = d.pop("fb_width")
    d["framebuffer_height"] = d.pop("fb_height")
    return safe_json_response(d)
