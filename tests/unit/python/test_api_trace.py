"""REST API tests for `gpa trace` reflection-scan sources endpoints."""
import pytest
from starlette.testclient import TestClient

from gpa.api.app import create_app
from gpa.api.trace_store import TraceStore
from gpa.backends.native import NativeBackend

from conftest import AUTH_HEADERS, AUTH_TOKEN


def _payload(path: str = "map._transform._maxZoom", vhash: str = "vh"):
    return {
        "frame_id": 2,
        "dc_id": 3,
        "sources": {
            "roots": ["THREE", "map"],
            "mode": "gated",
            "value_index": {
                vhash: [
                    {"path": path, "type": "number", "confidence": "high"},
                ],
            },
            "truncated": False,
            "scan_ms": 1.23,
        },
    }


def test_post_then_get_roundtrip(client):
    pl = _payload()
    r = client.post(
        "/api/v1/frames/2/drawcalls/3/sources",
        json=pl,
        headers=AUTH_HEADERS,
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["ok"] is True
    assert body["frame_id"] == 2
    assert body["dc_id"] == 3
    assert body["byte_count"] > 0

    r = client.get("/api/v1/frames/2/drawcalls/3/sources", headers=AUTH_HEADERS)
    assert r.status_code == 200
    got = r.json()
    assert got == pl["sources"]


def test_post_bare_sources_dict_accepted(client):
    """The shim may POST either the wrapped shape or a bare sources dict."""
    bare = {
        "roots": ["PIXI"],
        "mode": "gated",
        "value_index": {"h": [{"path": "app.stage.x", "type": "number"}]},
    }
    r = client.post(
        "/api/v1/frames/7/drawcalls/0/sources",
        json=bare,
        headers=AUTH_HEADERS,
    )
    assert r.status_code == 200, r.text
    r = client.get("/api/v1/frames/7/drawcalls/0/sources", headers=AUTH_HEADERS)
    assert r.json()["roots"] == ["PIXI"]


def test_overwrite_same_drawcall(client):
    client.post("/api/v1/frames/1/drawcalls/0/sources",
                json=_payload("a"), headers=AUTH_HEADERS)
    client.post("/api/v1/frames/1/drawcalls/0/sources",
                json=_payload("b"), headers=AUTH_HEADERS)
    r = client.get("/api/v1/frames/1/drawcalls/0/sources", headers=AUTH_HEADERS)
    idx = r.json()["value_index"]["vh"]
    assert idx[0]["path"] == "b"


def test_get_unknown_returns_404(client):
    r = client.get("/api/v1/frames/999/drawcalls/0/sources", headers=AUTH_HEADERS)
    assert r.status_code == 404


def test_post_non_dict_rejected(client):
    r = client.post(
        "/api/v1/frames/1/drawcalls/0/sources",
        json=[1, 2, 3],
        headers=AUTH_HEADERS,
    )
    assert r.status_code == 400


def test_post_bad_sources_field_rejected(client):
    r = client.post(
        "/api/v1/frames/1/drawcalls/0/sources",
        json={"frame_id": 1, "dc_id": 0, "sources": "not-a-dict"},
        headers=AUTH_HEADERS,
    )
    assert r.status_code == 400


def test_post_oversized_rejected(client):
    big = "x" * (300 * 1024)
    r = client.post(
        "/api/v1/frames/1/drawcalls/0/sources",
        json={"value_index": {"h": [{"path": big, "type": "string"}]}},
        headers=AUTH_HEADERS,
    )
    assert r.status_code == 413


@pytest.mark.parametrize("headers", [
    {},
    {"Authorization": "Bearer wrong"},
    {"Authorization": "malformed"},
])
def test_auth_required_post(client, headers):
    r = client.post(
        "/api/v1/frames/1/drawcalls/0/sources",
        json=_payload(),
        headers=headers,
    )
    assert r.status_code == 401


@pytest.mark.parametrize("headers", [
    {},
    {"Authorization": "Bearer wrong"},
    {"Authorization": "malformed"},
])
def test_auth_required_get(client, headers):
    r = client.get("/api/v1/frames/1/drawcalls/0/sources", headers=headers)
    assert r.status_code == 401


def test_custom_trace_store_wired(mock_query_engine, mock_engine):
    """Make sure the trace_store kwarg is propagated to app.state."""
    store = TraceStore(capacity=4)
    provider = NativeBackend(mock_query_engine, engine=mock_engine)
    app = create_app(
        provider=provider,
        auth_token=AUTH_TOKEN,
        trace_store=store,
    )
    client = TestClient(app)
    client.post(
        "/api/v1/frames/1/drawcalls/0/sources",
        json=_payload(),
        headers=AUTH_HEADERS,
    )
    # The shared instance must see the write.
    assert store.get(1, 0) is not None


# ---------------------------------------------------------------------------
# `frame_id=latest` alias on trace routes
# ---------------------------------------------------------------------------


def test_post_sources_latest_alias(client):
    r = client.post(
        "/api/v1/frames/latest/drawcalls/0/sources",
        json=_payload(),
        headers=AUTH_HEADERS,
    )
    assert r.status_code == 200, r.text
    # conftest mock: latest frame id is 1
    assert r.json()["frame_id"] == 1
    r2 = client.get(
        "/api/v1/frames/1/drawcalls/0/sources", headers=AUTH_HEADERS
    )
    assert r2.status_code == 200


def test_get_sources_latest_alias(client):
    client.post(
        "/api/v1/frames/1/drawcalls/0/sources",
        json=_payload(),
        headers=AUTH_HEADERS,
    )
    r = client.get(
        "/api/v1/frames/latest/drawcalls/0/sources", headers=AUTH_HEADERS
    )
    assert r.status_code == 200
    assert "value_index" in r.json()


def test_trace_value_frame_latest_alias(client):
    r = client.get(
        "/api/v1/frames/latest/trace/value?query=42", headers=AUTH_HEADERS
    )
    assert r.status_code == 200
    assert r.json()["frame_id"] == 1


def test_trace_value_dc_latest_alias(client):
    r = client.get(
        "/api/v1/frames/latest/drawcalls/0/trace/value?query=42",
        headers=AUTH_HEADERS,
    )
    assert r.status_code == 200
    assert r.json()["frame_id"] == 1


def test_trace_routes_reject_bogus_frame_id(client):
    r = client.get(
        "/api/v1/frames/foo/trace/value?query=42", headers=AUTH_HEADERS
    )
    assert r.status_code == 400
