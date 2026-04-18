"""Capture backend abstraction for OpenGPA.

All capture backends implement :class:`FrameProvider`.  The REST API,
MCP server, and eval harness work through this interface only.
"""

from .base import (
    DrawCallInfo,
    FrameOverview,
    FrameProvider,
    PixelResult,
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
]
