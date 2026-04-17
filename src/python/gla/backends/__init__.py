"""Capture backend abstraction for GLA.

All capture backends implement :class:`FrameProvider`.  The REST API,
MCP server, and eval harness work through this interface only.
"""

from .base import (
    DrawCallInfo,
    FrameOverview,
    FrameProvider,
    PixelResult,
    SceneInfo,
)
from .native import NativeBackend
from .renderdoc import RenderDocBackend

__all__ = [
    "DrawCallInfo",
    "FrameOverview",
    "FrameProvider",
    "NativeBackend",
    "PixelResult",
    "RenderDocBackend",
    "SceneInfo",
]
