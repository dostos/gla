"""Frame diff (comparison) endpoint.

GET /api/v1/diff/{frame_a}/{frame_b}?depth=summary|drawcalls|pixels
"""
from typing import Any, Dict, List

from fastapi import APIRouter, HTTPException, Query, Request

router = APIRouter(tags=["diff"])

_VALID_DEPTHS = {"summary", "drawcalls", "pixels"}


def _draw_call_diff_to_dict(d) -> Dict[str, Any]:
    return {
        "dc_id": d.dc_id,
        "added": d.added,
        "removed": d.removed,
        "modified": d.modified,
        "shader_changed": d.shader_changed,
        "params_changed": d.params_changed,
        "pipeline_changed": d.pipeline_changed,
        "textures_changed": d.textures_changed,
        "changed_param_names": list(d.changed_param_names),
    }


def _pixel_diff_to_dict(p) -> Dict[str, Any]:
    return {
        "x": p.x,
        "y": p.y,
        "a": [p.a_r, p.a_g, p.a_b, p.a_a],
        "b": [p.b_r, p.b_g, p.b_b, p.b_a],
    }


@router.get("/diff/{frame_a}/{frame_b}")
def compare_frames(
    frame_a: int,
    frame_b: int,
    request: Request,
    depth: str = Query(default="summary"),
) -> Dict[str, Any]:
    """Compare two captured frames.

    Returns a diff at the requested depth:
    - ``summary``   – counts only
    - ``drawcalls`` – per-draw-call breakdown
    - ``pixels``    – pixel-level diff (first 100 differing pixels)
    """
    if depth not in _VALID_DEPTHS:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid depth '{depth}'. Must be one of: {sorted(_VALID_DEPTHS)}",
        )

    provider = request.app.state.provider
    result = provider.compare_frames(frame_a, frame_b, depth)
    if result is None:
        raise HTTPException(
            status_code=404,
            detail=f"One or both frames not found: {frame_a}, {frame_b}",
        )

    draw_call_diffs: List[Dict[str, Any]] = [
        _draw_call_diff_to_dict(d) for d in result.draw_call_diffs
    ]
    pixel_diffs: List[Dict[str, Any]] = [
        _pixel_diff_to_dict(p) for p in result.pixel_diffs
    ]

    return {
        "frame_id_a": result.frame_id_a,
        "frame_id_b": result.frame_id_b,
        "summary": {
            "draw_calls_added": result.draw_calls_added,
            "draw_calls_removed": result.draw_calls_removed,
            "draw_calls_modified": result.draw_calls_modified,
            "draw_calls_unchanged": result.draw_calls_unchanged,
            "pixels_changed": result.pixels_changed,
        },
        "draw_call_diffs": draw_call_diffs,
        "pixel_diffs": pixel_diffs,
    }
