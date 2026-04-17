"""Capture engine control endpoints (pause / resume / step / status)."""
from typing import Any, Dict

from fastapi import APIRouter, HTTPException, Query, Request

router = APIRouter(tags=["control"])


def _provider_or_503(request: Request):
    provider = request.app.state.provider
    if not provider.supports_live_control:
        raise HTTPException(status_code=503, detail="Engine not attached")
    return provider


@router.post("/control/pause")
def pause_engine(request: Request) -> Dict[str, Any]:
    """Pause frame capture."""
    provider = _provider_or_503(request)
    return provider.pause()


@router.post("/control/resume")
def resume_engine(request: Request) -> Dict[str, Any]:
    """Resume frame capture."""
    provider = _provider_or_503(request)
    return provider.resume()


@router.post("/control/step")
def step_engine(
    request: Request,
    count: int = Query(1, ge=1, description="Number of frames to advance"),
) -> Dict[str, Any]:
    """Advance capture by *count* frames (only valid while paused)."""
    provider = _provider_or_503(request)
    return provider.step(count)


@router.get("/control/status")
def get_status(request: Request) -> Dict[str, Any]:
    """Return the current engine running state."""
    provider = _provider_or_503(request)
    return provider.status()
