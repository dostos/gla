"""Tests for ``GET /api/v1/frames`` — the frame-id list endpoint.

The native backend probes backwards from the latest overview to enumerate
the in-engine ring buffer.  Empty session → empty list.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from starlette.testclient import TestClient

from gpa.api.app import create_app
from gpa.backends.native import NativeBackend

from conftest import AUTH_HEADERS, AUTH_TOKEN, _make_overview


def _build_client_with(qe: MagicMock) -> TestClient:
    provider = NativeBackend(qe, engine=None)
    return TestClient(
        create_app(provider=provider, auth_token=AUTH_TOKEN),
        raise_server_exceptions=True,
    )


class TestFramesListEndpoint:
    def test_default_fixture_lists_one_frame(self, client):
        """The default conftest fixture has frame 1 (and only frame 1)."""
        resp = client.get("/api/v1/frames", headers=AUTH_HEADERS)
        assert resp.status_code == 200
        data = resp.json()
        assert data["frames"] == [1]
        assert data["count"] == 1

    def test_no_auth_401(self, client):
        resp = client.get("/api/v1/frames")
        assert resp.status_code == 401

    def test_empty_session_returns_empty_list(self):
        """When the engine has captured nothing, return ``{frames: []}``."""
        qe = MagicMock()
        qe.latest_frame_overview.return_value = None
        qe.frame_overview.side_effect = lambda fid: None

        tc = _build_client_with(qe)
        resp = tc.get("/api/v1/frames", headers=AUTH_HEADERS)
        assert resp.status_code == 200
        data = resp.json()
        assert data["frames"] == []
        assert data["count"] == 0

    def test_multiple_frames_listed_in_order(self):
        """Frames 0..3 captured → endpoint returns sorted ints."""
        qe = MagicMock()
        ov = _make_overview(frame_id=3)
        ov.draw_call_count = 0
        qe.latest_frame_overview.return_value = ov
        valid = {0, 1, 2, 3}
        def _get_overview(fid):
            if fid in valid:
                return _make_overview(frame_id=fid)
            return None
        qe.frame_overview.side_effect = _get_overview

        tc = _build_client_with(qe)
        resp = tc.get("/api/v1/frames", headers=AUTH_HEADERS)
        assert resp.status_code == 200
        data = resp.json()
        assert data["frames"] == [0, 1, 2, 3]
        assert data["count"] == 4

    def test_frames_list_stops_at_first_gap(self):
        """Probe backwards stops at the oldest contiguous frame.

        If frames 5,6,7 exist but 4 was evicted, only 5..7 should be
        returned (probing terminates on the first None).
        """
        qe = MagicMock()
        ov = _make_overview(frame_id=7)
        qe.latest_frame_overview.return_value = ov

        def _get_overview(fid):
            if fid in {5, 6, 7}:
                return _make_overview(frame_id=fid)
            return None
        qe.frame_overview.side_effect = _get_overview

        tc = _build_client_with(qe)
        resp = tc.get("/api/v1/frames", headers=AUTH_HEADERS)
        assert resp.status_code == 200
        data = resp.json()
        assert data["frames"] == [5, 6, 7]
        assert data["count"] == 3

    def test_backend_not_implemented_returns_empty(self):
        """A backend that raises NotImplementedError should yield ``[]`` (not 500)."""
        from gpa.backends.base import FrameProvider, FrameOverview

        class BareBackend(FrameProvider):
            def get_latest_overview(self):
                return FrameOverview(
                    frame_id=0, draw_call_count=0, clear_count=0,
                    fb_width=0, fb_height=0, timestamp=0.0,
                )

            def get_frame_overview(self, frame_id):
                return None

            def list_frame_ids(self):
                raise NotImplementedError

            def list_draw_calls(self, frame_id, limit=50, offset=0):
                return []

            def get_draw_call(self, frame_id, dc_id):
                return None

            def get_pixel(self, frame_id, x, y):
                return None

            def compare_frames(self, a, b, depth="summary"):
                return None

        provider = BareBackend()
        app = create_app(provider=provider, auth_token=AUTH_TOKEN)
        tc = TestClient(app, raise_server_exceptions=True)
        resp = tc.get("/api/v1/frames", headers=AUTH_HEADERS)
        assert resp.status_code == 200
        data = resp.json()
        assert data["frames"] == []
        assert data["count"] == 0
