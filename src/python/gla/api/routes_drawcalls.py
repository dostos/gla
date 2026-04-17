"""Draw call list and detail endpoints."""
from typing import Any, Dict, List

from fastapi import APIRouter, HTTPException, Query, Request

router = APIRouter(tags=["drawcalls"])


def _drawcall_summary(dc) -> Dict[str, Any]:
    """Minimal summary suitable for a list item."""
    return {
        "id": dc.id,
        "primitive_type": dc.primitive_type,
        "vertex_count": dc.vertex_count,
        "instance_count": dc.instance_count,
        "shader_id": dc.shader_id,
    }


def _drawcall_detail(dc) -> Dict[str, Any]:
    """Full detail for a single draw call."""
    result = _drawcall_summary(dc)
    result.update(
        {
            "index_count": dc.index_count,
            "pipeline_state": dc.pipeline_state,
        }
    )
    return result


@router.get("/frames/{frame_id}/drawcalls")
def list_drawcalls(
    frame_id: int,
    request: Request,
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
) -> Dict[str, Any]:
    """Return a paginated list of draw calls for a frame."""
    provider = request.app.state.provider
    overview = provider.get_frame_overview(frame_id)
    if overview is None:
        raise HTTPException(status_code=404, detail=f"Frame {frame_id} not found")
    drawcalls = provider.list_draw_calls(frame_id, limit, offset)
    total = overview.draw_call_count
    return {
        "frame_id": frame_id,
        "offset": offset,
        "limit": limit,
        "total": total,
        "items": [_drawcall_summary(dc) for dc in drawcalls],
    }


@router.get("/frames/{frame_id}/drawcalls/{dc_id}")
def get_drawcall(frame_id: int, dc_id: int, request: Request) -> Dict[str, Any]:
    """Return full details for a single draw call."""
    provider = request.app.state.provider
    dc = provider.get_draw_call(frame_id, dc_id)
    if dc is None:
        raise HTTPException(
            status_code=404, detail=f"Draw call {dc_id} in frame {frame_id} not found"
        )
    return _drawcall_detail(dc)


@router.get("/frames/{frame_id}/drawcalls/{dc_id}/shader")
def get_drawcall_shader(
    frame_id: int, dc_id: int, request: Request
) -> Dict[str, Any]:
    """Return shader program info and uniform parameters for a draw call."""
    provider = request.app.state.provider
    dc = provider.get_draw_call(frame_id, dc_id)
    if dc is None:
        raise HTTPException(
            status_code=404, detail=f"Draw call {dc_id} in frame {frame_id} not found"
        )
    return {
        "frame_id": frame_id,
        "dc_id": dc_id,
        "shader_id": dc.shader_id,
        "parameters": dc.params,
    }


@router.get("/frames/{frame_id}/drawcalls/{dc_id}/textures")
def get_drawcall_textures(
    frame_id: int, dc_id: int, request: Request
) -> Dict[str, Any]:
    """Return bound texture units for a draw call."""
    provider = request.app.state.provider
    dc = provider.get_draw_call(frame_id, dc_id)
    if dc is None:
        raise HTTPException(
            status_code=404, detail=f"Draw call {dc_id} in frame {frame_id} not found"
        )
    return {
        "frame_id": frame_id,
        "dc_id": dc_id,
        "textures": dc.textures,
    }


@router.get("/frames/{frame_id}/drawcalls/{dc_id}/vertices")
def get_drawcall_vertices(
    frame_id: int, dc_id: int, request: Request
) -> Dict[str, Any]:
    """Return vertex buffer info and attribute layout for a draw call."""
    provider = request.app.state.provider
    dc = provider.get_draw_call(frame_id, dc_id)
    if dc is None:
        raise HTTPException(
            status_code=404, detail=f"Draw call {dc_id} in frame {frame_id} not found"
        )
    return {
        "frame_id": frame_id,
        "dc_id": dc_id,
        "vertex_count": dc.vertex_count,
        "index_count": dc.index_count,
        "primitive_type": dc.primitive_type,
    }
