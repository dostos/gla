"""REST API tests for per-frame free-form annotations (minimal Tier-3)."""
import pytest
from starlette.testclient import TestClient

from gpa.api.annotations_store import AnnotationsStore
from gpa.api.app import create_app
from gpa.backends.native import NativeBackend

from conftest import AUTH_TOKEN, AUTH_HEADERS


def test_post_then_get_roundtrip(client):
    payload = {"zoom": 4.5, "tile": "a/b/c", "nested": {"k": [1, 2, 3]}}
    r = client.post(
        "/api/v1/frames/1/annotations",
        json=payload,
        headers=AUTH_HEADERS,
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["ok"] is True
    assert body["frame_id"] == 1
    assert isinstance(body["byte_count"], int)
    assert body["byte_count"] > 0

    r = client.get("/api/v1/frames/1/annotations", headers=AUTH_HEADERS)
    assert r.status_code == 200
    assert r.json() == payload


def test_overwrite_same_frame(client):
    client.post("/api/v1/frames/2/annotations", json={"v": 1}, headers=AUTH_HEADERS)
    client.post("/api/v1/frames/2/annotations", json={"v": 2}, headers=AUTH_HEADERS)
    r = client.get("/api/v1/frames/2/annotations", headers=AUTH_HEADERS)
    assert r.json() == {"v": 2}


def test_get_unseen_frame_returns_empty(client):
    r = client.get("/api/v1/frames/987654/annotations", headers=AUTH_HEADERS)
    assert r.status_code == 200
    assert r.json() == {}


def test_oversized_body_rejected_with_413(client):
    big_value = "x" * (300 * 1024)  # > 256 KB
    r = client.post(
        "/api/v1/frames/3/annotations",
        json={"big": big_value},
        headers=AUTH_HEADERS,
    )
    assert r.status_code == 413, r.text


def test_non_dict_body_rejected(client):
    r = client.post(
        "/api/v1/frames/4/annotations",
        json=[1, 2, 3],  # list, not dict
        headers=AUTH_HEADERS,
    )
    assert r.status_code == 400


def test_lru_eviction(mock_query_engine, mock_engine):
    """POST 121 frames at capacity=120: the oldest must be gone."""
    provider = NativeBackend(mock_query_engine, engine=mock_engine)
    app = create_app(
        provider=provider,
        auth_token=AUTH_TOKEN,
        annotations_store=AnnotationsStore(capacity=120),
    )
    client = TestClient(app)

    for fid in range(121):
        r = client.post(
            f"/api/v1/frames/{fid}/annotations",
            json={"id": fid},
            headers=AUTH_HEADERS,
        )
        assert r.status_code == 200

    # Frame 0 was the oldest; it must have been evicted → returns {}.
    r = client.get("/api/v1/frames/0/annotations", headers=AUTH_HEADERS)
    assert r.json() == {}

    # Frame 1 is still present.
    r = client.get("/api/v1/frames/1/annotations", headers=AUTH_HEADERS)
    assert r.json() == {"id": 1}

    # Latest frame is present.
    r = client.get("/api/v1/frames/120/annotations", headers=AUTH_HEADERS)
    assert r.json() == {"id": 120}


@pytest.mark.parametrize("headers", [
    {},
    {"Authorization": "Bearer wrong-token"},
    {"Authorization": "not-even-a-bearer"},
])
def test_auth_required_on_post(client, headers):
    r = client.post(
        "/api/v1/frames/1/annotations",
        json={"k": "v"},
        headers=headers,
    )
    assert r.status_code == 401


@pytest.mark.parametrize("headers", [
    {},
    {"Authorization": "Bearer wrong-token"},
    {"Authorization": "not-even-a-bearer"},
])
def test_auth_required_on_get(client, headers):
    r = client.get("/api/v1/frames/1/annotations", headers=headers)
    assert r.status_code == 401


# ---------------------------------------------------------------------------
# `frame_id=latest` alias
# ---------------------------------------------------------------------------


def test_annotations_post_latest_alias(client):
    r = client.post(
        "/api/v1/frames/latest/annotations",
        json={"tag": "value"},
        headers=AUTH_HEADERS,
    )
    assert r.status_code == 200, r.text
    # conftest mock: latest frame id is 1
    assert r.json()["frame_id"] == 1

    r2 = client.get("/api/v1/frames/1/annotations", headers=AUTH_HEADERS)
    assert r2.json() == {"tag": "value"}


def test_annotations_get_latest_alias(client):
    client.post(
        "/api/v1/frames/1/annotations",
        json={"via": "numeric"},
        headers=AUTH_HEADERS,
    )
    r = client.get("/api/v1/frames/latest/annotations", headers=AUTH_HEADERS)
    assert r.status_code == 200
    assert r.json() == {"via": "numeric"}


def test_annotations_bogus_frame_id_returns_400(client):
    r = client.get("/api/v1/frames/foo/annotations", headers=AUTH_HEADERS)
    assert r.status_code == 400
