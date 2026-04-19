"""Tests for /api/v1/frames/{frame_id}/scene/* endpoints.

Scene endpoints require Tier 3 framework metadata.  Without a
FrameworkQueryEngine on app.state, all scene routes return 404.
"""
import pytest
from unittest.mock import MagicMock
from starlette.testclient import TestClient

from gla.api.app import create_app
from gla.backends.native import NativeBackend

AUTH_TOKEN = "test-token"
AUTH_HEADERS = {"Authorization": f"Bearer {AUTH_TOKEN}"}


def _make_client_no_fqe() -> TestClient:
    """Client with no FrameworkQueryEngine — scene routes should return 404."""
    qe = MagicMock()
    qe.frame_overview.return_value = MagicMock(frame_id=1)
    provider = NativeBackend(qe)
    app = create_app(provider=provider, auth_token=AUTH_TOKEN)
    return TestClient(app, raise_server_exceptions=True)


def _make_client_with_fqe(scene_info=None) -> TestClient:
    """Client with a mock FrameworkQueryEngine that returns scene_info."""
    qe = MagicMock()
    provider = NativeBackend(qe)
    app = create_app(provider=provider, auth_token=AUTH_TOKEN)

    fqe = MagicMock()
    fqe.get_scene.return_value = scene_info
    app.state.framework_query_engine = fqe

    return TestClient(app, raise_server_exceptions=True)


def _make_scene(camera=None, objects=None):
    scene = MagicMock()
    scene.camera = camera
    scene.objects = objects or []
    return scene


# ---------------------------------------------------------------------------
# No framework metadata — all scene routes return 404
# ---------------------------------------------------------------------------

class TestSceneNoFrameworkMetadata:
    def test_scene_returns_404(self):
        client = _make_client_no_fqe()
        resp = client.get("/api/v1/frames/1/scene", headers=AUTH_HEADERS)
        assert resp.status_code == 404
        assert "framework metadata" in resp.json()["detail"].lower()

    def test_camera_returns_404(self):
        client = _make_client_no_fqe()
        resp = client.get("/api/v1/frames/1/scene/camera", headers=AUTH_HEADERS)
        assert resp.status_code == 404

    def test_objects_returns_404(self):
        client = _make_client_no_fqe()
        resp = client.get("/api/v1/frames/1/scene/objects", headers=AUTH_HEADERS)
        assert resp.status_code == 404

    def test_scene_requires_auth(self):
        client = _make_client_no_fqe()
        resp = client.get("/api/v1/frames/1/scene")
        assert resp.status_code == 401

    def test_camera_requires_auth(self):
        client = _make_client_no_fqe()
        resp = client.get("/api/v1/frames/1/scene/camera")
        assert resp.status_code == 401

    def test_objects_requires_auth(self):
        client = _make_client_no_fqe()
        resp = client.get("/api/v1/frames/1/scene/objects")
        assert resp.status_code == 401


# ---------------------------------------------------------------------------
# With FrameworkQueryEngine — scene routes return data
# ---------------------------------------------------------------------------

class TestSceneWithFrameworkMetadata:
    def test_scene_returns_camera_and_objects(self):
        camera = {"position": [1.0, 2.0, 3.0], "type": "perspective"}
        obj = {"id": 0, "name": "Cube"}
        scene = _make_scene(camera=camera, objects=[obj])
        client = _make_client_with_fqe(scene_info=scene)
        resp = client.get("/api/v1/frames/1/scene", headers=AUTH_HEADERS)
        assert resp.status_code == 200
        data = resp.json()
        assert data["camera"]["type"] == "perspective"
        assert len(data["objects"]) == 1

    def test_camera_returns_camera_dict(self):
        camera = {"position": [0.0, 0.0, 5.0], "type": "perspective"}
        scene = _make_scene(camera=camera)
        client = _make_client_with_fqe(scene_info=scene)
        resp = client.get("/api/v1/frames/1/scene/camera", headers=AUTH_HEADERS)
        assert resp.status_code == 200
        assert resp.json()["type"] == "perspective"

    def test_camera_404_when_camera_is_none(self):
        scene = _make_scene(camera=None)
        client = _make_client_with_fqe(scene_info=scene)
        resp = client.get("/api/v1/frames/1/scene/camera", headers=AUTH_HEADERS)
        assert resp.status_code == 404

    def test_objects_returns_object_list(self):
        objects = [{"id": 0, "name": "Cube"}, {"id": 1, "name": "Sphere"}]
        scene = _make_scene(objects=objects)
        client = _make_client_with_fqe(scene_info=scene)
        resp = client.get("/api/v1/frames/1/scene/objects", headers=AUTH_HEADERS)
        assert resp.status_code == 200
        assert len(resp.json()["objects"]) == 2

    def test_scene_returns_404_when_fqe_returns_none(self):
        client = _make_client_with_fqe(scene_info=None)
        resp = client.get("/api/v1/frames/1/scene", headers=AUTH_HEADERS)
        assert resp.status_code == 404
