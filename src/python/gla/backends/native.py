"""Native capture backend — wraps the existing C++ engine via pybind11.

Converts C++ pybind11 objects returned by ``QueryEngine`` into the pure-Python
dataclasses defined in :mod:`gla.backends.base`.
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


class NativeBackend(FrameProvider):
    """Live capture via LD_PRELOAD shim + C++ engine."""

    def __init__(self, query_engine, scene_reconstructor=None, engine=None):
        self._qe = query_engine
        self._scene = scene_reconstructor
        self._engine = engine

    # -- Capabilities -------------------------------------------------------

    @property
    def supports_live_control(self) -> bool:
        return self._engine is not None

    @property
    def backend_name(self) -> str:
        return "native"

    # -- Helpers to convert C++ types to Python dataclasses ------------------

    @staticmethod
    def _convert_overview(ov) -> FrameOverview:
        return FrameOverview(
            frame_id=ov.frame_id,
            draw_call_count=ov.draw_call_count,
            fb_width=ov.fb_width,
            fb_height=ov.fb_height,
            timestamp=ov.timestamp,
        )

    @staticmethod
    def _convert_pipeline(ps) -> Dict[str, Any]:
        viewport = ps.viewport
        scissor = ps.scissor
        return {
            "viewport_x": viewport[0],
            "viewport_y": viewport[1],
            "viewport_w": viewport[2],
            "viewport_h": viewport[3],
            "scissor_enabled": ps.scissor_enabled,
            "scissor_x": scissor[0],
            "scissor_y": scissor[1],
            "scissor_w": scissor[2],
            "scissor_h": scissor[3],
            "blend_enabled": ps.blend_enabled,
            "blend_src": ps.blend_src,
            "blend_dst": ps.blend_dst,
            "depth_test_enabled": ps.depth_test,
            "depth_write_enabled": ps.depth_write,
            "depth_func": ps.depth_func,
            "cull_enabled": ps.cull_enabled,
            "cull_mode": ps.cull_mode,
            "front_face": ps.front_face,
        }

    @staticmethod
    def _convert_drawcall(dc) -> DrawCallInfo:
        params = []
        for p in (dc.params or []):
            params.append({"name": p.name, "type": p.type, "data": p.data})

        textures = []
        for t in (dc.textures or []):
            textures.append({
                "slot": t.slot,
                "texture_id": t.texture_id,
                "width": t.width,
                "height": t.height,
                "format": t.format,
            })

        return DrawCallInfo(
            id=dc.id,
            primitive_type=dc.primitive_type,
            vertex_count=dc.vertex_count,
            index_count=dc.index_count,
            instance_count=dc.instance_count,
            shader_id=dc.shader_id,
            pipeline_state=NativeBackend._convert_pipeline(dc.pipeline),
            params=params,
            textures=textures,
        )

    @staticmethod
    def _convert_camera(cam) -> Dict[str, Any]:
        pos = list(cam.position)
        fwd = list(cam.forward)
        up = list(cam.up)
        cam_type = "perspective" if cam.is_perspective else "orthographic"
        summary = (
            f"{cam_type.capitalize()} camera at "
            f"({pos[0]:.1f}, {pos[1]:.1f}, {pos[2]:.1f}) looking toward "
            f"({fwd[0]:.3f}, {fwd[1]:.3f}, {fwd[2]:.3f}), "
            f"FOV {cam.fov_y_degrees:.1f} deg"
        )
        return {
            "summary": summary,
            "position": pos,
            "forward": fwd,
            "up": up,
            "fov_y_degrees": cam.fov_y_degrees,
            "aspect_ratio": cam.aspect,
            "near": cam.near_plane,
            "far": cam.far_plane,
            "type": cam_type,
            "confidence": cam.confidence,
        }

    @staticmethod
    def _convert_object(obj) -> Dict[str, Any]:
        return {
            "id": obj.id,
            "draw_call_ids": list(obj.draw_call_ids),
            "world_transform": list(obj.world_transform),
            "bounding_box": {
                "min": list(obj.bbox_min),
                "max": list(obj.bbox_max),
            },
            "visible": obj.visible,
            "confidence": obj.confidence,
        }

    # -- FrameProvider implementation ----------------------------------------

    def get_latest_overview(self) -> Optional[FrameOverview]:
        ov = self._qe.latest_frame_overview()
        if ov is None:
            return None
        return self._convert_overview(ov)

    def get_frame_overview(self, frame_id: int) -> Optional[FrameOverview]:
        ov = self._qe.frame_overview(frame_id)
        if ov is None:
            return None
        return self._convert_overview(ov)

    def list_draw_calls(self, frame_id: int, limit: int = 50, offset: int = 0) -> List[DrawCallInfo]:
        raw = self._qe.list_draw_calls(frame_id, limit, offset)
        return [self._convert_drawcall(dc) for dc in raw]

    def get_draw_call(self, frame_id: int, dc_id: int) -> Optional[DrawCallInfo]:
        dc = self._qe.get_draw_call(frame_id, dc_id)
        if dc is None:
            return None
        return self._convert_drawcall(dc)

    def get_pixel(self, frame_id: int, x: int, y: int) -> Optional[PixelResult]:
        result = self._qe.get_pixel(frame_id, x, y)
        if result is None:
            return None
        return PixelResult(
            r=result.r, g=result.g, b=result.b, a=result.a,
            depth=result.depth, stencil=result.stencil,
        )

    def get_scene(self, frame_id: int) -> Optional[SceneInfo]:
        if self._scene is None:
            return None

        overview = self._qe.frame_overview(frame_id)
        if overview is None:
            return None

        frame = self._qe.get_normalized_frame(frame_id)
        if frame is None:
            return None

        scene = self._scene.reconstruct(frame)
        camera = self._convert_camera(scene.camera) if scene.camera else None
        objects = [self._convert_object(o) for o in scene.objects]

        return SceneInfo(
            camera=camera,
            objects=objects,
            reconstruction_quality=scene.reconstruction_quality,
        )

    def compare_frames(self, frame_a: int, frame_b: int, depth: str = "summary") -> Optional[Any]:
        return self._qe.compare_frames(frame_a, frame_b, depth)

    # -- Control -------------------------------------------------------------

    def pause(self) -> Dict[str, Any]:
        if self._engine is None:
            return super().pause()
        self._engine.pause()
        return {"status": "paused"}

    def resume(self) -> Dict[str, Any]:
        if self._engine is None:
            return super().resume()
        self._engine.resume()
        return {"status": "running"}

    def step(self, count: int = 1) -> Dict[str, Any]:
        if self._engine is None:
            return super().step(count)
        self._engine.step(count)
        return {"status": "stepped", "count": count}

    def status(self) -> Dict[str, Any]:
        if self._engine is None:
            return super().status()
        is_running = self._engine.is_running()
        return {
            "state": "running" if is_running else "paused",
            "is_running": is_running,
        }
