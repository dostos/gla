"""Endpoints for ``gpa trace`` reflection-scanner sidecar.

Phase 1 (shipped): POST/GET ``/frames/{id}/drawcalls/{dc}/sources`` —
raw per-drawcall reflection-scan payloads from the WebGL shim
(``src/shims/webgl/extension/gpa-trace.js``).

Phase 2 (this module): query-side endpoints for reverse-lookup:

- ``GET /frames/{id}/drawcalls/{dc}/trace/uniform/{name}`` — resolve a
  decoded uniform to its value, then find app-level fields that hold it.
- ``GET /frames/{id}/drawcalls/{dc}/trace/value?query=<literal>`` —
  direct reverse-lookup on a numeric / string literal.

The reverse-lookup works by parsing the stored hash keys back into
values and comparing with the requested literal. Hash key format:

- Numbers: ``"n:<canonical>"`` where ``<canonical>`` is ``NaN`` / ``Inf`` /
  ``-Inf`` / ``0`` / signed decimal (for integers |v| < 2^53) / ``f:<16
  hex chars>`` (IEEE-754 bit pattern for fractional doubles). This
  canonical format is matched byte-for-byte by the C shim
  (``src/shims/gl/native_trace.c``) and the JS extension
  (``src/shims/webgl/extension/gpa-trace.js``).
- Strings: ``"s:<djb2-of-lowered>"``
- Booleans: ``"b:<0|1>"``
- Arrays: ``"a:<djb2-of-json>"``

Legacy base-36 number hashes are still recognised — pre-canonical-format
payloads stay queryable even when the engine is upgraded in place.
"""
from __future__ import annotations

import math
import re
from typing import Any, Dict, List, Optional, Tuple, Union

from fastapi import APIRouter, HTTPException, Query, Request

from gpa.api.app import resolve_frame_id, safe_json_response
from gpa.api.trace_ranking import (
    build_corpus_for_value,
    rank_candidates,
)

router = APIRouter(tags=["trace"])

# 256 KB per drawcall payload cap — matches annotations. A full value
# index with depth-4 / 1000-object cap should be well under this.
MAX_SOURCES_BYTES = 256 * 1024

# How many recent frames to consider when building the rarity corpus.
RARITY_WINDOW = 10

# Float tolerance used when reverse-matching a numeric literal to a
# parsed-from-base36 value. Captured GL uniforms are usually float32,
# while the scanner hashes the JS-side float64 value; we need enough
# slack to bridge that precision gap (~1e-6 relative) without making
# unrelated values collide.
FLOAT_REL_TOL = 1e-5
FLOAT_ABS_TOL = 1e-9


# ======================================================================
# Phase 1 — POST / GET raw sources
# ======================================================================


@router.post("/frames/{frame_id}/drawcalls/{dc_id}/sources")
async def post_sources(frame_id: Union[int, str], dc_id: int, request: Request):
    """Store the reflection-scan sources for *(frame_id, dc_id)*."""
    frame_id = resolve_frame_id(frame_id, request.app.state.provider)
    raw = await request.body()
    if len(raw) > MAX_SOURCES_BYTES:
        raise HTTPException(
            status_code=413,
            detail=(
                f"Sources payload {len(raw)} bytes exceeds "
                f"{MAX_SOURCES_BYTES}-byte limit"
            ),
        )
    try:
        data = await request.json()
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=400, detail=f"Invalid JSON: {exc}")
    if not isinstance(data, dict):
        raise HTTPException(
            status_code=400,
            detail="Sources body must be a JSON object (dict)",
        )
    sources = data.get("sources") if "sources" in data else data
    if not isinstance(sources, dict):
        raise HTTPException(
            status_code=400,
            detail="'sources' field must be a JSON object",
        )

    store = request.app.state.trace_store
    store.put(frame_id, dc_id, sources)
    return safe_json_response({
        "ok": True,
        "frame_id": frame_id,
        "dc_id": dc_id,
        "byte_count": len(raw),
    })


@router.get("/frames/{frame_id}/drawcalls/{dc_id}/sources")
def get_sources(frame_id: Union[int, str], dc_id: int, request: Request):
    """Return stored sources for *(frame_id, dc_id)*."""
    frame_id = resolve_frame_id(frame_id, request.app.state.provider)
    store = request.app.state.trace_store
    sources = store.get(frame_id, dc_id)
    if sources is None:
        raise HTTPException(
            status_code=404,
            detail=f"No sources stored for frame={frame_id} dc={dc_id}",
        )
    return safe_json_response(sources)


# ======================================================================
# Phase 2 — reverse lookup
# ======================================================================


_NUM_HASH_RE = re.compile(r"^n:(.*)$")
_STR_HASH_RE = re.compile(r"^s:(.*)$")
_BOOL_HASH_RE = re.compile(r"^b:([01])$")
_ARR_HASH_RE = re.compile(r"^a:(.*)$")


def _parse_canonical_number(token: str) -> Optional[float]:
    """Parse a canonical number hash body.

    Canonical format (matches src/shims/gl/native_trace.c and
    src/shims/webgl/extension/gpa-trace.js)::

        NaN | Inf | -Inf        → float sentinels
        0                       → 0.0
        <signed decimal>        → integer via int(...)
        f:<16 hex chars>        → IEEE-754 bit pattern (big-endian)

    For backward compatibility with pre-canonical-format sources (base-36
    encoded), we fall back to the old parser if the token doesn't match
    any canonical shape. Pre-fix payloads may still be in the trace store
    when the engine is upgraded without clearing state.
    """
    import struct

    if not token:
        return None
    if token in ("NaN", "Inf", "-Inf"):
        return {"NaN": math.nan, "Inf": math.inf, "-Inf": -math.inf}[token]
    if token.startswith("f:") and len(token) == 2 + 16:
        try:
            bits = int(token[2:], 16)
        except ValueError:
            return None
        try:
            return struct.unpack(">d", bits.to_bytes(8, "big"))[0]
        except (OverflowError, struct.error):
            return None
    # Decimal integer.
    try:
        return float(int(token, 10))
    except ValueError:
        pass
    # Legacy base-36 (pre-canonical-format sources).
    return _parse_b36_legacy(token)


def _parse_b36_legacy(token: str) -> Optional[float]:
    """Legacy parser for the pre-canonical base-36 format.

    Kept so old TraceStore entries (or trace payloads from not-yet-rebundled
    browser extensions) still resolve. New C / JS scanners emit the
    canonical format handled above.
    """
    if not token:
        return None
    neg = False
    if token.startswith("-"):
        neg = True
        token = token[1:]
    if "." in token:
        int_part, frac_part = token.split(".", 1)
    else:
        int_part, frac_part = token, ""
    try:
        val = float(int(int_part, 36)) if int_part else 0.0
        for i, ch in enumerate(frac_part):
            val += int(ch, 36) / (36.0 ** (i + 1))
    except ValueError:
        return None
    return -val if neg else val


# Backwards-compat alias.
_parse_b36 = _parse_canonical_number


def _djb2(s: str) -> str:
    """Mirror of the scanner's djb2 → base-36 hashing (for string lookup)."""
    h = 5381
    for ch in s:
        h = ((h << 5) + h + ord(ch)) & 0xFFFFFFFF
    return _int_to_b36(h & 0xFFFFFFFF)


_B36_ALPHABET = "0123456789abcdefghijklmnopqrstuvwxyz"


def _int_to_b36(n: int) -> str:
    if n == 0:
        return "0"
    out = ""
    while n > 0:
        out = _B36_ALPHABET[n % 36] + out
        n //= 36
    return out


def _numbers_match(a: float, b: float) -> bool:
    if math.isnan(a) and math.isnan(b):
        return True
    if math.isinf(a) or math.isinf(b):
        return a == b
    return math.isclose(a, b, rel_tol=FLOAT_REL_TOL, abs_tol=FLOAT_ABS_TOL)


def _literal_matches_hash(literal: Any, hash_key: str) -> bool:
    """Does *hash_key* encode *literal*?"""
    if isinstance(literal, bool):
        m = _BOOL_HASH_RE.match(hash_key)
        return bool(m and (m.group(1) == "1") == literal)
    if isinstance(literal, (int, float)):
        m = _NUM_HASH_RE.match(hash_key)
        if not m:
            return False
        parsed = _parse_b36(m.group(1))
        if parsed is None:
            return False
        return _numbers_match(float(literal), parsed)
    if isinstance(literal, str):
        m = _STR_HASH_RE.match(hash_key)
        if not m:
            return False
        return m.group(1) == _djb2(literal.lower())
    if isinstance(literal, (list, tuple)):
        m = _ARR_HASH_RE.match(hash_key)
        if not m:
            return False
        import json as _json
        try:
            canonical = _json.dumps(list(literal))
        except (TypeError, ValueError):
            return False
        return m.group(1) == _djb2(canonical)
    return False


def _collect_candidates_for_value(
    store,
    frame_id: int,
    dc_id: Optional[int],
    literal: Any,
) -> Tuple[List[Dict[str, Any]], Optional[str]]:
    """Walk *store*[frame_id][dc_id?] and return every path entry whose
    hash-key encodes *literal*.

    Also returns the matched hash (for rarity-corpus construction), or
    *None* if nothing matched.
    """
    matched_hash: Optional[str] = None
    collected: List[Dict[str, Any]] = []

    if dc_id is not None:
        src = store.get(frame_id, dc_id)
        dc_iter: List[Tuple[int, Dict[str, Any]]] = [
            (dc_id, src)
        ] if src is not None else []
    else:
        dc_iter = [
            (e["dc_id"], e["sources"])
            for e in store.get_frame(frame_id)
        ]

    for dcid, src in dc_iter:
        value_index = src.get("value_index") if isinstance(src, dict) else None
        if not isinstance(value_index, dict):
            continue
        for hkey, paths in value_index.items():
            if not isinstance(hkey, str) or not isinstance(paths, list):
                continue
            if not _literal_matches_hash(literal, hkey):
                continue
            matched_hash = hkey
            for p in paths:
                if not isinstance(p, dict):
                    continue
                entry = dict(p)
                entry["dc_id"] = dcid
                collected.append(entry)
    return collected, matched_hash


# ----------------------------------------------------------------------
# Value extraction for the uniform / texture routes
# ----------------------------------------------------------------------

def _param_field(p: Any, key: str, default: Any = None) -> Any:
    """Field access that works for both dict params (post-NativeBackend
    conversion) and attribute-bearing params (raw pybind11 / MagicMock).
    """
    if isinstance(p, dict):
        return p.get(key, default)
    return getattr(p, key, default)


def _find_uniform_value(dc, name: str) -> Optional[Any]:
    """Pick the decoded value of uniform *name* from *dc.params*."""
    for p in getattr(dc, "params", None) or []:
        pname = _param_field(p, "name")
        if pname == name:
            # Prefer an already-decoded ``value``. If absent, we can't
            # match — the raw bytes are framework-opaque.
            has_value = (
                ("value" in p) if isinstance(p, dict)
                else hasattr(p, "value")
            )
            if not has_value:
                return None
            val = _param_field(p, "value")
            if val is None:
                return None
            if isinstance(val, (list, tuple)) and len(val) == 1:
                return val[0]
            return val
    return None


def _no_match_hint() -> str:
    return (
        "no app-level field currently holds this value — value may be "
        "computed inline at the call site"
    )


def _recent_frame_ids(store) -> List[int]:
    """Best-effort — peek at the LRU to pick the last N frame ids."""
    # TraceStore doesn't expose its keys; walk the private dict under the
    # lock. Worst case (misuse by a subclass) we get an empty list and
    # skip the rarity step.
    try:
        with store._lock:  # type: ignore[attr-defined]
            keys = list(store._data.keys())  # type: ignore[attr-defined]
    except Exception:
        return []
    return keys[-RARITY_WINDOW:]


def _build_response(
    frame_id: int,
    dc_id: Optional[int],
    field: Optional[str],
    value: Any,
    candidates: List[Dict[str, Any]],
    matched_hash: Optional[str],
    store,
    call_site: Optional[str] = None,
) -> Dict[str, Any]:
    corpus = None
    if matched_hash is not None:
        corpus = build_corpus_for_value(
            store, matched_hash, _recent_frame_ids(store)
        )
    ranked = rank_candidates(candidates, value, corpus=corpus)
    resp: Dict[str, Any] = {
        "frame_id": frame_id,
        "dc_id": dc_id,
        "field": field,
        "value": value,
        "candidates": ranked,
    }
    if call_site is not None:
        resp["call_site"] = call_site
    if not ranked:
        resp["hint"] = _no_match_hint()
    return resp


# ----------------------------------------------------------------------
# Routes
# ----------------------------------------------------------------------

@router.get("/frames/{frame_id}/drawcalls/{dc_id}/trace/uniform/{name}")
def trace_uniform(
    frame_id: Union[int, str], dc_id: int, name: str, request: Request,
):
    """Resolve uniform *name* at *(frame_id, dc_id)* and reverse-lookup."""
    provider = request.app.state.provider
    frame_id = resolve_frame_id(frame_id, provider)
    dc = provider.get_draw_call(frame_id, dc_id)
    if dc is None:
        raise HTTPException(
            status_code=404,
            detail=f"Draw call {dc_id} in frame {frame_id} not found",
        )
    value = _find_uniform_value(dc, name)
    if value is None:
        raise HTTPException(
            status_code=404,
            detail=(
                f"Uniform {name!r} not decoded for frame={frame_id} "
                f"dc={dc_id} (either not bound or raw bytes only)"
            ),
        )

    store = request.app.state.trace_store
    # Vector uniforms: try the whole array first, then each component.
    lookup_value = value
    if isinstance(value, (list, tuple)):
        lookup_value = list(value)
    cands, mhash = _collect_candidates_for_value(
        store, frame_id, dc_id, lookup_value
    )

    return safe_json_response(_build_response(
        frame_id=frame_id, dc_id=dc_id, field=name, value=value,
        candidates=cands, matched_hash=mhash, store=store,
    ))


@router.get("/frames/{frame_id}/drawcalls/{dc_id}/trace/value")
def trace_value_dc(
    frame_id: Union[int, str], dc_id: int, request: Request,
    query: str = Query(..., description="Literal value (JSON-encoded)"),
):
    """Reverse-lookup a literal within a single (frame, dc) pair."""
    frame_id = resolve_frame_id(frame_id, request.app.state.provider)
    literal = _parse_literal(query)
    store = request.app.state.trace_store
    cands, mhash = _collect_candidates_for_value(
        store, frame_id, dc_id, literal
    )
    return safe_json_response(_build_response(
        frame_id=frame_id, dc_id=dc_id, field=None, value=literal,
        candidates=cands, matched_hash=mhash, store=store,
    ))


@router.get("/frames/{frame_id}/trace/value")
def trace_value_frame(
    frame_id: Union[int, str], request: Request,
    query: str = Query(..., description="Literal value (JSON-encoded)"),
):
    """Reverse-lookup a literal across every stored dc in *frame_id*."""
    frame_id = resolve_frame_id(frame_id, request.app.state.provider)
    literal = _parse_literal(query)
    store = request.app.state.trace_store
    cands, mhash = _collect_candidates_for_value(
        store, frame_id, None, literal
    )
    return safe_json_response(_build_response(
        frame_id=frame_id, dc_id=None, field=None, value=literal,
        candidates=cands, matched_hash=mhash, store=store,
    ))


def _parse_literal(query: str) -> Any:
    """Accept a JSON-encoded literal or a bare token.

    ``16.58`` → ``16.58`` (float). ``"hello"`` → ``"hello"``. ``true`` →
    ``True``. Anything else that doesn't parse as JSON is returned as a
    raw string.
    """
    import json
    try:
        return json.loads(query)
    except (ValueError, TypeError):
        return query
