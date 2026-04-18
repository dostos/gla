"""Scene query endpoints: full scene, camera, and objects.

Scene-level data (camera, objects) requires Tier 3 framework metadata
supplied via POST /frames/{id}/metadata or a framework plugin.
Tier 1 raw capture (GL/Vulkan calls) is intentionally not interpreted
as scene semantics.
"""
from fastapi import APIRouter, HTTPException, Request

from gla.api.app import safe_json_response

router = APIRouter(tags=["scene"])

_NO_FRAMEWORK_METADATA = (
    "No framework metadata available. "
    "POST to /frames/{id}/metadata or use a framework plugin."
)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _get_framework_query_engine(request: Request):
    """Return the FrameworkQueryEngine if present on app state, else None."""
    return getattr(request.app.state, "framework_query_engine", None)


def _get_scene_from_tier3(fqe, frame_id: int):
    """Ask the FrameworkQueryEngine for scene data; raise 404 when unavailable."""
    if fqe is None:
        raise HTTPException(status_code=404, detail=_NO_FRAMEWORK_METADATA)
    scene = fqe.get_scene(frame_id) if hasattr(fqe, "get_scene") else None
    if scene is None:
        raise HTTPException(status_code=404, detail=_NO_FRAMEWORK_METADATA)
    return scene


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@router.get("/frames/{frame_id}/scene")
def get_scene(frame_id: int, request: Request):
    """Full scene data from Tier 3 framework metadata."""
    fqe = _get_framework_query_engine(request)
    scene = _get_scene_from_tier3(fqe, frame_id)
    return safe_json_response({
        "camera": scene.camera,
        "objects": scene.objects,
    })


@router.get("/frames/{frame_id}/scene/camera")
def get_camera(frame_id: int, request: Request):
    """Camera parameters from Tier 3 framework metadata."""
    fqe = _get_framework_query_engine(request)
    scene = _get_scene_from_tier3(fqe, frame_id)
    if scene.camera is None:
        raise HTTPException(status_code=404, detail=_NO_FRAMEWORK_METADATA)
    return safe_json_response(scene.camera)


@router.get("/frames/{frame_id}/scene/objects")
def get_objects(frame_id: int, request: Request):
    """Scene objects from Tier 3 framework metadata."""
    fqe = _get_framework_query_engine(request)
    scene = _get_scene_from_tier3(fqe, frame_id)
    return safe_json_response({"objects": scene.objects})
