"""RenderDoc capture backend — reads .rdc capture files.

Requires the ``renderdoc`` Python module (ships with RenderDoc installs).
If the module is not importable, the backend raises a clear error at init time.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from .base import (
    DrawCallInfo,
    FrameOverview,
    FrameProvider,
    PixelResult,
    SceneInfo,
)


class RenderDocBackend(FrameProvider):
    """Reads frame data from RenderDoc ``.rdc`` capture files.

    RenderDoc captures are typically single-frame, so ``frame_id`` 0 is
    used as the canonical frame ID.
    """

    FRAME_ID = 0  # RenderDoc captures are single-frame

    def __init__(self, capture_path: str):
        self._path = capture_path
        self._cap = None
        self._controller = None
        self._load()

    def _load(self):
        try:
            import renderdoc as rd  # type: ignore
        except ImportError:
            raise RuntimeError(
                "RenderDoc Python module not available. "
                "Install RenderDoc or use the native backend."
            )

        self._rd = rd
        self._cap = rd.OpenCaptureFile()
        status = self._cap.OpenFile(self._path, "", None)
        if status != rd.ResultCode.Succeeded:
            raise RuntimeError(f"Failed to open {self._path}: {status}")
        self._controller = self._cap.OpenCapture(rd.ReplayOptions(), None)

    def close(self):
        """Release the capture file and replay controller."""
        if self._controller is not None:
            self._controller.Shutdown()
            self._controller = None
        if self._cap is not None:
            self._cap.Shutdown()
            self._cap = None

    def __del__(self):
        self.close()

    # -- Capabilities -------------------------------------------------------

    @property
    def supports_live_control(self) -> bool:
        return False

    @property
    def backend_name(self) -> str:
        return "renderdoc"

    # -- Helpers -------------------------------------------------------------

    def _iter_draws(self, actions=None):
        """Yield all draw-call actions from the root action list."""
        if actions is None:
            actions = self._controller.GetRootActions()
        for action in actions:
            flags = action.flags
            if flags & self._rd.ActionFlags.Drawcall:
                yield action
            if action.children:
                yield from self._iter_draws(action.children)

    # -- FrameProvider implementation ----------------------------------------

    def get_latest_overview(self) -> Optional[FrameOverview]:
        return self.get_frame_overview(self.FRAME_ID)

    def get_frame_overview(self, frame_id: int) -> Optional[FrameOverview]:
        if frame_id != self.FRAME_ID:
            return None

        actions = list(self._iter_draws())
        draw_count = len(actions)

        # Try to determine framebuffer dimensions from output targets
        fb_width, fb_height = 0, 0
        try:
            textures = self._controller.GetTextures()
            for tex in textures:
                if tex.creationFlags & self._rd.TextureCategory.SwapBuffer:
                    fb_width = tex.width
                    fb_height = tex.height
                    break
        except Exception:
            pass

        return FrameOverview(
            frame_id=self.FRAME_ID,
            draw_call_count=draw_count,
            fb_width=fb_width,
            fb_height=fb_height,
            timestamp=0.0,
        )

    def list_draw_calls(self, frame_id: int, limit: int = 50, offset: int = 0) -> List[DrawCallInfo]:
        if frame_id != self.FRAME_ID:
            return []
        all_draws = list(self._iter_draws())
        page = all_draws[offset:offset + limit]
        return [self._action_to_drawcall(i + offset, a) for i, a in enumerate(page)]

    def _action_to_drawcall(self, idx: int, action) -> DrawCallInfo:
        return DrawCallInfo(
            id=idx,
            primitive_type=str(action.topology) if hasattr(action, "topology") else "UNKNOWN",
            vertex_count=action.numIndices if hasattr(action, "numIndices") else 0,
            index_count=action.numIndices if hasattr(action, "numIndices") else 0,
            instance_count=action.numInstances if hasattr(action, "numInstances") else 1,
            shader_id=0,
            pipeline_state={},
            params=[],
            textures=[],
        )

    def get_draw_call(self, frame_id: int, dc_id: int) -> Optional[DrawCallInfo]:
        if frame_id != self.FRAME_ID:
            return None
        all_draws = list(self._iter_draws())
        if dc_id < 0 or dc_id >= len(all_draws):
            return None
        return self._action_to_drawcall(dc_id, all_draws[dc_id])

    def get_pixel(self, frame_id: int, x: int, y: int) -> Optional[PixelResult]:
        if frame_id != self.FRAME_ID:
            return None
        # Pixel picking via RenderDoc replay is possible but complex;
        # return None for now — can be implemented with PickPixel later.
        return None

    def get_scene(self, frame_id: int) -> Optional[SceneInfo]:
        # Scene reconstruction from RenderDoc captures is not yet implemented.
        # Return a raw_only stub.
        if frame_id != self.FRAME_ID:
            return None
        return SceneInfo(
            camera=None,
            objects=[],
            reconstruction_quality="raw_only",
        )

    def compare_frames(self, frame_a: int, frame_b: int, depth: str = "summary") -> Optional[Any]:
        # RenderDoc captures are single-frame; cross-frame diff is not supported.
        return None
