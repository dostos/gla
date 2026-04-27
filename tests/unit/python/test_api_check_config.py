"""Tests for ``GET /api/v1/frames/{frame_id}/check-config``."""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from starlette.testclient import TestClient

from gpa.api.app import create_app
from gpa.backends.native import NativeBackend

from conftest import AUTH_HEADERS, AUTH_TOKEN, _make_drawcall, _make_overview


# --------------------------------------------------------------------------- #
# Custom fixtures: shape mock_query_engine to fire / suppress specific rules.
# --------------------------------------------------------------------------- #


def _build_app_with(qe: MagicMock):
    provider = NativeBackend(qe, engine=None)
    return TestClient(
        create_app(provider=provider, auth_token=AUTH_TOKEN),
        raise_server_exceptions=True,
    )


def _qe_for_state(*, draw_calls, clear_count=0, fb=(800, 600)):
    """Build a mock_query_engine that returns a specific frame state."""
    qe = MagicMock()
    fb_w, fb_h = fb
    ov = _make_overview(frame_id=1)
    ov.draw_call_count = len(draw_calls)
    ov.clear_count = clear_count
    ov.fb_width = fb_w
    ov.fb_height = fb_h
    qe.latest_frame_overview.return_value = ov
    qe.frame_overview.side_effect = lambda fid: ov if fid == 1 else None
    qe.list_draw_calls.side_effect = lambda fid, limit=50, offset=0: (
        list(draw_calls) if fid == 1 else []
    )
    qe.get_draw_call.side_effect = lambda fid, did: (
        draw_calls[did] if fid == 1 and did < len(draw_calls) else None
    )
    qe.get_pixel.return_value = None
    return qe


# --------------------------------------------------------------------------- #
# Empty / quiet frames
# --------------------------------------------------------------------------- #


class TestEndpointBasics:
    def test_unknown_frame_404(self, client):
        r = client.get(
            "/api/v1/frames/9999/check-config", headers=AUTH_HEADERS
        )
        assert r.status_code == 404

    def test_invalid_severity_400(self, client):
        r = client.get(
            "/api/v1/frames/1/check-config?severity=critical",
            headers=AUTH_HEADERS,
        )
        assert r.status_code == 400

    def test_unknown_rule_400(self, client):
        r = client.get(
            "/api/v1/frames/1/check-config?rule=does-not-exist",
            headers=AUTH_HEADERS,
        )
        assert r.status_code == 400
        assert "Unknown rule" in r.json()["detail"]

    def test_latest_alias_resolves(self, client):
        r = client.get(
            "/api/v1/frames/latest/check-config", headers=AUTH_HEADERS,
        )
        assert r.status_code == 200
        assert r.json()["frame_id"] == 1

    def test_response_shape(self, client):
        r = client.get(
            "/api/v1/frames/1/check-config?severity=info",
            headers=AUTH_HEADERS,
        )
        assert r.status_code == 200
        data = r.json()
        assert data["frame_id"] == 1
        assert isinstance(data["rules_evaluated"], list)
        assert isinstance(data["findings"], list)


# --------------------------------------------------------------------------- #
# Empty frame -> no findings
# --------------------------------------------------------------------------- #


class TestQuietFrame:
    def test_clean_frame_emits_no_findings(self):
        # A "clean" frame: clear was issued, viewport == fb, depth coherent.
        clean_dc = _make_drawcall(dc_id=0)
        # Override fields that auto-fixture set spicily.
        clean_dc.fbo_color_attachment_tex = 0
        clean_dc.fbo_color_attachments = [0] * 8
        clean_dc.params = []
        clean_dc.textures = []
        ps = clean_dc.pipeline
        ps.viewport = (0, 0, 800, 600)
        ps.depth_test = True
        ps.depth_write = True
        ps.blend_enabled = False

        qe = _qe_for_state(draw_calls=[clean_dc], clear_count=1)
        c = _build_app_with(qe)
        r = c.get(
            "/api/v1/frames/1/check-config?severity=warn",
            headers=AUTH_HEADERS,
        )
        assert r.status_code == 200
        assert r.json()["findings"] == []


# --------------------------------------------------------------------------- #
# Per-rule firings via crafted state
# --------------------------------------------------------------------------- #


def _make_minimal_dc(dc_id: int = 0):
    """A dc with no-op pipeline state; tests tweak fields they care about."""
    dc = _make_drawcall(dc_id=dc_id)
    dc.fbo_color_attachment_tex = 0
    dc.fbo_color_attachments = [0] * 8
    dc.params = []
    dc.textures = []
    return dc


class TestPerRuleFiring:
    def test_auto_clear_fires(self):
        dc = _make_minimal_dc()
        dc.pipeline.viewport = (0, 0, 800, 600)
        qe = _qe_for_state(draw_calls=[dc], clear_count=0)
        c = _build_app_with(qe)
        r = c.get(
            "/api/v1/frames/1/check-config?severity=info",
            headers=AUTH_HEADERS,
        )
        rules = [f["rule_id"] for f in r.json()["findings"]]
        assert "auto-clear-with-no-explicit-clear" in rules

    def test_depth_write_fires(self):
        dc = _make_minimal_dc()
        dc.pipeline.viewport = (0, 0, 800, 600)
        dc.pipeline.depth_test = False
        dc.pipeline.depth_write = True
        qe = _qe_for_state(draw_calls=[dc], clear_count=1)
        c = _build_app_with(qe)
        r = c.get(
            "/api/v1/frames/1/check-config?severity=info",
            headers=AUTH_HEADERS,
        )
        rules = [f["rule_id"] for f in r.json()["findings"]]
        assert "depth-write-without-depth-test" in rules

    def test_viewport_mismatch_fires_at_info(self):
        dc = _make_minimal_dc()
        dc.pipeline.viewport = (0, 0, 400, 300)  # smaller than 800x600
        qe = _qe_for_state(draw_calls=[dc], clear_count=1, fb=(800, 600))
        c = _build_app_with(qe)
        r = c.get(
            "/api/v1/frames/1/check-config?severity=info",
            headers=AUTH_HEADERS,
        )
        rules = [f["rule_id"] for f in r.json()["findings"]]
        assert "viewport-not-equal-framebuffer-size" in rules
        # And not present at warn level.
        r2 = c.get(
            "/api/v1/frames/1/check-config?severity=warn",
            headers=AUTH_HEADERS,
        )
        rules_warn = [f["rule_id"] for f in r2.json()["findings"]]
        assert "viewport-not-equal-framebuffer-size" not in rules_warn

    def test_color_space_mismatch_fires(self):
        dc = _make_minimal_dc()
        dc.pipeline.viewport = (0, 0, 800, 600)
        t1 = MagicMock(slot=0, texture_id=1, width=256, height=256, format="RGBA8")
        t2 = MagicMock(slot=1, texture_id=2, width=256, height=256, format="SRGB8_ALPHA8")
        dc.textures = [t1, t2]
        qe = _qe_for_state(draw_calls=[dc], clear_count=1)
        c = _build_app_with(qe)
        r = c.get(
            "/api/v1/frames/1/check-config?severity=warn",
            headers=AUTH_HEADERS,
        )
        rules = [f["rule_id"] for f in r.json()["findings"]]
        assert "color-space-encoding-mismatch" in rules

    def test_premult_alpha_incoherent_fires(self):
        a = _make_minimal_dc(dc_id=0)
        a.pipeline.viewport = (0, 0, 800, 600)
        a.pipeline.blend_enabled = True
        a.pipeline.blend_src = "ONE"
        a.pipeline.blend_dst = "ONE_MINUS_SRC_ALPHA"
        b = _make_minimal_dc(dc_id=1)
        b.pipeline.viewport = (0, 0, 800, 600)
        b.pipeline.blend_enabled = True
        b.pipeline.blend_src = "SRC_ALPHA"
        b.pipeline.blend_dst = "ONE_MINUS_SRC_ALPHA"
        qe = _qe_for_state(draw_calls=[a, b], clear_count=1)
        c = _build_app_with(qe)
        r = c.get(
            "/api/v1/frames/1/check-config?severity=warn",
            headers=AUTH_HEADERS,
        )
        rules = [f["rule_id"] for f in r.json()["findings"]]
        assert "premultiplied-alpha-incoherence" in rules

    def test_npot_fires(self):
        dc = _make_minimal_dc()
        dc.pipeline.viewport = (0, 0, 800, 600)
        dc.textures = [
            MagicMock(slot=0, texture_id=1, width=100, height=200, format="RGBA8"),
        ]
        qe = _qe_for_state(draw_calls=[dc], clear_count=1)
        c = _build_app_with(qe)
        r = c.get(
            "/api/v1/frames/1/check-config?severity=warn",
            headers=AUTH_HEADERS,
        )
        rules = [f["rule_id"] for f in r.json()["findings"]]
        assert "mipmap-on-npot-without-min-filter" in rules


# --------------------------------------------------------------------------- #
# Filter scoping
# --------------------------------------------------------------------------- #


class TestFiltering:
    def test_rule_filter_returns_only_requested(self):
        dc = _make_minimal_dc()
        dc.pipeline.viewport = (0, 0, 800, 600)
        dc.pipeline.depth_test = False
        dc.pipeline.depth_write = True
        qe = _qe_for_state(draw_calls=[dc], clear_count=0)
        c = _build_app_with(qe)
        r = c.get(
            "/api/v1/frames/1/check-config"
            "?rule=depth-write-without-depth-test&severity=info",
            headers=AUTH_HEADERS,
        )
        data = r.json()
        rules = [f["rule_id"] for f in data["findings"]]
        # Only the requested rule may fire.
        assert rules == ["depth-write-without-depth-test"]
        assert data["rules_evaluated"] == ["depth-write-without-depth-test"]

    def test_csv_rule_value_supported(self):
        dc = _make_minimal_dc()
        dc.pipeline.viewport = (0, 0, 800, 600)
        qe = _qe_for_state(draw_calls=[dc], clear_count=0)
        c = _build_app_with(qe)
        # Comma-separated within a single ?rule= param.
        r = c.get(
            "/api/v1/frames/1/check-config"
            "?rule=auto-clear-with-no-explicit-clear,depth-write-without-depth-test"
            "&severity=info",
            headers=AUTH_HEADERS,
        )
        assert r.status_code == 200
        evald = set(r.json()["rules_evaluated"])
        assert "auto-clear-with-no-explicit-clear" in evald
        assert "depth-write-without-depth-test" in evald


# --------------------------------------------------------------------------- #
# /check-config/rules listing endpoint
# --------------------------------------------------------------------------- #


class TestRulesListEndpoint:
    def test_lists_all_rules(self, client):
        r = client.get(
            "/api/v1/check-config/rules", headers=AUTH_HEADERS,
        )
        assert r.status_code == 200
        rules = r.json()["rules"]
        ids = {r["id"] for r in rules}
        assert "auto-clear-with-no-explicit-clear" in ids
        assert "unused-uniform-set" in ids
        assert len(ids) == 8
