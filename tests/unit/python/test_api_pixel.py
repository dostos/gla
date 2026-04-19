"""Tests for /api/v1/frames/{frame_id}/pixel/{x}/{y} endpoint."""
import pytest


class TestPixelQuery:
    def test_get_pixel_200(self, client, auth_headers):
        resp = client.get("/api/v1/frames/1/pixel/100/50", headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert data["x"] == 100
        assert data["y"] == 50
        assert data["r"] == 255
        assert data["g"] == 0
        assert data["b"] == 128
        assert data["a"] == 255
        assert data["depth"] == pytest.approx(0.5)
        assert data["stencil"] == 0

    def test_get_pixel_no_auth_401(self, client):
        resp = client.get("/api/v1/frames/1/pixel/100/50")
        assert resp.status_code == 401

    def test_get_pixel_out_of_bounds_404(self, client, auth_headers):
        # x=9000 is beyond framebuffer width of 800
        resp = client.get("/api/v1/frames/1/pixel/9000/50", headers=auth_headers)
        assert resp.status_code == 404

    def test_get_pixel_nonexistent_frame_404(self, client, auth_headers):
        resp = client.get("/api/v1/frames/9999/pixel/0/0", headers=auth_headers)
        assert resp.status_code == 404

    def test_get_pixel_negative_coords_404(self, client, auth_headers):
        # Negative coordinates are outside the framebuffer — mock returns None.
        resp = client.get("/api/v1/frames/1/pixel/-1/0", headers=auth_headers)
        assert resp.status_code == 404
