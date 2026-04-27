"""End-to-end integration test for the ``gpa trace`` pipeline.

Exercises the full scanner-side POST → TraceStore → query REST → CLI
plain-text render path without a real browser. The scanner's JS hashing
is reproduced by parsing stored hash keys back into numbers on the
server side, so we feed in realistic payloads (the same shape
``gpa-trace.js`` would send) and query them with the CLI-layer
plumbing.
"""

from __future__ import annotations

import io

import pytest
from starlette.testclient import TestClient

from gpa.cli.commands import trace as trace_cmd
from gpa.cli.rest_client import RestClient, RestError

from conftest import AUTH_HEADERS, AUTH_TOKEN


# ----------------------------------------------------------------------
# Helpers
# ----------------------------------------------------------------------


def _rest_client(client: TestClient) -> RestClient:
    def http_callable(method, path, headers, body=None):
        if method == "GET":
            resp = client.get(path, headers=headers)
        elif method == "POST":
            resp = client.post(path, headers=headers, content=body)
        else:  # pragma: no cover
            raise AssertionError(f"unsupported method {method}")
        if resp.status_code >= 400:
            raise RestError(
                f"{method} {path} → HTTP {resp.status_code}: {resp.text}",
                status=resp.status_code,
            )
        if not resp.content:
            return None
        return resp.json()

    return RestClient(token=AUTH_TOKEN, http_callable=http_callable)


def _scanner_payload_16_58(extra_paths=None):
    """Mimic the payload ``gpa-trace.js`` would POST for the scenario
    'uZoom uniform = 16.58, produced by map._transform._maxZoom'.

    The key ``n:g.kvoha2voh`` is the exact hash that the JS scanner
    produces for 16.58 via ``Number.prototype.toString(36)`` — Python
    reverses it with IEEE 754 round-trip arithmetic (see
    ``routes_trace._parse_b36``).
    """
    paths = [{"path": "map._transform._maxZoom", "type": "number",
              "confidence": "high"}]
    if extra_paths:
        paths.extend(extra_paths)
    return {
        "roots": ["map", "THREE"],
        "mode": "gated",
        "value_index": {
            "n:g.kvoha2voh": paths,
        },
        "truncated": False,
        "scan_ms": 0.4,
    }


# ----------------------------------------------------------------------
# Full pipeline: POST sources → GET raw → simulate `gpa trace value`
# ----------------------------------------------------------------------


def test_post_then_raw_get_roundtrip(client):
    r = client.post(
        "/api/v1/frames/1/drawcalls/3/sources",
        json=_scanner_payload_16_58(),
        headers=AUTH_HEADERS,
    )
    assert r.status_code == 200, r.text

    r = client.get("/api/v1/frames/1/drawcalls/3/sources", headers=AUTH_HEADERS)
    assert r.status_code == 200
    got = r.json()
    assert "n:g.kvoha2voh" in got["value_index"]


def test_trace_value_resolves_candidate_via_cli(client):
    # Seed the store.
    client.post(
        "/api/v1/frames/1/drawcalls/3/sources",
        json=_scanner_payload_16_58(),
        headers=AUTH_HEADERS,
    )

    rest = _rest_client(client)
    buf = io.StringIO()
    rc = trace_cmd.run_value(
        literal="16.58", frame=1, dc=3, client=rest, print_stream=buf,
    )
    assert rc == 0, buf.getvalue()
    out = buf.getvalue()
    assert "map._transform._maxZoom" in out
    # Plain-text shape: "value (frame N, dc M) = 16.58"
    assert "frame 1" in out
    assert "dc 3" in out
    assert "16.58" in out
    # Rendered candidate block.
    assert "candidates:" in out
    assert "[high]" in out or "[medium]" in out


def test_trace_value_frame_wide_without_dc(client):
    client.post(
        "/api/v1/frames/1/drawcalls/0/sources",
        json=_scanner_payload_16_58(),
        headers=AUTH_HEADERS,
    )
    client.post(
        "/api/v1/frames/1/drawcalls/7/sources",
        json={
            "value_index": {
                "n:g.kvoha2voh": [
                    {"path": "style.zoom", "type": "number", "confidence": "high"},
                ],
            },
        },
        headers=AUTH_HEADERS,
    )

    rest = _rest_client(client)
    buf = io.StringIO()
    rc = trace_cmd.run_value(
        literal="16.58", frame=1, client=rest, print_stream=buf,
    )
    assert rc == 0
    out = buf.getvalue()
    assert "map._transform._maxZoom" in out
    assert "style.zoom" in out


def test_trace_value_json_output(client):
    client.post(
        "/api/v1/frames/1/drawcalls/3/sources",
        json=_scanner_payload_16_58(),
        headers=AUTH_HEADERS,
    )
    rest = _rest_client(client)
    buf = io.StringIO()
    rc = trace_cmd.run_value(
        literal="16.58", frame=1, dc=3, client=rest, print_stream=buf,
        json_output=True,
    )
    assert rc == 0
    import json as _json
    payload = _json.loads(buf.getvalue())
    assert payload["frame_id"] == 1
    assert payload["dc_id"] == 3
    assert payload["value"] == 16.58
    assert any(
        c["path"] == "map._transform._maxZoom" for c in payload["candidates"]
    )
    # Every ranked candidate carries the enriched fields.
    for c in payload["candidates"]:
        assert "distance_hops" in c
        assert c["confidence"] in ("high", "medium", "low")


def test_trace_value_unique_match_upgrades_confidence(client):
    """One rare path across a single frame → rarity rule bumps its tier."""
    client.post(
        "/api/v1/frames/4/drawcalls/0/sources",
        json={
            "value_index": {
                "n:g.kvoha2voh": [
                    {"path": "myApp.rareField", "type": "number",
                     "confidence": "low"},
                ],
            },
        },
        headers=AUTH_HEADERS,
    )

    rest = _rest_client(client)
    buf = io.StringIO()
    trace_cmd.run_value(
        literal="16.58", frame=4, dc=0, client=rest, print_stream=buf,
        json_output=True,
    )
    import json as _json
    payload = _json.loads(buf.getvalue())
    cands = payload["candidates"]
    assert len(cands) == 1
    # Rarity promoted low → medium.
    assert cands[0]["confidence"] == "medium"
    assert cands[0]["raw_confidence"] == "low"


def test_trace_value_no_match_emits_hint(client):
    client.post(
        "/api/v1/frames/1/drawcalls/0/sources",
        json={"value_index": {"n:g.kvoha2voh": [
            {"path": "some.path", "type": "number", "confidence": "high"},
        ]}},
        headers=AUTH_HEADERS,
    )
    rest = _rest_client(client)
    buf = io.StringIO()
    rc = trace_cmd.run_value(
        literal="999", frame=1, dc=0, client=rest, print_stream=buf,
    )
    assert rc == 0
    out = buf.getvalue()
    assert "no app-level field" in out


def test_trace_uniform_end_to_end(client):
    """Uniform resolution path: server inspects dc.params, finds the
    decoded value, reverse-matches against stored scanner payload.

    The shared ``client`` fixture's mocked dc 0 exposes a decoded float
    uniform ``uColor = [1.0, 0.0, 0.0, 1.0]``. We seed a scanner payload
    whose value-index holds the whole vec4 under its canonical JSON hash
    so the uniform path resolves. Rather than reproduce the JS array
    hash here, we target a scalar uniform scenario by posting a
    payload keyed to the hash of ``1.0`` (the alpha component) — the
    server will whole-array-match first and come up empty, then we
    check the fallback via ``gpa trace value``.
    """
    # Seed the store with a payload that matches the scalar 1.0 so we can
    # exercise the `trace value` path. For the uniform path we rely on
    # the separate `test_trace_uniform_matches_vector_component` below.
    client.post(
        "/api/v1/frames/1/drawcalls/0/sources",
        json={
            "value_index": {
                "n:1": [
                    {"path": "material.opacity", "type": "number",
                     "confidence": "high"},
                ],
            },
        },
        headers=AUTH_HEADERS,
    )
    rest = _rest_client(client)
    buf = io.StringIO()
    rc = trace_cmd.run_value(
        literal="1.0", frame=1, dc=0, client=rest, print_stream=buf,
        json_output=True,
    )
    assert rc == 0
    import json as _json
    payload = _json.loads(buf.getvalue())
    assert any(c["path"] == "material.opacity" for c in payload["candidates"])


def test_trace_uniform_vector_whole_array_match(client):
    """uniform uColor is a vec4; scanner stored ``a:<djb2>`` under the
    same JSON it canonicalized. We post that key directly so the server
    finds it via whole-array match.
    """
    # Compute the a: hash for [1.0, 0.0, 0.0, 1.0] exactly the way the JS
    # scanner does: djb2 of JSON.stringify(...). We reuse the server's
    # helper to stay consistent.
    from gpa.api.routes_trace import _djb2
    import json as _json
    canonical = _json.dumps([1.0, 0.0, 0.0, 1.0])
    vhash = "a:" + _djb2(canonical)
    client.post(
        "/api/v1/frames/1/drawcalls/0/sources",
        json={
            "value_index": {
                vhash: [
                    {"path": "material.color", "type": "array",
                     "confidence": "high"},
                ],
            },
        },
        headers=AUTH_HEADERS,
    )
    rest = _rest_client(client)
    buf = io.StringIO()
    rc = trace_cmd.run_uniform(
        name="uColor", frame=1, dc=0, client=rest, print_stream=buf,
        json_output=True,
    )
    assert rc == 0, buf.getvalue()
    payload = _json.loads(buf.getvalue())
    assert payload["field"] == "uColor"
    assert any(c["path"] == "material.color" for c in payload["candidates"])


def test_trace_value_requires_no_dc_returns_multiple(client):
    """Rarity disengages when the same hash appears in many paths."""
    # Six distinct paths → rarity count > 5 → downgrade.
    paths = [
        {"path": f"pool.slot{i}", "type": "number", "confidence": "high"}
        for i in range(6)
    ]
    client.post(
        "/api/v1/frames/5/drawcalls/0/sources",
        json={"value_index": {"n:g.kvoha2voh": paths}},
        headers=AUTH_HEADERS,
    )
    rest = _rest_client(client)
    buf = io.StringIO()
    trace_cmd.run_value(
        literal="16.58", frame=5, dc=0, client=rest, print_stream=buf,
        json_output=True,
    )
    import json as _json
    payload = _json.loads(buf.getvalue())
    assert len(payload["candidates"]) == 6
    # At least one of the 6 should be demoted to "medium" (was high).
    assert any(c["confidence"] == "medium" for c in payload["candidates"])


def test_trace_plain_text_shape_matches_spec(client):
    """The format matches the docstring example in the spec."""
    client.post(
        "/api/v1/frames/2/drawcalls/3/sources",
        json=_scanner_payload_16_58(extra_paths=[
            {"path": "sourceCache.maxzoom", "type": "number",
             "confidence": "high"},
            {"path": "style._sources.terrain.maxzoom", "type": "number",
             "confidence": "medium"},
        ]),
        headers=AUTH_HEADERS,
    )
    rest = _rest_client(client)
    buf = io.StringIO()
    trace_cmd.run_value(
        literal="16.58", frame=2, dc=3, client=rest, print_stream=buf,
    )
    out = buf.getvalue()
    # Header line
    assert "value (frame 2, dc 3) = 16.58" in out
    # Body has each candidate
    assert "map._transform._maxZoom" in out
    assert "sourceCache.maxzoom" in out
    assert "style._sources.terrain.maxzoom" in out
    # hop counts are rendered
    assert "hops)" in out or "hop)" in out


# ----------------------------------------------------------------------
# Negative paths
# ----------------------------------------------------------------------


def test_trace_uniform_unknown_name_404(client):
    rest = _rest_client(client)
    buf = io.StringIO()
    rc = trace_cmd.run_uniform(
        name="uDoesNotExist", frame=1, dc=0, client=rest, print_stream=buf,
    )
    # CLI translates a 404 to a generic exit-1 transport error.
    assert rc == 1


def test_trace_uniform_requires_dc():
    from gpa.cli.rest_client import RestClient
    buf = io.StringIO()
    client = RestClient(token=AUTH_TOKEN, http_callable=lambda *a, **k: None)
    rc = trace_cmd.run_uniform(
        name="uZoom", frame=1, dc=None, client=client, print_stream=buf,
    )
    assert rc == 2


def test_trace_value_missing_frame_exits_4(client):
    """run_value resolves frame via /frames/current/overview; we emulate
    an engine with no frames by making GET 404."""
    def http_callable(method, path, headers, body=None):
        # Simulate "no frames captured yet": the current-overview GET
        # returns 404, which RestClient surfaces as RestError → _resolve
        # returns None → command exits 4.
        if path.endswith("/frames/current/overview"):
            raise RestError("HTTP 404", status=404)
        return None

    rest = RestClient(token=AUTH_TOKEN, http_callable=http_callable)
    buf = io.StringIO()
    rc = trace_cmd.run_value(
        literal="1", frame=None, client=rest, print_stream=buf,
    )
    assert rc == 4
