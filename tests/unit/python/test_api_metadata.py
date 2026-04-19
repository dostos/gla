"""Tests for POST/GET /api/v1/frames/{frame_id}/metadata endpoints."""
import pytest
from starlette.testclient import TestClient

from gla.api.app import create_app
from gla.backends.native import NativeBackend
from gla.framework.metadata_store import MetadataStore


AUTH_TOKEN = "test-token"
AUTH_HEADERS = {"Authorization": f"Bearer {AUTH_TOKEN}"}

SAMPLE_METADATA = {
    "framework": "three.js",
    "version": "r155",
    "objects": [
        {
            "name": "Cube",
            "type": "Mesh",
            "draw_call_ids": [0],
        }
    ],
    "materials": [
        {
            "name": "BasicMat",
            "shader": "MeshBasicMaterial",
        }
    ],
    "render_passes": [
        {
            "name": "MainPass",
            "draw_call_range": [0, 5],
        }
    ],
}


@pytest.fixture
def metadata_store() -> MetadataStore:
    return MetadataStore()


@pytest.fixture
def meta_client(mock_query_engine, mock_engine, metadata_store) -> TestClient:
    """TestClient that includes a MetadataStore in app state."""
    provider = NativeBackend(mock_query_engine, engine=mock_engine)
    app = create_app(
        provider=provider,
        auth_token=AUTH_TOKEN,
        metadata_store=metadata_store,
    )
    return TestClient(app, raise_server_exceptions=True)


# ---------------------------------------------------------------------------
# Test cases
# ---------------------------------------------------------------------------


def test_post_metadata_200(meta_client):
    resp = meta_client.post(
        "/api/v1/frames/1/metadata",
        json=SAMPLE_METADATA,
        headers=AUTH_HEADERS,
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ok"
    assert data["frame_id"] == 1


def test_get_metadata_summary_200(meta_client):
    # First POST
    meta_client.post(
        "/api/v1/frames/1/metadata",
        json=SAMPLE_METADATA,
        headers=AUTH_HEADERS,
    )
    resp = meta_client.get("/api/v1/frames/1/metadata", headers=AUTH_HEADERS)
    assert resp.status_code == 200
    data = resp.json()
    assert data["frame_id"] == 1
    assert data["framework"] == "three.js"
    assert data["object_count"] == 1
    assert data["material_count"] == 1
    assert data["render_pass_count"] == 1


def test_get_nonexistent_metadata_404(meta_client):
    resp = meta_client.get("/api/v1/frames/9999/metadata", headers=AUTH_HEADERS)
    assert resp.status_code == 404


def test_post_metadata_without_auth_401(meta_client):
    resp = meta_client.post(
        "/api/v1/frames/1/metadata",
        json=SAMPLE_METADATA,
        # No Authorization header
    )
    assert resp.status_code == 401
