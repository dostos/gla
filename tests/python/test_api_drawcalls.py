"""Tests for /api/v1/frames/{frame_id}/drawcalls/* endpoints."""


class TestDrawCallList:
    def test_list_drawcalls_200(self, client, auth_headers):
        resp = client.get("/api/v1/frames/1/drawcalls", headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert data["frame_id"] == 1
        assert isinstance(data["items"], list)
        assert len(data["items"]) >= 1
        item = data["items"][0]
        assert "id" in item
        assert "primitive_type" in item

    def test_list_drawcalls_pagination(self, client, auth_headers):
        resp = client.get(
            "/api/v1/frames/1/drawcalls?limit=10&offset=0", headers=auth_headers
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["limit"] == 10
        assert data["offset"] == 0

    def test_list_drawcalls_nonexistent_frame_404(self, client, auth_headers):
        resp = client.get("/api/v1/frames/9999/drawcalls", headers=auth_headers)
        assert resp.status_code == 404


class TestDrawCallDetail:
    def test_get_drawcall_200(self, client, auth_headers):
        resp = client.get("/api/v1/frames/1/drawcalls/0", headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert data["id"] == 0
        assert data["primitive_type"] == "TRIANGLES"
        assert "pipeline_state" in data
        ps = data["pipeline_state"]
        assert "depth_test_enabled" in ps

    def test_get_nonexistent_drawcall_404(self, client, auth_headers):
        resp = client.get("/api/v1/frames/1/drawcalls/9999", headers=auth_headers)
        assert resp.status_code == 404

    def test_get_drawcall_wrong_frame_404(self, client, auth_headers):
        resp = client.get("/api/v1/frames/9999/drawcalls/0", headers=auth_headers)
        assert resp.status_code == 404


class TestDrawCallShader:
    def test_get_shader_200(self, client, auth_headers):
        resp = client.get(
            "/api/v1/frames/1/drawcalls/0/shader", headers=auth_headers
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["dc_id"] == 0
        assert data["shader_id"] == 7
        assert isinstance(data["parameters"], list)
        assert len(data["parameters"]) >= 1
        p = data["parameters"][0]
        assert p["name"] == "uColor"

    def test_get_shader_nonexistent_drawcall_404(self, client, auth_headers):
        resp = client.get(
            "/api/v1/frames/1/drawcalls/9999/shader", headers=auth_headers
        )
        assert resp.status_code == 404


class TestDrawCallTextures:
    def test_get_textures_200(self, client, auth_headers):
        resp = client.get(
            "/api/v1/frames/1/drawcalls/0/textures", headers=auth_headers
        )
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data["textures"], list)
        assert len(data["textures"]) >= 1
        tex = data["textures"][0]
        assert tex["slot"] == 0
        assert tex["texture_id"] == 3

    def test_get_textures_nonexistent_404(self, client, auth_headers):
        resp = client.get(
            "/api/v1/frames/1/drawcalls/9999/textures", headers=auth_headers
        )
        assert resp.status_code == 404


class TestDrawCallVertices:
    def test_get_vertices_200(self, client, auth_headers):
        resp = client.get(
            "/api/v1/frames/1/drawcalls/0/vertices", headers=auth_headers
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["vertex_count"] == 3
        assert data["primitive_type"] == "TRIANGLES"

    def test_get_vertices_nonexistent_404(self, client, auth_headers):
        resp = client.get(
            "/api/v1/frames/1/drawcalls/9999/vertices", headers=auth_headers
        )
        assert resp.status_code == 404
