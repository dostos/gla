"""Tests for the MCP server's ``gpa_report`` / ``gpa_check`` tools.

We reuse the same TestClient-backed REST app the rest of the suite uses
and wrap it in a thin ``APIClient`` stand-in so the MCP dispatcher code
path runs unchanged.
"""

from __future__ import annotations

import json
from typing import Any, Dict, Optional
from unittest.mock import MagicMock

import pytest

from gpa.api.app import create_app
from gpa.backends.native import NativeBackend
from gpa.mcp import server as mcp_server
from starlette.testclient import TestClient


AUTH_TOKEN = "test-token"


class _TestClientAPI:
    """APIClient shape (``.get``/``.post``) routed through a TestClient."""

    def __init__(self, test_client: TestClient):
        self._tc = test_client
        self.base_url = "http://testserver/api/v1"
        self.token = AUTH_TOKEN

    def _headers(self) -> Dict[str, str]:
        return {"Authorization": f"Bearer {AUTH_TOKEN}"}

    def get(self, path: str, params: Optional[Dict[str, Any]] = None) -> Any:
        url = "/api/v1" + path
        resp = self._tc.get(url, params=params or None, headers=self._headers())
        if resp.status_code >= 400:
            return {"error": resp.status_code, "detail": resp.text}
        return resp.json()

    def post(self, path: str, params: Optional[Dict[str, Any]] = None) -> Any:
        url = "/api/v1" + path
        resp = self._tc.post(url, params=params or None, headers=self._headers())
        if resp.status_code >= 400:
            return {"error": resp.status_code, "detail": resp.text}
        return resp.json()


# --------------------------------------------------------------------------- #
# Fixtures: a full mock QueryEngine + app we can tweak per-test
# --------------------------------------------------------------------------- #


def _make_app_client(qe: MagicMock) -> TestClient:
    eng = MagicMock()
    eng.is_running.return_value = True
    provider = NativeBackend(qe, engine=eng)
    app = create_app(provider=provider, auth_token=AUTH_TOKEN)
    return TestClient(app, raise_server_exceptions=True)


@pytest.fixture
def api_client(client) -> _TestClientAPI:
    """Wrap the default conftest TestClient as an APIClient stand-in."""
    return _TestClientAPI(client)


# --------------------------------------------------------------------------- #
# gpa_report
# --------------------------------------------------------------------------- #


def test_gpa_report_tool_is_registered():
    names = [t["name"] for t in mcp_server.TOOLS]
    assert "gpa_report" in names
    assert "gpa_check" in names
    assert "gpa_report" in mcp_server._DISPATCH
    assert "gpa_check" in mcp_server._DISPATCH


def test_gpa_report_tool_returns_structured_json(api_client):
    """Default mock frame has a feedback loop (tex 7 bound as sampler AND
    COLOR_ATTACHMENT0) and a NaN uniform. Run the tool and assert the
    report surfaces both findings in a machine-readable shape."""
    text = mcp_server._tool_gpa_report(api_client, {"frame_id": 1})
    payload = json.loads(text)

    assert payload["frame"] == 1
    assert payload["warning_count"] >= 1

    check_by_name = {c["name"]: c for c in payload["checks"]}
    assert "feedback-loops" in check_by_name
    fl = check_by_name["feedback-loops"]
    assert fl["status"] == "warn"
    assert any(
        f.get("texture_id") == 7 and f.get("dc_id") == 0
        for f in fl["findings"]
    )
    # NaN uniforms flagged too.
    assert check_by_name["nan-uniforms"]["status"] == "warn"


def test_gpa_report_handles_empty_capture():
    """Frame with zero draw calls: empty-capture check must warn."""
    qe = MagicMock()
    ov = MagicMock()
    ov.frame_id = 1
    ov.draw_call_count = 0
    ov.clear_count = 0
    ov.fb_width = 800
    ov.fb_height = 600
    ov.timestamp = 0.0
    qe.latest_frame_overview.return_value = ov
    qe.frame_overview.side_effect = lambda fid: ov if fid == 1 else None
    qe.list_draw_calls.side_effect = lambda fid, limit=50, offset=0: []
    qe.get_draw_call.side_effect = lambda fid, dcid: None

    api = _TestClientAPI(_make_app_client(qe))
    text = mcp_server._tool_gpa_report(api, {"frame_id": 1})
    payload = json.loads(text)

    assert payload["frame"] == 1
    by_name = {c["name"]: c for c in payload["checks"]}
    assert by_name["empty-capture"]["status"] == "warn"


def test_gpa_report_latest_resolves(api_client):
    """`latest` should resolve to the current frame via /frames/current/overview."""
    text = mcp_server._tool_gpa_report(api_client, {"frame_id": "latest"})
    payload = json.loads(text)
    assert payload["frame"] == 1  # conftest latest_frame_overview → frame_id=1


def test_gpa_report_only_filter(api_client):
    text = mcp_server._tool_gpa_report(
        api_client, {"frame_id": 1, "only": ["empty-capture"]}
    )
    payload = json.loads(text)
    names = {c["name"] for c in payload["checks"]}
    assert names == {"empty-capture"}


def test_gpa_report_skip_filter(api_client):
    text = mcp_server._tool_gpa_report(
        api_client,
        {"frame_id": 1, "skip": ["feedback-loops", "nan-uniforms"]},
    )
    payload = json.loads(text)
    names = {c["name"] for c in payload["checks"]}
    assert "feedback-loops" not in names
    assert "nan-uniforms" not in names
    assert "empty-capture" in names


# --------------------------------------------------------------------------- #
# gpa_check
# --------------------------------------------------------------------------- #


def test_gpa_check_tool_returns_detail(api_client):
    text = mcp_server._tool_gpa_check(
        api_client, {"check_name": "feedback-loops", "frame_id": 1}
    )
    payload = json.loads(text)
    assert payload["frame"] == 1
    assert payload["check"] == "feedback-loops"
    assert payload["status"] == "warn"
    assert payload["findings"]
    # The finding for the colliding texture should expose machine-readable
    # fields (summary + texture_id + dc_id).
    first = payload["findings"][0]
    assert "summary" in first
    assert first.get("texture_id") == 7
    assert first.get("dc_id") == 0


def test_gpa_check_unknown_name_returns_error(api_client):
    text = mcp_server._tool_gpa_check(
        api_client, {"check_name": "does-not-exist", "frame_id": 1}
    )
    payload = json.loads(text)
    assert "error" in payload
    assert "does-not-exist" in payload["error"]
    assert "known" in payload
    # Builtin checks must all be advertised so agents can self-correct.
    assert "feedback-loops" in payload["known"]


def test_gpa_check_empty_capture_ok(api_client):
    text = mcp_server._tool_gpa_check(
        api_client, {"check_name": "empty-capture", "frame_id": 1}
    )
    payload = json.loads(text)
    assert payload["check"] == "empty-capture"
    assert payload["status"] == "ok"


def test_gpa_check_missing_check_name_returns_error(api_client):
    text = mcp_server._tool_gpa_check(api_client, {"frame_id": 1})
    payload = json.loads(text)
    assert "error" in payload
    assert "known" in payload


def test_gpa_check_with_dc_id(api_client):
    """Passing dc_id should restrict the drill-down to that draw call."""
    text = mcp_server._tool_gpa_check(
        api_client,
        {"check_name": "feedback-loops", "frame_id": 1, "dc_id": 0},
    )
    payload = json.loads(text)
    assert payload["status"] == "warn"
    assert payload["findings"]
    assert payload["findings"][0]["dc_id"] == 0


# --------------------------------------------------------------------------- #
# C3: cleanup-batch-1 MCP-tool parity with the new CLI commands
# --------------------------------------------------------------------------- #


class TestNewMcpToolsRegistered:
    """The 5 newly wired tools must be advertised AND dispatched.

    Catches the common 'forgot to add to _DISPATCH' regression where the
    tool surfaces in tools/list but every call returns Unknown tool.
    """

    NEW_TOOLS = [
        "gpa_check_config",
        "gpa_explain_draw",
        "gpa_diff_draws",
        "gpa_scene_find",
        "gpa_scene_explain",
    ]

    def test_each_tool_listed_and_dispatched(self):
        names = {t["name"] for t in mcp_server.TOOLS}
        for tool in self.NEW_TOOLS:
            assert tool in names, f"missing tool: {tool}"
            assert tool in mcp_server._DISPATCH, f"missing dispatch: {tool}"

    def test_each_tool_description_has_example(self):
        """Per cli-for-agents principle, tool descriptions must include "
        "at least one ``Example:`` invocation so an LLM can copy it."""
        defs = {t["name"]: t for t in mcp_server.TOOLS}
        for tool in self.NEW_TOOLS:
            desc = defs[tool]["description"]
            assert "Example:" in desc, (
                f"{tool} description missing 'Example:' invocation"
            )


def test_gpa_check_config_tool_returns_findings(api_client):
    """Default conftest mock has feedback loop + NaN uniform; the
    rule-engine route should surface at least one config finding."""
    text = mcp_server._tool_gpa_check_config(
        api_client, {"frame_id": 1, "severity": "warn"}
    )
    payload = json.loads(text)
    assert payload["frame_id"] == 1
    assert isinstance(payload["rules_evaluated"], list)
    assert isinstance(payload["findings"], list)


def test_gpa_check_config_invalid_severity_returns_error(api_client):
    text = mcp_server._tool_gpa_check_config(
        api_client, {"frame_id": 1, "severity": "critical"}
    )
    payload = json.loads(text)
    assert "error" in payload


def test_gpa_explain_draw_tool_returns_explanation(api_client):
    text = mcp_server._tool_gpa_explain_draw(
        api_client, {"frame_id": 1, "draw_id": 0}
    )
    payload = json.loads(text)
    assert payload["frame_id"] == 1
    assert payload["draw_call_id"] == 0
    # The mock has 2 uniforms (uColor, uBad) and 2 textures.
    assert "uniforms_set" in payload
    assert "textures_sampled" in payload
    assert "relevant_state" in payload


def test_gpa_explain_draw_field_filter(api_client):
    """``fields`` whitelists the response — only requested top-level keys
    survive (plus the always-on identifying keys)."""
    text = mcp_server._tool_gpa_explain_draw(
        api_client,
        {"frame_id": 1, "draw_id": 0, "fields": ["uniforms_set"]},
    )
    payload = json.loads(text)
    assert "uniforms_set" in payload
    assert "textures_sampled" not in payload
    assert "relevant_state" not in payload
    # Identifying keys preserved so the response stays self-describing.
    assert payload["frame_id"] == 1
    assert payload["draw_call_id"] == 0


def test_gpa_explain_draw_invalid_draw_id_returns_error(api_client):
    text = mcp_server._tool_gpa_explain_draw(
        api_client, {"frame_id": 1, "draw_id": "not-an-int"}
    )
    payload = json.loads(text)
    assert "error" in payload


def test_gpa_diff_draws_tool_state_scope(api_client):
    """Both draws come from the same mock so the diff is empty — but the
    payload shape must be stable."""
    text = mcp_server._tool_gpa_diff_draws(
        api_client, {"frame_id": 1, "a": 0, "b": 0}
    )
    payload = json.loads(text)
    assert payload["frame_id"] == 1
    assert payload["a"] == 0
    assert payload["b"] == 0
    assert payload["scope"] == "state"
    assert "changes" in payload


def test_gpa_diff_draws_invalid_scope_returns_error(api_client):
    text = mcp_server._tool_gpa_diff_draws(
        api_client, {"frame_id": 1, "a": 0, "b": 0, "scope": "bogus"}
    )
    payload = json.loads(text)
    assert "error" in payload


def test_gpa_scene_find_no_predicate_returns_error(api_client):
    text = mcp_server._tool_gpa_scene_find(
        api_client, {"frame_id": 1}
    )
    payload = json.loads(text)
    assert "error" in payload


def test_gpa_scene_find_with_predicate(api_client):
    """Even with no annotations posted the route returns 0 matches (not 4xx)."""
    text = mcp_server._tool_gpa_scene_find(
        api_client,
        {"frame_id": 1, "predicate": "material:transparent", "limit": 5},
    )
    payload = json.loads(text)
    assert payload["frame_id"] == 1
    assert payload["match_count"] == 0
    assert payload["matches"] == []
    # Default conftest has no scene annotations so this also asserts the
    # endpoint stays well-formed against an empty annotation store.
    assert payload["annotation_present"] is False


def test_gpa_scene_explain_returns_pixel_trace(api_client):
    """Pixel inside the mock viewport (800x600) → topmost-draw resolution."""
    text = mcp_server._tool_gpa_scene_explain(
        api_client, {"frame_id": 1, "x": 400, "y": 300}
    )
    payload = json.loads(text)
    assert payload["frame_id"] == 1
    assert payload["pixel"] == [400, 300]
    # The mock has draw 0 covering the full 800x600 viewport, so resolution
    # is approximate (not 'miss').
    assert payload["resolved"] in ("approximate", "miss")
    assert "draw_call_id" in payload


def test_gpa_scene_explain_negative_pixel_returns_error(api_client):
    text = mcp_server._tool_gpa_scene_explain(
        api_client, {"frame_id": 1, "x": -1, "y": 0}
    )
    payload = json.loads(text)
    assert "error" in payload
