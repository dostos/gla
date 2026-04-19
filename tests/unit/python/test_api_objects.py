"""Tests for object/passes/explain REST endpoints (Task 7)."""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from starlette.testclient import TestClient

from gla.api.app import create_app
from gla.backends.native import NativeBackend
from gla.framework.metadata_store import MetadataStore
from gla.framework.types import ObjectInfo, RenderPassInfo, MaterialInfo

AUTH_TOKEN = "test-token"
AUTH_HEADERS = {"Authorization": f"Bearer {AUTH_TOKEN}"}

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_OBJ = ObjectInfo(
    name="Cube",
    type="Mesh",
    parent="",
    draw_call_ids=[0],
    material="BasicMat",
    transform={"position": [0, 0, 0]},
    visible=True,
    properties={},
)

_PASS = RenderPassInfo(
    name="MainPass",
    draw_call_ids=[0, 1, 2],
    input=[],
    output="framebuffer",
)


def _make_mock_fqe():
    fqe = MagicMock()
    fqe.list_objects.return_value = [_OBJ]
    fqe.query_object.side_effect = lambda fid, name: _OBJ if name == "Cube" else None
    fqe.list_render_passes.return_value = [_PASS]
    fqe.explain_pixel.return_value = None  # overridden per test
    return fqe


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def fqe_client(mock_query_engine, mock_engine):
    """TestClient with a mock FrameworkQueryEngine."""
    provider = NativeBackend(mock_query_engine, engine=mock_engine)
    fqe = _make_mock_fqe()
    app = create_app(
        provider=provider,
        auth_token=AUTH_TOKEN,
        framework_query_engine=fqe,
    )
    return TestClient(app, raise_server_exceptions=True), fqe


# ---------------------------------------------------------------------------
# /objects
# ---------------------------------------------------------------------------

def test_list_objects_200(fqe_client):
    client, _ = fqe_client
    resp = client.get("/api/v1/frames/1/objects", headers=AUTH_HEADERS)
    assert resp.status_code == 200
    data = resp.json()
    assert data["frame_id"] == 1
    assert len(data["objects"]) == 1
    assert data["objects"][0]["name"] == "Cube"


def test_get_object_200(fqe_client):
    client, _ = fqe_client
    resp = client.get("/api/v1/frames/1/objects/Cube", headers=AUTH_HEADERS)
    assert resp.status_code == 200
    data = resp.json()
    assert data["name"] == "Cube"
    assert data["material"] == "BasicMat"


def test_get_object_404(fqe_client):
    client, _ = fqe_client
    resp = client.get("/api/v1/frames/1/objects/NonExistent", headers=AUTH_HEADERS)
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# /passes
# ---------------------------------------------------------------------------

def test_list_passes_200(fqe_client):
    client, _ = fqe_client
    resp = client.get("/api/v1/frames/1/passes", headers=AUTH_HEADERS)
    assert resp.status_code == 200
    data = resp.json()
    assert data["frame_id"] == 1
    assert len(data["passes"]) == 1
    assert data["passes"][0]["name"] == "MainPass"


def test_get_pass_200(fqe_client):
    client, _ = fqe_client
    resp = client.get("/api/v1/frames/1/passes/MainPass", headers=AUTH_HEADERS)
    assert resp.status_code == 200
    data = resp.json()
    assert data["name"] == "MainPass"
    assert data["draw_call_ids"] == [0, 1, 2]


def test_get_pass_404(fqe_client):
    client, _ = fqe_client
    resp = client.get("/api/v1/frames/1/passes/NoSuchPass", headers=AUTH_HEADERS)
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# /objects/at/{x}/{y}
# ---------------------------------------------------------------------------

def test_object_at_pixel_404_when_no_explanation(fqe_client):
    client, _ = fqe_client
    resp = client.get("/api/v1/frames/1/objects/at/100/200", headers=AUTH_HEADERS)
    assert resp.status_code == 404


def test_object_at_pixel_no_auth_401(fqe_client):
    client, _ = fqe_client
    resp = client.get("/api/v1/frames/1/objects/at/100/200")
    assert resp.status_code == 401
