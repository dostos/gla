"""Tests for the backend abstraction layer."""
from unittest.mock import MagicMock

import pytest

from gla.backends.base import (
    DrawCallInfo,
    FrameOverview,
    FrameProvider,
    PixelResult,
)
from gla.backends.native import NativeBackend


# ---------------------------------------------------------------------------
# FrameProvider ABC
# ---------------------------------------------------------------------------

class TestFrameProviderABC:
    def test_cannot_instantiate_directly(self):
        with pytest.raises(TypeError):
            FrameProvider()

    def test_default_control_methods(self):
        """Default control methods return 'not_supported'."""
        # Create a concrete subclass with minimal implementation
        class Stub(FrameProvider):
            def get_latest_overview(self): return None
            def get_frame_overview(self, fid): return None
            def list_draw_calls(self, fid, limit=50, offset=0): return []
            def get_draw_call(self, fid, dcid): return None
            def get_pixel(self, fid, x, y): return None
            def compare_frames(self, fa, fb, depth="summary"): return None

        stub = Stub()
        assert stub.pause()["state"] == "not_supported"
        assert stub.resume()["state"] == "not_supported"
        assert stub.step()["state"] == "not_supported"
        assert stub.status()["state"] == "capture_mode"
        assert stub.supports_live_control is False
        assert stub.backend_name == "unknown"


# ---------------------------------------------------------------------------
# NativeBackend adapter
# ---------------------------------------------------------------------------

def _mock_overview(frame_id=1):
    ov = MagicMock()
    ov.frame_id = frame_id
    ov.draw_call_count = 10
    ov.fb_width = 1920
    ov.fb_height = 1080
    ov.timestamp = 42.0
    return ov


def _mock_drawcall(dc_id=0):
    dc = MagicMock()
    dc.id = dc_id
    dc.primitive_type = "TRIANGLES"
    dc.vertex_count = 36
    dc.index_count = 36
    dc.instance_count = 1
    dc.shader_id = 5
    ps = MagicMock()
    ps.viewport = (0, 0, 1920, 1080)
    ps.scissor = (0, 0, 1920, 1080)
    ps.scissor_enabled = False
    ps.blend_enabled = False
    ps.blend_src = "ONE"
    ps.blend_dst = "ZERO"
    ps.depth_test = True
    ps.depth_write = True
    ps.depth_func = "LESS"
    ps.cull_enabled = True
    ps.cull_mode = "BACK"
    ps.front_face = "CCW"
    dc.pipeline = ps
    param = MagicMock()
    param.name = "uMVP"
    param.type = "mat4"
    param.data = list(range(16))
    dc.params = [param]
    dc.textures = []
    return dc


def _mock_pixel():
    pr = MagicMock()
    pr.r = 128
    pr.g = 64
    pr.b = 32
    pr.a = 255
    pr.depth = 0.9
    pr.stencil = 1
    return pr


class TestNativeBackend:
    def test_backend_name(self):
        qe = MagicMock()
        backend = NativeBackend(qe)
        assert backend.backend_name == "native"

    def test_supports_live_control_with_engine(self):
        backend = NativeBackend(MagicMock(), engine=MagicMock())
        assert backend.supports_live_control is True

    def test_supports_live_control_without_engine(self):
        backend = NativeBackend(MagicMock())
        assert backend.supports_live_control is False

    def test_get_latest_overview_converts_to_dataclass(self):
        qe = MagicMock()
        qe.latest_frame_overview.return_value = _mock_overview(1)
        backend = NativeBackend(qe)
        ov = backend.get_latest_overview()
        assert isinstance(ov, FrameOverview)
        assert ov.frame_id == 1
        assert ov.fb_width == 1920

    def test_get_latest_overview_none(self):
        qe = MagicMock()
        qe.latest_frame_overview.return_value = None
        backend = NativeBackend(qe)
        assert backend.get_latest_overview() is None

    def test_get_frame_overview_converts(self):
        qe = MagicMock()
        qe.frame_overview.return_value = _mock_overview(5)
        backend = NativeBackend(qe)
        ov = backend.get_frame_overview(5)
        assert isinstance(ov, FrameOverview)
        assert ov.frame_id == 5

    def test_list_draw_calls_converts(self):
        qe = MagicMock()
        qe.list_draw_calls.return_value = [_mock_drawcall(0), _mock_drawcall(1)]
        backend = NativeBackend(qe)
        dcs = backend.list_draw_calls(1)
        assert len(dcs) == 2
        assert all(isinstance(dc, DrawCallInfo) for dc in dcs)
        assert dcs[0].pipeline_state["depth_test_enabled"] is True

    def test_get_draw_call_converts(self):
        qe = MagicMock()
        qe.get_draw_call.return_value = _mock_drawcall(7)
        backend = NativeBackend(qe)
        dc = backend.get_draw_call(1, 7)
        assert isinstance(dc, DrawCallInfo)
        assert dc.id == 7
        import base64
        expected_data = base64.b64encode(bytes(range(16))).decode("ascii")
        assert dc.params == [{"name": "uMVP", "type": "mat4", "data": expected_data}]

    def test_get_draw_call_none(self):
        qe = MagicMock()
        qe.get_draw_call.return_value = None
        backend = NativeBackend(qe)
        assert backend.get_draw_call(1, 999) is None

    def test_get_pixel_converts(self):
        qe = MagicMock()
        qe.get_pixel.return_value = _mock_pixel()
        backend = NativeBackend(qe)
        px = backend.get_pixel(1, 100, 200)
        assert isinstance(px, PixelResult)
        assert px.r == 128
        assert px.depth == pytest.approx(0.9)

    def test_get_pixel_none(self):
        qe = MagicMock()
        qe.get_pixel.return_value = None
        backend = NativeBackend(qe)
        assert backend.get_pixel(1, -1, -1) is None

    def test_compare_frames_delegates(self):
        qe = MagicMock()
        qe.compare_frames.return_value = "some_diff"
        backend = NativeBackend(qe)
        assert backend.compare_frames(1, 2, "summary") == "some_diff"
        qe.compare_frames.assert_called_once_with(1, 2, "summary")

    def test_pause_with_engine(self):
        eng = MagicMock()
        backend = NativeBackend(MagicMock(), engine=eng)
        result = backend.pause()
        eng.pause.assert_called_once()
        assert result["status"] == "paused"

    def test_pause_without_engine(self):
        backend = NativeBackend(MagicMock())
        result = backend.pause()
        assert result["state"] == "not_supported"

    def test_status_with_engine(self):
        eng = MagicMock()
        eng.is_running.return_value = False
        backend = NativeBackend(MagicMock(), engine=eng)
        result = backend.status()
        assert result["state"] == "paused"
        assert result["is_running"] is False


# ---------------------------------------------------------------------------
# RenderDocBackend
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Helpers: build a minimal mock renderdoc module + controller
# ---------------------------------------------------------------------------

def _make_rd_module():
    """Return a mock ``renderdoc`` module with the constants we use."""
    rd = MagicMock(name="renderdoc")

    # ResultCode
    rd.ResultCode.Succeeded = "Succeeded"

    # ActionFlags — use distinct sentinel objects so bitwise-AND works
    class _AF:
        Drawcall = 0b01
        Clear = 0b10
    rd.ActionFlags = _AF

    # TextureCategory
    class _TC:
        SwapBuffer = 0b0001
        DepthTarget = 0b0010
        ColourTarget = 0b0100
    rd.TextureCategory = _TC

    # GraphicsAPI
    class _GAPI:
        OpenGL = "OpenGL"
        Vulkan = "Vulkan"
    rd.GraphicsAPI = _GAPI

    # ShaderStage
    class _SS:
        Vertex = "Vertex"
        Fragment = "Fragment"
    rd.ShaderStage = _SS

    # CullMode
    class _CM:
        NoCulling = "NoCulling"
        Back = "Back"
    rd.CullMode = _CM

    # Subresource / CompType
    rd.Subresource = MagicMock(return_value=MagicMock())
    rd.CompType.Float = "Float"
    rd.CompType.Depth = "Depth"

    # ReplayOptions
    rd.ReplayOptions = MagicMock(return_value=MagicMock())

    return rd


def _make_mock_action(event_id=1, name="Draw", num_indices=3, num_instances=1,
                      topology="Topology.TriangleList", flags=None, children=None):
    a = MagicMock()
    a.eventId = event_id
    a.name = name
    a.numIndices = num_indices
    a.numInstances = num_instances
    a.topology = topology
    a.flags = flags if flags is not None else 0b01  # ActionFlags.Drawcall
    a.children = children or []
    return a


def _make_mock_texture(resource_id=1, width=1920, height=1080,
                       creation_flags=0b0001):  # SwapBuffer by default
    t = MagicMock()
    t.resourceId = resource_id
    t.width = width
    t.height = height
    t.creationFlags = creation_flags
    fmt = MagicMock()
    fmt.Name.return_value = "R8G8B8A8_UNORM"
    t.format = fmt
    return t


def _make_mock_controller(actions=None, textures=None, pixel_floats=None):
    ctrl = MagicMock()
    ctrl.GetRootActions.return_value = actions or []
    ctrl.GetTextures.return_value = textures or []

    if pixel_floats is not None:
        pick = MagicMock()
        pick.value.f = pixel_floats
        ctrl.PickPixel.return_value = pick

    pipe = MagicMock()
    pipe.GetGraphicsAPI.return_value = "OpenGL"
    pipe.GetShaderReflection.return_value = None  # no uniforms by default
    ctrl.GetPipelineState.return_value = pipe

    return ctrl


def _make_mock_cap(controller, rd, open_result=None):
    """Return a mock CaptureFile that yields the given controller."""
    cap = MagicMock()
    cap.OpenFile.return_value = open_result if open_result is not None else rd.ResultCode.Succeeded
    cap.LocalReplaySupport.return_value = True
    cap.OpenCapture.return_value = (rd.ResultCode.Succeeded, controller)
    return cap


# ---------------------------------------------------------------------------
# Actual tests
# ---------------------------------------------------------------------------

class TestRenderDocBackend:
    """Unit tests for RenderDocBackend using a mock renderdoc module."""

    # ------------------------------------------------------------------ #
    # Import-error / bad-file handling
    # ------------------------------------------------------------------ #

    def test_import_error_gives_clear_message(self):
        """When renderdoc is not installed, init raises RuntimeError."""
        from gla.backends.renderdoc import RenderDocBackend
        with pytest.raises(RuntimeError, match="RenderDoc Python module not available"):
            RenderDocBackend("/nonexistent/capture.rdc")

    def test_open_file_failure_raises(self):
        """A bad ResultCode from OpenFile raises RuntimeError."""
        import sys
        from unittest.mock import patch

        rd = _make_rd_module()
        ctrl = _make_mock_controller()
        cap = _make_mock_cap(ctrl, rd, open_result="SomeError")

        rd.OpenCaptureFile = MagicMock(return_value=cap)

        with patch.dict(sys.modules, {"renderdoc": rd}):
            from importlib import reload
            import gla.backends.renderdoc as rmod
            reload(rmod)
            with pytest.raises(RuntimeError, match="Failed to open"):
                rmod.RenderDocBackend("/fake/path.rdc")

    def test_local_replay_not_supported_raises(self):
        """LocalReplaySupport() == False raises RuntimeError."""
        import sys
        from unittest.mock import patch

        rd = _make_rd_module()
        ctrl = _make_mock_controller()
        cap = _make_mock_cap(ctrl, rd)
        cap.LocalReplaySupport.return_value = False
        rd.OpenCaptureFile = MagicMock(return_value=cap)

        with patch.dict(sys.modules, {"renderdoc": rd}):
            from importlib import reload
            import gla.backends.renderdoc as rmod
            reload(rmod)
            with pytest.raises(RuntimeError, match="Local replay not supported"):
                rmod.RenderDocBackend("/fake/path.rdc")

    # ------------------------------------------------------------------ #
    # Factory helper
    # ------------------------------------------------------------------ #

    def _make_backend(self, actions=None, textures=None, pixel_floats=None):
        """Instantiate RenderDocBackend with mocked renderdoc internals."""
        import sys
        from unittest.mock import patch
        from importlib import reload

        rd = _make_rd_module()
        ctrl = _make_mock_controller(
            actions=actions,
            textures=textures,
            pixel_floats=pixel_floats,
        )
        cap = _make_mock_cap(ctrl, rd)
        rd.OpenCaptureFile = MagicMock(return_value=cap)

        with patch.dict(sys.modules, {"renderdoc": rd}):
            import gla.backends.renderdoc as rmod
            reload(rmod)
            backend = rmod.RenderDocBackend.__new__(rmod.RenderDocBackend)
            backend._rd = rd
            backend._path = "/fake/path.rdc"
            backend._cap = cap
            backend._controller = ctrl

        # Patch _rd on the backend so instance methods resolve the right module
        backend._rd = rd
        backend._controller = ctrl
        return backend

    # ------------------------------------------------------------------ #
    # backend_name / capabilities
    # ------------------------------------------------------------------ #

    def test_backend_name(self):
        b = self._make_backend()
        assert b.backend_name == "renderdoc"

    def test_supports_live_control_is_false(self):
        b = self._make_backend()
        assert b.supports_live_control is False

    def test_compare_frames_returns_none(self):
        b = self._make_backend()
        assert b.compare_frames(0, 1) is None

    # ------------------------------------------------------------------ #
    # _iter_draws / _collect_draws recursion
    # ------------------------------------------------------------------ #

    def test_iter_draws_flat_list(self):
        """Flat list of draw actions is iterated directly."""
        rd = _make_rd_module()
        a0 = _make_mock_action(event_id=1, flags=rd.ActionFlags.Drawcall)
        a1 = _make_mock_action(event_id=2, flags=rd.ActionFlags.Drawcall)
        b = self._make_backend(actions=[a0, a1])
        draws = list(b._iter_draws())
        assert len(draws) == 2
        assert draws[0].eventId == 1
        assert draws[1].eventId == 2

    def test_iter_draws_filters_non_draw(self):
        """Non-draw actions (e.g. Clear) are excluded."""
        rd = _make_rd_module()
        clear = _make_mock_action(event_id=1, flags=rd.ActionFlags.Clear)
        draw = _make_mock_action(event_id=2, flags=rd.ActionFlags.Drawcall)
        b = self._make_backend(actions=[clear, draw])
        draws = list(b._iter_draws())
        assert len(draws) == 1
        assert draws[0].eventId == 2

    def test_iter_draws_recursive_children(self):
        """Children are traversed recursively."""
        rd = _make_rd_module()
        child1 = _make_mock_action(event_id=10, flags=rd.ActionFlags.Drawcall)
        child2 = _make_mock_action(event_id=11, flags=rd.ActionFlags.Drawcall)
        parent = _make_mock_action(event_id=5, flags=0, children=[child1, child2])
        b = self._make_backend(actions=[parent])
        draws = list(b._iter_draws())
        assert len(draws) == 2
        assert {d.eventId for d in draws} == {10, 11}

    def test_iter_draws_mixed_nested(self):
        """Mix of top-level and nested draws."""
        rd = _make_rd_module()
        top = _make_mock_action(event_id=1, flags=rd.ActionFlags.Drawcall)
        nested_draw = _make_mock_action(event_id=3, flags=rd.ActionFlags.Drawcall)
        group = _make_mock_action(event_id=2, flags=0, children=[nested_draw])
        b = self._make_backend(actions=[top, group])
        draws = list(b._iter_draws())
        assert len(draws) == 2

    # ------------------------------------------------------------------ #
    # get_frame_overview
    # ------------------------------------------------------------------ #

    def test_get_frame_overview_returns_correct_data(self):
        rd = _make_rd_module()
        draw = _make_mock_action(flags=rd.ActionFlags.Drawcall)
        tex = _make_mock_texture(width=800, height=600,
                                  creation_flags=rd.TextureCategory.SwapBuffer)
        b = self._make_backend(actions=[draw], textures=[tex])
        ov = b.get_frame_overview(0)
        assert isinstance(ov, FrameOverview)
        assert ov.frame_id == 0
        assert ov.draw_call_count == 1
        assert ov.fb_width == 800
        assert ov.fb_height == 600

    def test_get_frame_overview_wrong_frame_returns_none(self):
        b = self._make_backend()
        assert b.get_frame_overview(99) is None

    def test_get_latest_overview_delegates(self):
        rd = _make_rd_module()
        draw = _make_mock_action(flags=rd.ActionFlags.Drawcall)
        b = self._make_backend(actions=[draw])
        ov = b.get_latest_overview()
        assert ov is not None
        assert ov.frame_id == 0

    # ------------------------------------------------------------------ #
    # list_draw_calls / get_draw_call
    # ------------------------------------------------------------------ #

    def test_list_draw_calls_returns_all(self):
        rd = _make_rd_module()
        draws = [_make_mock_action(event_id=i, flags=rd.ActionFlags.Drawcall) for i in range(5)]
        b = self._make_backend(actions=draws)
        result = b.list_draw_calls(0)
        assert len(result) == 5
        assert all(isinstance(dc, DrawCallInfo) for dc in result)

    def test_list_draw_calls_pagination(self):
        rd = _make_rd_module()
        draws = [_make_mock_action(event_id=i, flags=rd.ActionFlags.Drawcall) for i in range(10)]
        b = self._make_backend(actions=draws)
        page = b.list_draw_calls(0, limit=3, offset=4)
        assert len(page) == 3
        assert page[0].id == 4

    def test_list_draw_calls_wrong_frame(self):
        rd = _make_rd_module()
        draw = _make_mock_action(flags=rd.ActionFlags.Drawcall)
        b = self._make_backend(actions=[draw])
        assert b.list_draw_calls(5) == []

    def test_get_draw_call_valid_index(self):
        rd = _make_rd_module()
        draws = [_make_mock_action(event_id=i, num_indices=6,
                                   flags=rd.ActionFlags.Drawcall) for i in range(3)]
        b = self._make_backend(actions=draws)
        dc = b.get_draw_call(0, 1)
        assert isinstance(dc, DrawCallInfo)
        assert dc.id == 1
        assert dc.index_count == 6

    def test_get_draw_call_out_of_range(self):
        b = self._make_backend()
        assert b.get_draw_call(0, 999) is None

    def test_get_draw_call_wrong_frame(self):
        b = self._make_backend()
        assert b.get_draw_call(1, 0) is None

    # ------------------------------------------------------------------ #
    # _action_to_drawcall conversion
    # ------------------------------------------------------------------ #

    def test_action_to_drawcall_vertex_count(self):
        rd = _make_rd_module()
        action = _make_mock_action(num_indices=12, num_instances=2,
                                   topology="TriangleList",
                                   flags=rd.ActionFlags.Drawcall)
        b = self._make_backend(actions=[action])
        dc = b._action_to_drawcall(0, action)
        assert dc.vertex_count == 12
        assert dc.index_count == 12
        assert dc.instance_count == 2
        assert dc.primitive_type == "TriangleList"

    def test_action_to_drawcall_is_drawcallinfo(self):
        rd = _make_rd_module()
        action = _make_mock_action(flags=rd.ActionFlags.Drawcall)
        b = self._make_backend(actions=[action])
        dc = b._action_to_drawcall(7, action)
        assert isinstance(dc, DrawCallInfo)
        assert dc.id == 7
        assert dc.shader_id == 0

    def test_action_to_drawcall_pipeline_state_empty_on_error(self):
        """If SetFrameEvent raises, pipeline_state is still a dict."""
        rd = _make_rd_module()
        action = _make_mock_action(flags=rd.ActionFlags.Drawcall)
        b = self._make_backend(actions=[action])
        b._controller.SetFrameEvent.side_effect = Exception("boom")
        dc = b._action_to_drawcall(0, action)
        assert isinstance(dc.pipeline_state, dict)

    # ------------------------------------------------------------------ #
    # get_pixel
    # ------------------------------------------------------------------ #

    def test_get_pixel_converts_floats_to_bytes(self):
        rd = _make_rd_module()
        draw = _make_mock_action(flags=rd.ActionFlags.Drawcall)
        tex = _make_mock_texture(resource_id=42,
                                  creation_flags=rd.TextureCategory.SwapBuffer)
        pixel_floats = [1.0, 0.5, 0.25, 1.0]
        b = self._make_backend(actions=[draw], textures=[tex],
                                pixel_floats=pixel_floats)
        result = b.get_pixel(0, 100, 200)
        assert isinstance(result, PixelResult)
        assert result.r == 255
        assert result.g == 127
        assert result.b == 63
        assert result.a == 255

    def test_get_pixel_wrong_frame_returns_none(self):
        b = self._make_backend()
        assert b.get_pixel(1, 0, 0) is None

    def test_get_pixel_no_swap_buffer_returns_none(self):
        """If there is no SwapBuffer texture, get_pixel returns None."""
        rd = _make_rd_module()
        draw = _make_mock_action(flags=rd.ActionFlags.Drawcall)
        # Texture is a depth target, not a swap buffer
        tex = _make_mock_texture(creation_flags=rd.TextureCategory.DepthTarget)
        b = self._make_backend(actions=[draw], textures=[tex])
        result = b.get_pixel(0, 10, 10)
        assert result is None

    def test_get_pixel_no_draws_returns_none(self):
        rd = _make_rd_module()
        tex = _make_mock_texture(creation_flags=rd.TextureCategory.SwapBuffer)
        b = self._make_backend(actions=[], textures=[tex])
        result = b.get_pixel(0, 10, 10)
        assert result is None

    def test_get_pixel_clamps_values(self):
        """Float values outside [0,1] are clamped."""
        rd = _make_rd_module()
        draw = _make_mock_action(flags=rd.ActionFlags.Drawcall)
        tex = _make_mock_texture(creation_flags=rd.TextureCategory.SwapBuffer)
        pixel_floats = [2.0, -0.5, 0.0, 1.5]
        b = self._make_backend(actions=[draw], textures=[tex],
                                pixel_floats=pixel_floats)
        result = b.get_pixel(0, 0, 0)
        assert result.r == 255
        assert result.g == 0
        assert result.b == 0
        assert result.a == 255

    # ------------------------------------------------------------------ #
    # _shader_var_to_python
    # ------------------------------------------------------------------ #

    def test_shader_var_scalar(self):
        from gla.backends.renderdoc import RenderDocBackend
        var = MagicMock()
        var.rows = 1
        var.columns = 1
        var.value.f = [3.14, 0.0, 0.0, 0.0]
        result = RenderDocBackend._shader_var_to_python(var)
        assert result == pytest.approx(3.14)

    def test_shader_var_vec3(self):
        from gla.backends.renderdoc import RenderDocBackend
        var = MagicMock()
        var.rows = 1
        var.columns = 3
        var.value.f = [1.0, 2.0, 3.0, 0.0]
        result = RenderDocBackend._shader_var_to_python(var)
        assert result == pytest.approx([1.0, 2.0, 3.0])

    def test_shader_var_mat4(self):
        from gla.backends.renderdoc import RenderDocBackend
        var = MagicMock()
        var.rows = 4
        var.columns = 4
        var.value.f = list(range(16))
        result = RenderDocBackend._shader_var_to_python(var)
        assert len(result) == 4
        assert result[0] == [0, 1, 2, 3]
        assert result[3] == [12, 13, 14, 15]

    # ------------------------------------------------------------------ #
    # close / __del__
    # ------------------------------------------------------------------ #

    def test_close_shuts_down_controller_and_cap(self):
        rd = _make_rd_module()
        ctrl = _make_mock_controller()
        cap = _make_mock_cap(ctrl, rd)
        b = self._make_backend()
        b._controller = ctrl
        b._cap = cap
        b.close()
        ctrl.Shutdown.assert_called_once()
        cap.Shutdown.assert_called_once()
        assert b._controller is None
        assert b._cap is None

    def test_close_idempotent(self):
        b = self._make_backend()
        b._controller = None
        b._cap = None
        b.close()  # should not raise
