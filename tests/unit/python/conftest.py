"""Shared pytest fixtures for GLA REST API tests.

All C++ (_gla_core) types are mocked — no native extension needed at test time.
The test fixtures now construct a NativeBackend around mock objects, so the
routes exercise the full provider-based code path.
"""
from unittest.mock import MagicMock

import pytest
from starlette.testclient import TestClient

from gla.api.app import create_app
from gla.backends.native import NativeBackend

AUTH_TOKEN = "test-token"
AUTH_HEADERS = {"Authorization": f"Bearer {AUTH_TOKEN}"}


@pytest.fixture
def auth_headers() -> dict:
    """Authorization headers with the test Bearer token."""
    return AUTH_HEADERS.copy()


# ---------------------------------------------------------------------------
# Helpers to build realistic mock objects
# ---------------------------------------------------------------------------


def _make_overview(frame_id: int = 1) -> MagicMock:
    ov = MagicMock()
    ov.frame_id = frame_id
    ov.draw_call_count = 42
    ov.clear_count = 0
    ov.fb_width = 800
    ov.fb_height = 600
    ov.timestamp = 1234.5
    return ov


def _make_drawcall(dc_id: int = 0, frame_id: int = 1) -> MagicMock:
    dc = MagicMock()
    dc.id = dc_id
    dc.primitive_type = "TRIANGLES"
    dc.vertex_count = 3
    dc.instance_count = 1
    dc.index_count = 0
    dc.shader_id = 7
    ps = MagicMock()
    ps.viewport = (0, 0, 800, 600)
    ps.scissor = (0, 0, 800, 600)
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
    # Shader params attached directly to the draw call
    param = MagicMock()
    param.name = "uColor"
    # GL_FLOAT_VEC4 = 0x8B52; encode vec4(1.0, 0.0, 0.0, 1.0) as 16 raw bytes
    import struct as _struct
    param.type = 0x8B52  # GL_FLOAT_VEC4
    param.data = _struct.pack("<4f", 1.0, 0.0, 0.0, 1.0)
    dc.params = [param]
    # Texture bindings attached directly to the draw call
    tex = MagicMock()
    tex.slot = 0
    tex.texture_id = 3
    tex.width = 512
    tex.height = 512
    tex.format = "RGBA8"
    dc.textures = [tex]
    dc.fbo_color_attachment_tex = 7  # simulates render-to-texture FBO
    return dc


def _make_pixel_result() -> MagicMock:
    pr = MagicMock()
    pr.r = 255
    pr.g = 0
    pr.b = 128
    pr.a = 255
    pr.depth = 0.5
    pr.stencil = 0
    return pr


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_query_engine() -> MagicMock:
    """QueryEngine mock with preset return values covering the happy path."""
    qe = MagicMock()

    # Frame overview — routes call latest_frame_overview() and frame_overview()
    qe.latest_frame_overview.return_value = _make_overview(frame_id=1)
    qe.frame_overview.side_effect = lambda fid: (
        _make_overview(frame_id=fid) if fid == 1 else None
    )

    # Draw calls — routes call list_draw_calls() and get_draw_call()
    dc = _make_drawcall(dc_id=0)
    qe.list_draw_calls.side_effect = lambda fid, limit=50, offset=0: (
        [dc] if fid == 1 else []
    )
    qe.get_draw_call.side_effect = lambda fid, dcid: (
        dc if (fid == 1 and dcid == 0) else None
    )

    # Pixel — routes call get_pixel()
    qe.get_pixel.side_effect = lambda fid, x, y: (
        _make_pixel_result()
        if (fid == 1 and 0 <= x < 800 and 0 <= y < 600)
        else None
    )

    # Frame diff — routes call compare_frames()
    def _make_frame_diff(fid_a, fid_b, depth="summary"):
        if fid_a not in (1, 2) or fid_b not in (1, 2):
            return None
        diff = MagicMock()
        diff.frame_id_a           = fid_a
        diff.frame_id_b           = fid_b
        diff.draw_calls_added     = 1
        diff.draw_calls_removed   = 0
        diff.draw_calls_modified  = 2
        diff.draw_calls_unchanged = 5
        diff.pixels_changed       = 1234
        diff.draw_call_diffs      = []
        diff.pixel_diffs          = []
        return diff

    qe.compare_frames.side_effect = _make_frame_diff

    return qe


@pytest.fixture
def mock_engine() -> MagicMock:
    """Engine mock for pause/resume/step/status control operations."""
    eng = MagicMock()
    eng.is_running.return_value = True
    return eng


@pytest.fixture
def client(mock_query_engine, mock_engine) -> TestClient:
    """TestClient with Bearer token pre-configured."""
    provider = NativeBackend(mock_query_engine, engine=mock_engine)
    app = create_app(
        provider=provider,
        auth_token=AUTH_TOKEN,
    )
    return TestClient(app, raise_server_exceptions=True)
