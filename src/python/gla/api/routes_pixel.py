"""Per-pixel query endpoint."""
from typing import Any, Dict

from fastapi import APIRouter, HTTPException, Request

router = APIRouter(tags=["pixel"])


@router.get("/frames/{frame_id}/pixel/{x}/{y}")
def get_pixel(frame_id: int, x: int, y: int, request: Request) -> Dict[str, Any]:
    """Return colour, depth, and stencil values for a single pixel.

    Coordinates are in framebuffer space (origin top-left, x right, y down).
    Returns 404 if the frame does not exist or the coordinates are out of bounds.
    """
    provider = request.app.state.provider
    result = provider.get_pixel(frame_id, x, y)
    if result is None:
        raise HTTPException(
            status_code=404,
            detail=f"Pixel ({x}, {y}) not found in frame {frame_id} "
                   "(frame missing or coordinates out of bounds)",
        )
    return {
        "x": x,
        "y": y,
        "r": result.r,
        "g": result.g,
        "b": result.b,
        "a": result.a,
        "depth": result.depth,
        "stencil": result.stencil,
    }
