"""Scene query endpoints: full scene, camera, and objects."""
from typing import Any, Dict

from fastapi import APIRouter, HTTPException, Request

router = APIRouter(tags=["scene"])


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _get_scene_or_404(request: Request, frame_id: int):
    """Run scene reconstruction via the provider and return SceneInfo, or raise 404."""
    provider = request.app.state.provider
    scene = provider.get_scene(frame_id)
    if scene is None:
        raise HTTPException(status_code=404, detail=f"Frame {frame_id} not found")
    return scene


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@router.get("/frames/{frame_id}/scene")
def get_scene(frame_id: int, request: Request) -> Dict[str, Any]:
    """Full scene reconstruction: camera + objects + quality."""
    scene = _get_scene_or_404(request, frame_id)
    return {
        "reconstruction_quality": scene.reconstruction_quality,
        "camera": scene.camera,
        "objects": scene.objects,
    }


@router.get("/frames/{frame_id}/scene/camera")
def get_camera(frame_id: int, request: Request) -> Dict[str, Any]:
    """Camera parameters for a frame."""
    scene = _get_scene_or_404(request, frame_id)
    if scene.camera is None:
        raise HTTPException(status_code=404, detail="Camera could not be extracted for this frame")
    return scene.camera


@router.get("/frames/{frame_id}/scene/objects")
def get_objects(frame_id: int, request: Request) -> Dict[str, Any]:
    """List scene objects with transforms and bounding boxes."""
    scene = _get_scene_or_404(request, frame_id)
    return {
        "objects": scene.objects,
        "reconstruction_quality": scene.reconstruction_quality,
    }
