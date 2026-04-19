"""Tests for pixel explanation REST endpoint (Task 7)."""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from starlette.testclient import TestClient

from gla.api.app import create_app
from gla.backends.native import NativeBackend
from gla.framework.types import PixelExplanation

AUTH_TOKEN = "test-token"
AUTH_HEADERS = {"Authorization": f"Bearer {AUTH_TOKEN}"}


_EXPLANATION = PixelExplanation(
    pixel={"x": 10, "y": 20, "r": 255, "g": 0, "b": 128, "a": 255, "depth": 0.5},
    draw_call_id=None,
    debug_group=None,
    render_pass=None,
    object=None,
    material=None,
    shader_params=[],
    data_sources=["gl_capture"],
)


def _make_mock_fqe(explanation=_EXPLANATION):
    fqe = MagicMock()
    fqe.explain_pixel.return_value = explanation
    return fqe


@pytest.fixture
def explain_client(mock_query_engine, mock_engine):
    provider = NativeBackend(mock_query_engine, engine=mock_engine)
    fqe = _make_mock_fqe()
    app = create_app(
        provider=provider,
        auth_token=AUTH_TOKEN,
        framework_query_engine=fqe,
    )
    return TestClient(app, raise_server_exceptions=True), fqe


@pytest.fixture
def explain_client_null(mock_query_engine, mock_engine):
    """Client whose FQE returns None for explain_pixel."""
    provider = NativeBackend(mock_query_engine, engine=mock_engine)
    fqe = _make_mock_fqe(explanation=None)
    app = create_app(
        provider=provider,
        auth_token=AUTH_TOKEN,
        framework_query_engine=fqe,
    )
    return TestClient(app, raise_server_exceptions=True)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_explain_pixel_200(explain_client):
    client, _ = explain_client
    resp = client.get("/api/v1/frames/1/explain/10/20", headers=AUTH_HEADERS)
    assert resp.status_code == 200
    data = resp.json()
    assert data["pixel"]["x"] == 10
    assert data["pixel"]["y"] == 20
    assert data["pixel"]["r"] == 255
    assert data["data_sources"] == ["gl_capture"]


def test_explain_pixel_404_when_none(explain_client_null):
    resp = explain_client_null.get("/api/v1/frames/1/explain/0/0", headers=AUTH_HEADERS)
    assert resp.status_code == 404


def test_explain_pixel_no_auth_401(explain_client):
    client, _ = explain_client
    resp = client.get("/api/v1/frames/1/explain/10/20")
    assert resp.status_code == 401
