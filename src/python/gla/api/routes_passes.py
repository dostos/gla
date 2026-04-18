"""REST endpoints for render pass queries."""
from __future__ import annotations

from dataclasses import asdict

from fastapi import APIRouter, HTTPException, Request

from gla.api.app import safe_json_response

router = APIRouter(tags=["passes"])


@router.get("/frames/{frame_id}/passes")
async def list_passes(frame_id: int, request: Request):
    fqe = request.app.state.framework_query_engine
    if not fqe:
        raise HTTPException(status_code=501, detail="Framework query engine not configured")
    passes = fqe.list_render_passes(frame_id)
    return safe_json_response({"frame_id": frame_id, "passes": [asdict(p) for p in passes]})


@router.get("/frames/{frame_id}/passes/{name}")
async def get_pass(frame_id: int, name: str, request: Request):
    fqe = request.app.state.framework_query_engine
    if not fqe:
        raise HTTPException(status_code=501, detail="Framework query engine not configured")
    passes = fqe.list_render_passes(frame_id)
    found = next((p for p in passes if p.name == name), None)
    if not found:
        raise HTTPException(status_code=404, detail=f"Render pass '{name}' not found")
    return safe_json_response(asdict(found))
