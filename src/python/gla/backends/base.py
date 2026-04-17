"""FrameProvider ABC and shared data classes.

These are pure-Python dataclasses — they are NOT pybind11 types.
Backend adapters convert from their native representations into these types.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


# ---------------------------------------------------------------------------
# Data classes returned by every backend
# ---------------------------------------------------------------------------

@dataclass
class FrameOverview:
    frame_id: int
    draw_call_count: int
    fb_width: int
    fb_height: int
    timestamp: float


@dataclass
class PixelResult:
    r: int
    g: int
    b: int
    a: int
    depth: float
    stencil: int


@dataclass
class DrawCallInfo:
    id: int
    primitive_type: Any  # str or int depending on backend
    vertex_count: int
    index_count: int
    instance_count: int
    shader_id: int
    pipeline_state: Dict[str, Any] = field(default_factory=dict)
    params: List[Dict[str, Any]] = field(default_factory=list)
    textures: List[Dict[str, Any]] = field(default_factory=list)


@dataclass
class SceneInfo:
    camera: Optional[Dict[str, Any]]  # serialisable dict or None
    objects: List[Dict[str, Any]]
    reconstruction_quality: str  # "full", "partial", "raw_only"


# ---------------------------------------------------------------------------
# Abstract base
# ---------------------------------------------------------------------------

class FrameProvider(ABC):
    """Abstract interface for frame data providers.

    All capture backends implement this interface.  The REST API, MCP server,
    and eval harness work through this interface only.
    """

    # -- Frame overview -----------------------------------------------------

    @abstractmethod
    def get_latest_overview(self) -> Optional[FrameOverview]:
        """Get overview of the most recent frame."""
        ...

    @abstractmethod
    def get_frame_overview(self, frame_id: int) -> Optional[FrameOverview]:
        """Get overview of a specific frame."""
        ...

    # -- Draw calls ---------------------------------------------------------

    @abstractmethod
    def list_draw_calls(self, frame_id: int, limit: int = 50, offset: int = 0) -> List[DrawCallInfo]:
        """List draw calls in a frame (paginated)."""
        ...

    @abstractmethod
    def get_draw_call(self, frame_id: int, dc_id: int) -> Optional[DrawCallInfo]:
        """Get detailed info for a specific draw call."""
        ...

    # -- Pixel query --------------------------------------------------------

    @abstractmethod
    def get_pixel(self, frame_id: int, x: int, y: int) -> Optional[PixelResult]:
        """Get colour/depth/stencil at a pixel coordinate."""
        ...

    # -- Scene reconstruction -----------------------------------------------

    @abstractmethod
    def get_scene(self, frame_id: int) -> Optional[SceneInfo]:
        """Get semantic scene reconstruction."""
        ...

    # -- Frame diff ---------------------------------------------------------

    @abstractmethod
    def compare_frames(self, frame_a: int, frame_b: int, depth: str = "summary") -> Optional[Any]:
        """Compare two frames.  Returns backend-specific diff object."""
        ...

    # -- Control (live backends only) ----------------------------------------

    def pause(self) -> Dict[str, Any]:
        """Pause capture.  No-op for non-live backends."""
        return {"state": "not_supported", "detail": "This backend does not support live control"}

    def resume(self) -> Dict[str, Any]:
        return {"state": "not_supported", "detail": "This backend does not support live control"}

    def step(self, count: int = 1) -> Dict[str, Any]:
        return {"state": "not_supported", "detail": "This backend does not support live control"}

    def status(self) -> Dict[str, Any]:
        return {"state": "capture_mode", "is_running": True}

    # -- Capabilities -------------------------------------------------------

    @property
    def supports_live_control(self) -> bool:
        return False

    @property
    def backend_name(self) -> str:
        return "unknown"
