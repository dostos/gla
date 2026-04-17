"""Tests for /api/v1/frames/{frame_id}/scene/* endpoints."""
from unittest.mock import MagicMock

import pytest
from starlette.testclient import TestClient

from gla.api.app import create_app
from gla.backends.native import NativeBackend

AUTH_TOKEN = "test-token"
AUTH_HEADERS = {"Authorization": f"Bearer {AUTH_TOKEN}"}


# ---------------------------------------------------------------------------
# Mock helpers
# ---------------------------------------------------------------------------

def _make_camera() -> MagicMock:
    cam = MagicMock()
    cam.position = (5.0, 3.0, 2.0)
    cam.forward = (-0.707, -0.408, -0.577)
    cam.up = (0.0, 1.0, 0.0)
    cam.fov_y_degrees = 60.0
    cam.aspect = 1.778
    cam.near_plane = 0.1
    cam.far_plane = 100.0
    cam.is_perspective = True
    cam.confidence = 0.9
    return cam


def _make_object(obj_id: int = 0) -> MagicMock:
    obj = MagicMock()
    obj.id = obj_id
    obj.draw_call_ids = [0, 1]
    obj.world_transform = [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 5, 0, 3, 1]
    obj.bbox_min = (-1.0, -1.0, -1.0)
    obj.bbox_max = (1.0, 1.0, 1.0)
    obj.visible = True
    obj.confidence = 0.85
    return obj


def _make_scene_info(quality: str = "full", has_camera: bool = True) -> MagicMock:
    scene = MagicMock()
    scene.reconstruction_quality = quality
    scene.camera = _make_camera() if has_camera else None
    scene.objects = [_make_object(0)]
    return scene


def _make_overview(frame_id: int = 1) -> MagicMock:
    ov = MagicMock()
    ov.frame_id = frame_id
    ov.draw_call_count = 2
    ov.fb_width = 800
    ov.fb_height = 600
    ov.timestamp = 100.0
    return ov


def _make_normalized_frame() -> MagicMock:
    return MagicMock()


def _make_query_engine(frame_id: int = 1, has_frame: bool = True) -> MagicMock:
    qe = MagicMock()
    qe.frame_overview.side_effect = lambda fid: (
        _make_overview(fid) if fid == frame_id else None
    )
    qe.get_normalized_frame.side_effect = lambda fid: (
        _make_normalized_frame() if (fid == frame_id and has_frame) else None
    )
    return qe


def _make_reconstructor(quality: str = "full", has_camera: bool = True) -> MagicMock:
    rec = MagicMock()
    rec.reconstruct.return_value = _make_scene_info(quality, has_camera)
    return rec


def _make_client(quality: str = "full", has_camera: bool = True,
                 has_frame: bool = True) -> TestClient:
    qe = _make_query_engine(has_frame=has_frame)
    rec = _make_reconstructor(quality, has_camera)
    provider = NativeBackend(qe, scene_reconstructor=rec)
    app = create_app(
        provider=provider,
        auth_token=AUTH_TOKEN,
    )
    return TestClient(app, raise_server_exceptions=True)


# ---------------------------------------------------------------------------
# Tests: GET /frames/{frame_id}/scene/camera
# ---------------------------------------------------------------------------

class TestGetCamera:
    def test_200_with_camera_info(self):
        client = _make_client()
        resp = client.get("/api/v1/frames/1/scene/camera", headers=AUTH_HEADERS)
        assert resp.status_code == 200
        data = resp.json()
        assert data["position"] == pytest.approx([5.0, 3.0, 2.0])
        assert data["fov_y_degrees"] == pytest.approx(60.0)
        assert data["type"] == "perspective"
        assert data["confidence"] == pytest.approx(0.9)
        assert "summary" in data
        assert "Perspective" in data["summary"]

    def test_404_when_frame_missing(self):
        client = _make_client()
        resp = client.get("/api/v1/frames/9999/scene/camera", headers=AUTH_HEADERS)
        assert resp.status_code == 404

    def test_404_when_camera_not_extracted(self):
        client = _make_client(has_camera=False)
        resp = client.get("/api/v1/frames/1/scene/camera", headers=AUTH_HEADERS)
        assert resp.status_code == 404

    def test_401_without_auth(self):
        client = _make_client()
        resp = client.get("/api/v1/frames/1/scene/camera")
        assert resp.status_code == 401


# ---------------------------------------------------------------------------
# Tests: GET /frames/{frame_id}/scene/objects
# ---------------------------------------------------------------------------

class TestGetObjects:
    def test_200_with_object_list(self):
        client = _make_client()
        resp = client.get("/api/v1/frames/1/scene/objects", headers=AUTH_HEADERS)
        assert resp.status_code == 200
        data = resp.json()
        assert "objects" in data
        assert len(data["objects"]) == 1
        obj = data["objects"][0]
        assert obj["id"] == 0
        assert obj["draw_call_ids"] == [0, 1]
        assert len(obj["world_transform"]) == 16
        assert "bounding_box" in obj
        assert obj["bounding_box"]["min"] == pytest.approx([-1.0, -1.0, -1.0])
        assert obj["bounding_box"]["max"] == pytest.approx([1.0, 1.0, 1.0])
        assert obj["visible"] is True
        assert "reconstruction_quality" in data

    def test_404_when_frame_missing(self):
        client = _make_client()
        resp = client.get("/api/v1/frames/9999/scene/objects", headers=AUTH_HEADERS)
        assert resp.status_code == 404

    def test_401_without_auth(self):
        client = _make_client()
        resp = client.get("/api/v1/frames/1/scene/objects")
        assert resp.status_code == 401


# ---------------------------------------------------------------------------
# Tests: GET /frames/{frame_id}/scene  (full)
# ---------------------------------------------------------------------------

class TestGetScene:
    def test_200_full_scene(self):
        client = _make_client(quality="full")
        resp = client.get("/api/v1/frames/1/scene", headers=AUTH_HEADERS)
        assert resp.status_code == 200
        data = resp.json()
        assert data["reconstruction_quality"] == "full"
        assert "camera" in data
        assert data["camera"] is not None
        assert "objects" in data
        assert len(data["objects"]) == 1

    def test_200_raw_only_no_matrices(self):
        """Frame with no matrices returns reconstruction_quality='raw_only'."""
        client = _make_client(quality="raw_only", has_camera=False)
        resp = client.get("/api/v1/frames/1/scene", headers=AUTH_HEADERS)
        assert resp.status_code == 200
        data = resp.json()
        assert data["reconstruction_quality"] == "raw_only"
        assert data["camera"] is None

    def test_404_when_frame_missing(self):
        client = _make_client()
        resp = client.get("/api/v1/frames/9999/scene", headers=AUTH_HEADERS)
        assert resp.status_code == 404

    def test_401_without_auth(self):
        client = _make_client()
        resp = client.get("/api/v1/frames/1/scene")
        assert resp.status_code == 401
