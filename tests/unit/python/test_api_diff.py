"""Tests for GET /api/v1/diff/{frame_a}/{frame_b}."""
import pytest


class TestFrameDiff:
    def test_diff_summary_200(self, client, auth_headers):
        """GET /diff/1/2 returns 200 with summary fields."""
        resp = client.get("/api/v1/diff/1/2", headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()

        assert data["frame_id_a"] == 1
        assert data["frame_id_b"] == 2

        summary = data["summary"]
        assert summary["draw_calls_added"]    == 1
        assert summary["draw_calls_removed"]  == 0
        assert summary["draw_calls_modified"] == 2
        assert summary["draw_calls_unchanged"]== 5
        assert summary["pixels_changed"]      == 1234

        # Default depth=summary → detail lists are empty
        assert data["draw_call_diffs"] == []
        assert data["pixel_diffs"]     == []

    def test_diff_404_unknown_frame(self, client, auth_headers):
        """GET /diff/1/999 returns 404 when a frame is not found."""
        resp = client.get("/api/v1/diff/1/999", headers=auth_headers)
        assert resp.status_code == 404

    def test_diff_no_auth_401(self, client):
        """GET /diff/1/2 without auth returns 401."""
        resp = client.get("/api/v1/diff/1/2")
        assert resp.status_code == 401

    def test_diff_invalid_depth_400(self, client, auth_headers):
        """GET /diff/1/2?depth=invalid returns 400."""
        resp = client.get("/api/v1/diff/1/2?depth=invalid", headers=auth_headers)
        assert resp.status_code == 400

    def test_diff_drawcalls_depth_200(self, client, auth_headers):
        """GET /diff/1/2?depth=drawcalls returns 200."""
        resp = client.get("/api/v1/diff/1/2?depth=drawcalls", headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert "summary" in data
        assert "draw_call_diffs" in data

    def test_diff_pixels_depth_200(self, client, auth_headers):
        """GET /diff/1/2?depth=pixels returns 200."""
        resp = client.get("/api/v1/diff/1/2?depth=pixels", headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert "pixel_diffs" in data
