"""Integration test: POST metadata → query objects/passes/materials/explain."""

import pytest
from fastapi.testclient import TestClient
from gpa.api.app import create_app
from gpa.backends.base import FrameProvider, FrameOverview, DrawCallInfo, PixelResult
from gpa.framework.metadata_store import MetadataStore


# ---------------------------------------------------------------------------
# Mock provider that returns realistic frame data
# ---------------------------------------------------------------------------

class MockProvider(FrameProvider):
    @property
    def backend_name(self):
        return "mock"

    def get_latest_overview(self):
        return self.get_frame_overview(0)

    def get_frame_overview(self, frame_id):
        return FrameOverview(
            frame_id=0,
            draw_call_count=3,
            fb_width=800,
            fb_height=600,
            timestamp=1.0,
        )

    def list_draw_calls(self, frame_id, limit=50, offset=0):
        # DrawCallInfo does not have debug_group_path; the debug-group
        # tree builder handles this gracefully via getattr default.
        return [
            DrawCallInfo(
                id=0,
                primitive_type=4,
                vertex_count=36,
                index_count=0,
                instance_count=1,
                shader_id=3,
                pipeline_state={"depth_test_enabled": True},
                params=[{"name": "uModelMatrix", "type": "mat4", "data": "..."}],
                textures=[],
            ),
            DrawCallInfo(
                id=1,
                primitive_type=4,
                vertex_count=24,
                index_count=0,
                instance_count=1,
                shader_id=3,
                pipeline_state={"depth_test_enabled": True},
                params=[],
                textures=[],
            ),
            DrawCallInfo(
                id=2,
                primitive_type=4,
                vertex_count=6,
                index_count=0,
                instance_count=1,
                shader_id=5,
                pipeline_state={},
                params=[],
                textures=[],
            ),
        ]

    def get_draw_call(self, frame_id, dc_id):
        dcs = self.list_draw_calls(frame_id)
        return dcs[dc_id] if dc_id < len(dcs) else None

    def get_pixel(self, frame_id, x, y):
        return PixelResult(r=200, g=50, b=30, a=255, depth=0.45, stencil=0)

    def get_scene(self, frame_id):
        return None

    def compare_frames(self, frame_a, frame_b, depth="summary"):
        return None


# ---------------------------------------------------------------------------
# Sample metadata payload
# ---------------------------------------------------------------------------

SAMPLE_METADATA = {
    "framework": "threejs",
    "version": "165",
    "objects": [
        {
            "name": "Player",
            "type": "Mesh",
            "parent": "World/Characters",
            "draw_call_ids": [0],
            "transform": {"position": [5, 0, 3], "rotation": [0, 45, 0], "scale": [1, 1, 1]},
            "visible": True,
        },
        {
            "name": "Environment",
            "type": "Mesh",
            "parent": "World",
            "draw_call_ids": [1],
            "transform": {"position": [0, 0, 0]},
            "visible": True,
        },
    ],
    "materials": [
        {
            "name": "PBR_Metal",
            "shader": "MeshStandardMaterial",
            "used_by": ["Player"],
            "properties": {"color": [0.8, 0.2, 0.1], "metallic": 0.9, "roughness": 0.3},
            "textures": {"map": "player_diffuse.png", "normalMap": "player_normal.png"},
        },
        {
            "name": "Ground",
            "shader": "MeshLambertMaterial",
            "used_by": ["Environment"],
            "properties": {"color": [0.3, 0.5, 0.2]},
            "textures": {},
        },
    ],
    "render_passes": [
        {
            "name": "GBuffer",
            "draw_call_range": [0, 1],
            "output": ["color", "normal", "depth"],
            "input": [],
        },
        {
            "name": "PostFX",
            "draw_call_range": [2, 2],
            "output": "screen",
            "input": ["color"],
        },
    ],
}


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def integration_client():
    provider = MockProvider()
    metadata_store = MetadataStore()
    app = create_app(provider=provider, auth_token="test", metadata_store=metadata_store)
    return TestClient(app)


@pytest.fixture
def auth():
    return {"Authorization": "Bearer test"}


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestFrameworkIntegration:
    """End-to-end: POST metadata → query objects → query passes → explain pixel."""

    def test_post_metadata_then_list_objects(self, integration_client, auth):
        # POST metadata
        r = integration_client.post(
            "/api/v1/frames/0/metadata", json=SAMPLE_METADATA, headers=auth
        )
        assert r.status_code == 200

        # Query objects
        r = integration_client.get("/api/v1/frames/0/objects", headers=auth)
        assert r.status_code == 200
        data = r.json()
        assert len(data["objects"]) == 2
        names = [o["name"] for o in data["objects"]]
        assert "Player" in names
        assert "Environment" in names

    def test_query_specific_object(self, integration_client, auth):
        integration_client.post(
            "/api/v1/frames/0/metadata", json=SAMPLE_METADATA, headers=auth
        )

        r = integration_client.get("/api/v1/frames/0/objects/Player", headers=auth)
        assert r.status_code == 200
        obj = r.json()
        assert obj["name"] == "Player"
        assert obj["type"] == "Mesh"
        assert obj["material"] == "PBR_Metal"
        assert obj["draw_call_ids"] == [0]

    def test_query_nonexistent_object(self, integration_client, auth):
        integration_client.post(
            "/api/v1/frames/0/metadata", json=SAMPLE_METADATA, headers=auth
        )
        r = integration_client.get("/api/v1/frames/0/objects/DoesNotExist", headers=auth)
        assert r.status_code == 404

    def test_list_render_passes(self, integration_client, auth):
        integration_client.post(
            "/api/v1/frames/0/metadata", json=SAMPLE_METADATA, headers=auth
        )

        r = integration_client.get("/api/v1/frames/0/passes", headers=auth)
        assert r.status_code == 200
        data = r.json()
        names = [p["name"] for p in data["passes"]]
        assert "GBuffer" in names
        assert "PostFX" in names

    def test_query_specific_pass(self, integration_client, auth):
        integration_client.post(
            "/api/v1/frames/0/metadata", json=SAMPLE_METADATA, headers=auth
        )

        r = integration_client.get("/api/v1/frames/0/passes/GBuffer", headers=auth)
        assert r.status_code == 200
        data = r.json()
        assert data["name"] == "GBuffer"
        # GBuffer covers draw call range [0, 1]
        assert 0 in data["draw_call_ids"]
        assert 1 in data["draw_call_ids"]

    def test_metadata_summary(self, integration_client, auth):
        integration_client.post(
            "/api/v1/frames/0/metadata", json=SAMPLE_METADATA, headers=auth
        )

        r = integration_client.get("/api/v1/frames/0/metadata", headers=auth)
        assert r.status_code == 200
        data = r.json()
        assert data["object_count"] == 2
        assert data["material_count"] == 2
        assert data["render_pass_count"] == 2

    def test_no_metadata_degrades_gracefully(self, integration_client, auth):
        # Query without posting metadata — should still work, returning empty objects
        r = integration_client.get("/api/v1/frames/0/objects", headers=auth)
        assert r.status_code == 200
        data = r.json()
        assert data["objects"] == []  # no metadata → no named objects

    def test_render_passes_from_debug_groups(self, integration_client, auth):
        # Without metadata, render passes fall back to the debug-group tree.
        # DrawCallInfo has no debug_group_path, so the tree has no named groups
        # and list_render_passes returns an empty list — which is still a valid
        # 200 response (graceful degradation).
        r = integration_client.get("/api/v1/frames/0/passes", headers=auth)
        assert r.status_code == 200
        data = r.json()
        # With no debug group paths, no pass groups are synthesised.
        assert isinstance(data["passes"], list)

    def test_metadata_missing_frame_returns_404(self, integration_client, auth):
        # GET metadata for a frame that has never had metadata posted returns 404.
        r = integration_client.get("/api/v1/frames/99/metadata", headers=auth)
        assert r.status_code == 404

    def test_post_metadata_overwrite(self, integration_client, auth):
        # POSTing metadata a second time for the same frame replaces the first.
        integration_client.post(
            "/api/v1/frames/0/metadata", json=SAMPLE_METADATA, headers=auth
        )
        slim_metadata = {
            "framework": "threejs",
            "version": "166",
            "objects": [SAMPLE_METADATA["objects"][0]],
            "materials": [SAMPLE_METADATA["materials"][0]],
            "render_passes": [],
        }
        integration_client.post(
            "/api/v1/frames/0/metadata", json=slim_metadata, headers=auth
        )

        r = integration_client.get("/api/v1/frames/0/metadata", headers=auth)
        assert r.status_code == 200
        data = r.json()
        assert data["object_count"] == 1
        assert data["render_pass_count"] == 0
