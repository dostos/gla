"""Draw call list and detail endpoints."""
import math
from typing import Any, Dict, List, Union

from fastapi import APIRouter, HTTPException, Query, Request

from gpa.api.app import resolve_frame_id, safe_json_response

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


def _flatten_components(value: Any) -> List[Any]:
    """Flatten a decoded uniform value into a flat list of components.

    Handles scalars, flat lists (vec*), and nested lists (row-wise matrices).
    Returns ``[value]`` for scalars.
    """
    if isinstance(value, (list, tuple)):
        out: List[Any] = []
        for v in value:
            if isinstance(v, (list, tuple)):
                out.extend(_flatten_components(v))
            else:
                out.append(v)
        return out
    return [value]


def _find_nan_uniforms(params: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Scan decoded uniform params for NaN / Inf components.

    Returns ``[{name, type, bad_components}, ...]``. Empty list means all
    decoded uniforms are finite. Params without a decoded ``value`` (raw
    bytes only) are skipped.
    """
    offenders: List[Dict[str, Any]] = []
    for p in params or []:
        if "value" not in p:
            continue
        components = _flatten_components(p["value"])
        bad: List[int] = []
        for idx, comp in enumerate(components):
            if not isinstance(comp, (int, float)):
                continue
            try:
                if math.isnan(comp) or math.isinf(comp):
                    bad.append(idx)
            except (TypeError, ValueError):
                continue
        if bad:
            offenders.append({
                "name": p.get("name"),
                "type": p.get("type"),
                "bad_components": bad,
            })
    return offenders


def _sanitize_json_floats(obj):
    """Replace NaN / Inf floats with string sentinels so strict JSON
    encoders (Starlette) accept the payload. NaN / Inf in decoded uniforms
    is legitimate signal — preserve it as ``"NaN"`` / ``"Infinity"`` /
    ``"-Infinity"``.
    """
    if isinstance(obj, float):
        if math.isnan(obj):
            return "NaN"
        if math.isinf(obj):
            return "Infinity" if obj > 0 else "-Infinity"
        return obj
    if isinstance(obj, list):
        return [_sanitize_json_floats(v) for v in obj]
    if isinstance(obj, tuple):
        return tuple(_sanitize_json_floats(v) for v in obj)
    if isinstance(obj, dict):
        return {k: _sanitize_json_floats(v) for k, v in obj.items()}
    return obj


def _drawcall_detail(dc) -> Dict[str, Any]:
    """Full detail for a single draw call."""
    result = _drawcall_summary(dc)
    pipeline_state = dict(dc.pipeline_state) if dc.pipeline_state else {}
    pipeline_state["fbo_color_attachment_tex"] = getattr(dc, "fbo_color_attachment_tex", 0)
    nan_uniforms = _find_nan_uniforms(getattr(dc, "params", []) or [])
    result.update(
        {
            "index_count": dc.index_count,
            "index_type": getattr(dc, "index_type", 0) or 0,
            "pipeline_state": pipeline_state,
            "has_nan_uniforms": bool(nan_uniforms),
            "nan_uniforms": nan_uniforms,
        }
    )
    return result


def _enrich_textures(dc) -> list:
    """Add a derived `collides_with_fbo_attachment` flag to each bound texture.

    A collision means the same texture object is simultaneously the current
    FBO's color attachment and a bound sampler — the classic feedback-loop
    signature. Surfacing it inline saves the agent from manually
    cross-referencing two fields.
    """
    fbo_tex = getattr(dc, "fbo_color_attachment_tex", 0) or 0
    enriched = []
    for t in dc.textures or []:
        entry = dict(t)
        entry["collides_with_fbo_attachment"] = bool(
            fbo_tex and entry.get("texture_id") == fbo_tex
        )
        enriched.append(entry)
    return enriched


@router.get("/frames/{frame_id}/drawcalls")
def list_drawcalls(
    frame_id: Union[int, str],
    request: Request,
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
):
    """Return a paginated list of draw calls for a frame."""
    provider = request.app.state.provider
    frame_id = resolve_frame_id(frame_id, provider)
    overview = provider.get_frame_overview(frame_id)
    if overview is None:
        raise HTTPException(status_code=404, detail=f"Frame {frame_id} not found")
    drawcalls = provider.list_draw_calls(frame_id, limit, offset)
    total = overview.draw_call_count
    return safe_json_response({
        "frame_id": frame_id,
        "offset": offset,
        "limit": limit,
        "total": total,
        "items": [_drawcall_summary(dc) for dc in drawcalls],
    })


@router.get("/frames/{frame_id}/drawcalls/{dc_id}")
def get_drawcall(frame_id: Union[int, str], dc_id: int, request: Request):
    """Return full details for a single draw call."""
    provider = request.app.state.provider
    frame_id = resolve_frame_id(frame_id, provider)
    dc = provider.get_draw_call(frame_id, dc_id)
    if dc is None:
        raise HTTPException(
            status_code=404, detail=f"Draw call {dc_id} in frame {frame_id} not found"
        )
    return safe_json_response(_drawcall_detail(dc))


@router.get("/frames/{frame_id}/drawcalls/{dc_id}/shader")
def get_drawcall_shader(
    frame_id: Union[int, str], dc_id: int, request: Request
):
    """Return shader program info and uniform parameters for a draw call."""
    provider = request.app.state.provider
    frame_id = resolve_frame_id(frame_id, provider)
    dc = provider.get_draw_call(frame_id, dc_id)
    if dc is None:
        raise HTTPException(
            status_code=404, detail=f"Draw call {dc_id} in frame {frame_id} not found"
        )
    return safe_json_response({
        "frame_id": frame_id,
        "dc_id": dc_id,
        "shader_id": dc.shader_id,
        "parameters": _sanitize_json_floats(dc.params),
    })


@router.get("/frames/{frame_id}/drawcalls/{dc_id}/nan-uniforms")
def get_drawcall_nan_uniforms(
    frame_id: Union[int, str], dc_id: int, request: Request
):
    """Return the uniforms whose decoded value contains NaN or Inf.

    One-shot query for "is any input uniform NaN-tainted?" — agents
    should hit this before hypothesizing local shader math bugs.
    """
    provider = request.app.state.provider
    frame_id = resolve_frame_id(frame_id, provider)
    dc = provider.get_draw_call(frame_id, dc_id)
    if dc is None:
        raise HTTPException(
            status_code=404, detail=f"Draw call {dc_id} in frame {frame_id} not found"
        )
    nan_uniforms = _find_nan_uniforms(getattr(dc, "params", []) or [])
    return safe_json_response({
        "frame_id": frame_id,
        "dc_id": dc_id,
        "has_nan_uniforms": bool(nan_uniforms),
        "nan_uniforms": nan_uniforms,
    })


@router.get("/frames/{frame_id}/drawcalls/{dc_id}/textures")
def get_drawcall_textures(
    frame_id: Union[int, str], dc_id: int, request: Request
):
    """Return bound texture units for a draw call."""
    provider = request.app.state.provider
    frame_id = resolve_frame_id(frame_id, provider)
    dc = provider.get_draw_call(frame_id, dc_id)
    if dc is None:
        raise HTTPException(
            status_code=404, detail=f"Draw call {dc_id} in frame {frame_id} not found"
        )
    return safe_json_response({
        "frame_id": frame_id,
        "dc_id": dc_id,
        "textures": _enrich_textures(dc),
    })


@router.get("/frames/{frame_id}/drawcalls/{dc_id}/feedback-loops")
def get_drawcall_feedback_loops(
    frame_id: Union[int, str], dc_id: int, request: Request
):
    """Return any bound textures that are also the current FBO's color attachment.

    Empty `textures` list = no feedback loop. Non-empty = classic
    "sample-from-render-target" bug (e.g. transmission/refraction passes
    in three.js). One-shot query so agents don't have to cross-reference
    two fields on the detail endpoint.
    """
    provider = request.app.state.provider
    frame_id = resolve_frame_id(frame_id, provider)
    dc = provider.get_draw_call(frame_id, dc_id)
    if dc is None:
        raise HTTPException(
            status_code=404, detail=f"Draw call {dc_id} in frame {frame_id} not found"
        )
    fbo_tex = getattr(dc, "fbo_color_attachment_tex", 0) or 0
    offenders = [
        dict(t) for t in (dc.textures or [])
        if fbo_tex and t.get("texture_id") == fbo_tex
    ]
    return safe_json_response({
        "frame_id": frame_id,
        "dc_id": dc_id,
        "fbo_color_attachment_tex": fbo_tex,
        "textures": offenders,
    })


@router.get("/frames/{frame_id}/drawcalls/{dc_id}/vertices")
def get_drawcall_vertices(
    frame_id: Union[int, str], dc_id: int, request: Request
):
    """Return vertex buffer info and attribute layout for a draw call."""
    provider = request.app.state.provider
    frame_id = resolve_frame_id(frame_id, provider)
    dc = provider.get_draw_call(frame_id, dc_id)
    if dc is None:
        raise HTTPException(
            status_code=404, detail=f"Draw call {dc_id} in frame {frame_id} not found"
        )
    return safe_json_response({
        "frame_id": frame_id,
        "dc_id": dc_id,
        "vertex_count": dc.vertex_count,
        "index_count": dc.index_count,
        "index_type": getattr(dc, "index_type", 0) or 0,
        "primitive_type": dc.primitive_type,
    })


@router.get("/frames/{frame_id}/drawcalls/{dc_id}/attachments")
def get_drawcall_attachments(
    frame_id: Union[int, str], dc_id: int, request: Request
):
    """Return the full MRT color-attachment table for a draw call.

    Exposes GL_COLOR_ATTACHMENT0..7 as an 8-element list plus a convenience
    count of non-zero entries.  Diagnoses silent MRT misconfigurations where
    the shader writes to ``out`` locations the FBO does not bind (three.js
    custom-points r32).
    """
    provider = request.app.state.provider
    frame_id = resolve_frame_id(frame_id, provider)
    dc = provider.get_draw_call(frame_id, dc_id)
    if dc is None:
        raise HTTPException(
            status_code=404, detail=f"Draw call {dc_id} in frame {frame_id} not found"
        )
    attachments = list(getattr(dc, "fbo_color_attachments", []) or [])
    # Pad/truncate to exactly 8 for a stable shape.
    if len(attachments) < 8:
        attachments = attachments + [0] * (8 - len(attachments))
    elif len(attachments) > 8:
        attachments = attachments[:8]
    active = sum(1 for a in attachments if a)
    return safe_json_response({
        "frame_id": frame_id,
        "dc_id": dc_id,
        "fbo_color_attachments": attachments,
        "active_attachment_count": active,
    })
