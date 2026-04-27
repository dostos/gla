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
    clear_count: int
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
    fbo_color_attachment_tex: int = 0
    # Full MRT attachment table (GL_COLOR_ATTACHMENT0..7); entry i == 0 means
    # the slot is unbound. Non-MRT draws have entries 1..7 = 0.
    fbo_color_attachments: List[int] = field(default_factory=lambda: [0] * 8)
    index_type: int = 0
    # Path of GL_KHR_debug push groups active at draw time, outermost first.
    # Names are preserved verbatim (so node names containing '/' are safe).
    debug_groups: List[str] = field(default_factory=list)


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

    # -- Frame enumeration --------------------------------------------------

    def list_frame_ids(self) -> List[int]:
        """Return every frame id currently retrievable on this backend.

        Default behaviour: probe backwards from the latest frame id until a
        ``get_frame_overview()`` miss, capped at 4096 frames so a runaway
        scan can't pin the engine.  Backends that can answer this directly
        (``NativeBackend`` does, via the engine's ring buffer) should
        override.
        """
        latest = self.get_latest_overview()
        if latest is None:
            return []
        ids: List[int] = []
        # Cap probing at 4096 frames — protects pathological cases where
        # a backend lies about ``latest`` without bounding the history.
        max_probe = 4096
        for fid in range(int(latest.frame_id), -1, -1):
            if len(ids) >= max_probe:
                break
            if self.get_frame_overview(fid) is None:
                break
            ids.append(fid)
        ids.sort()
        return ids

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
