"""Tests for /api/v1/frames/* endpoints."""
import pytest


class TestCurrentFrameOverview:
    def test_get_current_overview_200(self, client, auth_headers):
        resp = client.get("/api/v1/frames/current/overview", headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert data["frame_id"] == 1
        assert data["draw_call_count"] == 42
        assert data["framebuffer_width"] == 800
        assert data["framebuffer_height"] == 600
        assert data["timestamp"] == pytest.approx(1234.5)
        assert "clear_count" in data
        assert data["clear_count"] == 0

    def test_get_current_overview_no_auth_401(self, client):
        resp = client.get("/api/v1/frames/current/overview")
        assert resp.status_code == 401

    def test_get_current_overview_wrong_token_401(self, client):
        resp = client.get(
            "/api/v1/frames/current/overview",
            headers={"Authorization": "Bearer wrong-token"},
        )
        assert resp.status_code == 401


class TestFrameOverviewById:
    def test_get_existing_frame_overview_200(self, client, auth_headers):
        resp = client.get("/api/v1/frames/1/overview", headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert data["frame_id"] == 1

    def test_get_nonexistent_frame_overview_404(self, client, auth_headers):
        resp = client.get("/api/v1/frames/9999/overview", headers=auth_headers)
        assert resp.status_code == 404

    def test_overview_no_auth_401(self, client):
        resp = client.get("/api/v1/frames/1/overview")
        assert resp.status_code == 401


