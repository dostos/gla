"""REST endpoints for framework-level object queries."""
from __future__ import annotations

from dataclasses import asdict

from fastapi import APIRouter, HTTPException, Request

from gla.api.app import safe_json_response

router = APIRouter(tags=["objects"])


@router.get("/frames/{frame_id}/objects")
async def list_objects(frame_id: int, request: Request):
    fqe = request.app.state.framework_query_engine
    if not fqe:
        raise HTTPException(status_code=501, detail="Framework query engine not configured")
    objects = fqe.list_objects(frame_id)
    return safe_json_response({"frame_id": frame_id, "objects": [asdict(o) for o in objects]})


@router.get("/frames/{frame_id}/objects/at/{x}/{y}")
async def object_at_pixel(frame_id: int, x: int, y: int, request: Request):
    fqe = request.app.state.framework_query_engine
    if not fqe:
        raise HTTPException(status_code=501, detail="Framework query engine not configured")
    # For now, explain_pixel doesn't do draw call attribution
    explanation = fqe.explain_pixel(frame_id, x, y)
    if not explanation:
        raise HTTPException(status_code=404, detail="No pixel explanation available")
    return safe_json_response(asdict(explanation))


@router.get("/frames/{frame_id}/objects/{name}")
async def get_object(frame_id: int, name: str, request: Request):
    fqe = request.app.state.framework_query_engine
    if not fqe:
        raise HTTPException(status_code=501, detail="Framework query engine not configured")
    obj = fqe.query_object(frame_id, name)
    if not obj:
        raise HTTPException(status_code=404, detail=f"Object '{name}' not found")
    return safe_json_response(asdict(obj))
