"""RenderDoc capture backend — reads .rdc capture files.

Requires the ``renderdoc`` Python module (ships with RenderDoc installs).
If the module is not importable, the backend raises a clear error at init time.

Installation
------------
1. Install RenderDoc >= 1.x from https://renderdoc.org/
2. Locate the Python module directory — typically one of:

   * Linux:  ``/usr/lib/renderdoc/`` or alongside the ``qrenderdoc`` binary
   * macOS:  ``/Applications/RenderDoc.app/Contents/Resources/``
   * Windows: ``C:\\Program Files\\RenderDoc\\``

3. Add that directory to ``PYTHONPATH`` before running GLA, e.g.::

       export PYTHONPATH=/usr/lib/renderdoc:$PYTHONPATH
       python -m gla.server --backend renderdoc --path capture.rdc

Usage
-----
::

    from gla.backends.renderdoc import RenderDocBackend

    backend = RenderDocBackend("path/to/capture.rdc")
    overview = backend.get_latest_overview()
    draws = backend.list_draw_calls(0)
    pixel = backend.get_pixel(0, 320, 240)
    backend.close()
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from .base import (
    DrawCallInfo,
    FrameOverview,
    FrameProvider,
    PixelResult,
)


class RenderDocBackend(FrameProvider):
    """Reads frame data from RenderDoc ``.rdc`` capture files.

    RenderDoc captures are typically single-frame, so ``frame_id`` 0 is
    used as the canonical frame ID.
    """

    FRAME_ID = 0  # RenderDoc captures are single-frame

    def __init__(self, capture_path: str):
        try:
            import renderdoc as rd  # type: ignore
            self._rd = rd
        except ImportError:
            raise RuntimeError(
                "RenderDoc Python module not available. "
                "Install RenderDoc (https://renderdoc.org/) and ensure "
                "the Python module is on your PYTHONPATH."
            )

        self._path = capture_path
        self._cap = None
        self._controller = None
        self._load()

    def _load(self):
        """Load and parse the .rdc capture file, building the replay controller."""
        rd = self._rd

        self._cap = rd.OpenCaptureFile()
        result = self._cap.OpenFile(self._path, "", None)
        if result != rd.ResultCode.Succeeded:
            raise RuntimeError(f"Failed to open {self._path}: {result}")

        if not self._cap.LocalReplaySupport():
            raise RuntimeError("Local replay not supported for this capture")

        status, self._controller = self._cap.OpenCapture(rd.ReplayOptions(), None)
        if status != rd.ResultCode.Succeeded:
            raise RuntimeError(f"Failed to open replay controller: {status}")

    def close(self):
        """Release the capture file and replay controller."""
        controller = getattr(self, "_controller", None)
        if controller is not None:
            controller.Shutdown()
            self._controller = None
        cap = getattr(self, "_cap", None)
        if cap is not None:
            cap.Shutdown()
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
        """Yield all draw-call actions recursively from the action tree."""
        if actions is None:
            actions = self._controller.GetRootActions()
        rd = self._rd
        for action in actions:
            if action.flags & rd.ActionFlags.Drawcall:
                yield action
            if action.children:
                yield from self._iter_draws(action.children)

    def _get_framebuffer_dims(self):
        """Return (width, height) of the swap-chain / primary render target."""
        try:
            textures = self._controller.GetTextures()
            for tex in textures:
                if tex.creationFlags & self._rd.TextureCategory.SwapBuffer:
                    return int(tex.width), int(tex.height)
            # Fallback: use largest texture that looks like a framebuffer
            best = None
            for tex in textures:
                if tex.width > 0 and tex.height > 0:
                    if best is None or tex.width * tex.height > best.width * best.height:
                        best = tex
            if best is not None:
                return int(best.width), int(best.height)
        except Exception:
            pass
        return 0, 0

    def _get_output_resource_id(self):
        """Return the resource ID of the primary colour output, or None."""
        try:
            textures = self._controller.GetTextures()
            for tex in textures:
                if tex.creationFlags & self._rd.TextureCategory.SwapBuffer:
                    return tex.resourceId
        except Exception:
            pass
        return None

    def _get_depth_resource_id(self):
        """Return the resource ID of the depth/stencil buffer, or None."""
        try:
            textures = self._controller.GetTextures()
            rd = self._rd
            for tex in textures:
                if tex.creationFlags & rd.TextureCategory.DepthTarget:
                    return tex.resourceId
        except Exception:
            pass
        return None

    # -- FrameProvider implementation ----------------------------------------

    def get_latest_overview(self) -> Optional[FrameOverview]:
        return self.get_frame_overview(self.FRAME_ID)

    def get_frame_overview(self, frame_id: int) -> Optional[FrameOverview]:
        if frame_id != self.FRAME_ID:
            return None

        draw_count = sum(1 for _ in self._iter_draws())
        fb_w, fb_h = self._get_framebuffer_dims()

        return FrameOverview(
            frame_id=self.FRAME_ID,
            draw_call_count=draw_count,
            fb_width=fb_w,
            fb_height=fb_h,
            timestamp=0.0,
        )

    def list_draw_calls(
        self, frame_id: int, limit: int = 50, offset: int = 0
    ) -> List[DrawCallInfo]:
        if frame_id != self.FRAME_ID:
            return []
        all_draws = list(self._iter_draws())
        page = all_draws[offset : offset + limit]
        return [self._action_to_drawcall(i + offset, a) for i, a in enumerate(page)]

    def get_draw_call(self, frame_id: int, dc_id: int) -> Optional[DrawCallInfo]:
        if frame_id != self.FRAME_ID:
            return None
        all_draws = list(self._iter_draws())
        if dc_id < 0 or dc_id >= len(all_draws):
            return None
        return self._action_to_drawcall(dc_id, all_draws[dc_id])

    def get_pixel(self, frame_id: int, x: int, y: int) -> Optional[PixelResult]:
        """Pick a pixel from the primary colour output at the end of the frame."""
        if frame_id != self.FRAME_ID:
            return None

        res_id = self._get_output_resource_id()
        if res_id is None:
            return None

        rd = self._rd
        try:
            all_draws = list(self._iter_draws())
            if not all_draws:
                return None
            last_action = all_draws[-1]
            self._controller.SetFrameEvent(last_action.eventId, True)

            picked = self._controller.PickPixel(
                res_id,
                x,
                y,
                rd.Subresource(),
                rd.CompType.Float,
            )

            floats = picked.value.f
            r = int(max(0.0, min(1.0, floats[0])) * 255)
            g = int(max(0.0, min(1.0, floats[1])) * 255)
            b = int(max(0.0, min(1.0, floats[2])) * 255)
            a = int(max(0.0, min(1.0, floats[3])) * 255)

            depth = 0.0
            stencil = 0
            try:
                depth_res_id = self._get_depth_resource_id()
                if depth_res_id is not None:
                    depth_pick = self._controller.PickPixel(
                        depth_res_id,
                        x,
                        y,
                        rd.Subresource(),
                        rd.CompType.Depth,
                    )
                    depth = float(depth_pick.value.f[0])
            except Exception:
                pass

            return PixelResult(r=r, g=g, b=b, a=a, depth=depth, stencil=stencil)
        except Exception:
            return None

    def compare_frames(
        self, frame_a: int, frame_b: int, depth: str = "summary"
    ) -> Optional[Any]:
        """RenderDoc captures are single-frame; cross-frame comparison is not supported."""
        return None

    # -- Private helpers -----------------------------------------------------

    def _action_to_drawcall(self, idx: int, action) -> DrawCallInfo:
        """Convert a RenderDoc action into a :class:`DrawCallInfo`."""
        pipeline_state: Dict[str, Any] = {}
        params: List[Dict[str, Any]] = []
        textures: List[Dict[str, Any]] = []

        try:
            self._controller.SetFrameEvent(action.eventId, True)
            pipe = self._controller.GetPipelineState()
            pipeline_state = self._extract_pipeline_state(pipe)
            params = self._extract_shader_params(pipe)
            textures = self._extract_textures(pipe)
        except Exception:
            pass

        primitive_type = "UNKNOWN"
        try:
            if hasattr(action, "topology"):
                primitive_type = str(action.topology)
        except Exception:
            pass

        return DrawCallInfo(
            id=idx,
            primitive_type=primitive_type,
            vertex_count=int(getattr(action, "numIndices", 0)),
            index_count=int(getattr(action, "numIndices", 0)),
            instance_count=int(getattr(action, "numInstances", 1)),
            shader_id=0,
            pipeline_state=pipeline_state,
            params=params,
            textures=textures,
        )

    def _extract_pipeline_state(self, pipe) -> Dict[str, Any]:
        """Extract viewport, scissor, blend, depth, and cull state from the pipe."""
        rd = self._rd
        state: Dict[str, Any] = {}

        api = None
        try:
            api = pipe.GetGraphicsAPI()
        except Exception:
            pass

        try:
            if api == rd.GraphicsAPI.OpenGL:
                gl = pipe.GetGLPipelineState()
                vp = (
                    gl.rasterizer.viewports[0]
                    if gl.rasterizer.viewports
                    else None
                )
                if vp is not None:
                    state["viewport_x"] = float(vp.x)
                    state["viewport_y"] = float(vp.y)
                    state["viewport_w"] = float(vp.width)
                    state["viewport_h"] = float(vp.height)
                sc = (
                    gl.rasterizer.scissors[0]
                    if gl.rasterizer.scissors
                    else None
                )
                if sc is not None:
                    state["scissor_enabled"] = bool(sc.enabled)
                    state["scissor_x"] = int(sc.x)
                    state["scissor_y"] = int(sc.y)
                    state["scissor_w"] = int(sc.width)
                    state["scissor_h"] = int(sc.height)
                ds = gl.depthState
                state["depth_test_enabled"] = bool(ds.depthEnable)
                state["depth_write_enabled"] = bool(ds.depthWrites)
                state["depth_func"] = str(ds.depthFunction)
                rs = gl.rasterizer.state
                state["cull_enabled"] = bool(
                    rs.cullMode != rd.CullMode.NoCulling
                )
                state["cull_mode"] = str(rs.cullMode)
                state["front_face"] = str(rs.frontFace)
                blend = gl.colorBlend
                if blend.blends:
                    b0 = blend.blends[0]
                    state["blend_enabled"] = bool(b0.enabled)
                    state["blend_src"] = str(b0.colorBlend.source)
                    state["blend_dst"] = str(b0.colorBlend.destination)

            elif api == rd.GraphicsAPI.Vulkan:
                vk = pipe.GetVulkanPipelineState()
                vp_state = vk.viewportScissor
                if vp_state.viewportScissors:
                    vp = vp_state.viewportScissors[0].vp
                    sc = vp_state.viewportScissors[0].scissor
                    state["viewport_x"] = float(vp.x)
                    state["viewport_y"] = float(vp.y)
                    state["viewport_w"] = float(vp.width)
                    state["viewport_h"] = float(vp.height)
                    state["scissor_enabled"] = True
                    state["scissor_x"] = int(sc.x)
                    state["scissor_y"] = int(sc.y)
                    state["scissor_w"] = int(sc.width)
                    state["scissor_h"] = int(sc.height)
                ds = vk.depthStencil
                state["depth_test_enabled"] = bool(ds.depthTestEnable)
                state["depth_write_enabled"] = bool(ds.depthWriteEnable)
                state["depth_func"] = str(ds.depthFunction)
                rs = vk.rasterizer
                state["cull_enabled"] = bool(
                    rs.cullMode != rd.CullMode.NoCulling
                )
                state["cull_mode"] = str(rs.cullMode)
                state["front_face"] = str(rs.frontFace)
                if vk.colorBlend.blends:
                    b0 = vk.colorBlend.blends[0]
                    state["blend_enabled"] = bool(b0.enabled)
                    state["blend_src"] = str(b0.colorBlend.source)
                    state["blend_dst"] = str(b0.colorBlend.destination)

            else:
                # Generic fallback — D3D11/D3D12 or unknown API
                state["api"] = str(api) if api is not None else "unknown"
        except Exception:
            pass

        return state

    def _extract_shader_params(self, pipe) -> List[Dict[str, Any]]:
        """Extract constant-buffer uniform values for VS and FS stages."""
        rd = self._rd
        params: List[Dict[str, Any]] = []

        for stage in (rd.ShaderStage.Vertex, rd.ShaderStage.Fragment):
            try:
                refl = pipe.GetShaderReflection(stage)
                if refl is None:
                    continue
                for cb_idx, _cb in enumerate(refl.constantBlocks):
                    try:
                        cb_info = pipe.GetConstantBuffer(stage, cb_idx, 0)
                        variables = self._controller.GetCBufferVariableContents(
                            pipe.GetGraphicsPipelineObject(),
                            pipe.GetShader(stage),
                            stage,
                            pipe.GetShaderEntryPoint(stage),
                            cb_idx,
                            cb_info.resourceId,
                            0,
                        )
                        stage_label = (
                            "vertex"
                            if stage == rd.ShaderStage.Vertex
                            else "fragment"
                        )
                        for var in variables:
                            value = self._shader_var_to_python(var)
                            params.append(
                                {
                                    "name": str(var.name),
                                    "type": str(
                                        var.type.descriptor.type
                                    ),
                                    "data": value,
                                    "stage": stage_label,
                                }
                            )
                    except Exception:
                        continue
            except Exception:
                continue

        return params

    def _extract_textures(self, pipe) -> List[Dict[str, Any]]:
        """Extract bound texture info for VS and FS stages."""
        rd = self._rd
        textures: List[Dict[str, Any]] = []
        all_textures_by_id: Dict[Any, Any] = {}

        try:
            for tex in self._controller.GetTextures():
                all_textures_by_id[tex.resourceId] = tex
        except Exception:
            pass

        slot = 0
        for stage in (rd.ShaderStage.Vertex, rd.ShaderStage.Fragment):
            try:
                refl = pipe.GetShaderReflection(stage)
                if refl is None:
                    continue
                stage_label = (
                    "vertex" if stage == rd.ShaderStage.Vertex else "fragment"
                )
                for res in refl.readOnlyResources:
                    try:
                        bound = pipe.GetReadOnlyResource(stage, res.bindPoint)
                        res_id = (
                            bound.resources[0].resourceId
                            if bound.resources
                            else None
                        )
                        tex_info = (
                            all_textures_by_id.get(res_id)
                            if res_id is not None
                            else None
                        )
                        textures.append(
                            {
                                "slot": slot,
                                "name": str(res.name),
                                "texture_id": (
                                    int(res_id) if res_id is not None else 0
                                ),
                                "width": (
                                    int(tex_info.width)
                                    if tex_info is not None
                                    else 0
                                ),
                                "height": (
                                    int(tex_info.height)
                                    if tex_info is not None
                                    else 0
                                ),
                                "format": (
                                    str(tex_info.format.Name())
                                    if tex_info is not None
                                    else "unknown"
                                ),
                                "stage": stage_label,
                            }
                        )
                        slot += 1
                    except Exception:
                        slot += 1
                        continue
            except Exception:
                continue

        return textures

    @staticmethod
    def _shader_var_to_python(var) -> Any:
        """Convert a RenderDoc ShaderVariable to a plain Python value."""
        try:
            rows = var.rows
            cols = var.columns
            floats = list(var.value.f)
            if rows == 1 and cols == 1:
                return floats[0]
            if rows == 1:
                return floats[:cols]
            # Matrix: rows x cols
            matrix = []
            for r in range(rows):
                matrix.append(floats[r * cols : (r + 1) * cols])
            return matrix
        except Exception:
            try:
                return list(var.value.f)
            except Exception:
                return None

