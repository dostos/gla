"""Tests for the backend abstraction layer."""
from unittest.mock import MagicMock

import pytest

from gla.backends.base import (
    DrawCallInfo,
    FrameOverview,
    FrameProvider,
    PixelResult,
    SceneInfo,
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
            def get_scene(self, fid): return None
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
        assert dc.params == [{"name": "uMVP", "type": "mat4", "data": list(range(16))}]

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

class TestRenderDocBackend:
    def test_import_error_gives_clear_message(self):
        """When renderdoc is not installed, init raises RuntimeError."""
        from gla.backends.renderdoc import RenderDocBackend
        with pytest.raises(RuntimeError, match="RenderDoc Python module not available"):
            RenderDocBackend("/nonexistent/capture.rdc")
