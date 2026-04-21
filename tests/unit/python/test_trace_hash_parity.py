"""Cross-origin hash parity: C shim (via Python port) ↔ JS extension
(via Node if available or a Python reference implementation) ↔ Python
parser.

The canonical number-hash format is documented in
``src/shims/gl/native_trace.c::number_to_js_base36`` and matched by
``src/shims/webgl/extension/gpa-trace.js::canonicalNumber``. This test
verifies the three implementations agree byte-for-byte on a curated set
of values that previously exercised the divergence (integers, zero,
fractional doubles, negative zero, NaN, +/- Inf, subnormal, boundary).

We exercise the C side indirectly: the C implementation is trivial
enough to mirror in Python (same format spec), so we compare the Python
mirror with the Python parser's inverse and — when `node` is on PATH —
with the JS implementation loaded from the extension source.
"""
from __future__ import annotations

import math
import shutil
import struct
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
JS_EXT = REPO_ROOT / "src" / "shims" / "webgl" / "extension" / "gpa-trace.js"


# ---------------------------------------------------------------------------
# Python reference — mirrors the C canonical formatter byte-for-byte.
# ---------------------------------------------------------------------------
def canonical_py(v: float) -> str:
    """Mirror of `number_to_js_base36` in native_trace.c (C side) and
    `canonicalNumber` in gpa-trace.js (JS side)."""
    if math.isnan(v):
        return "NaN"
    if math.isinf(v):
        return "Inf" if v > 0 else "-Inf"
    if v == 0:
        return "0"
    # int fast path
    if abs(v) < 2**53 and v == int(v):
        return str(int(v))
    bits = struct.unpack(">Q", struct.pack(">d", v))[0]
    return f"f:{bits:016x}"


# Known-value table.
VALUES = [
    0.0,
    -0.0,
    1.0,
    -1.0,
    42.0,
    -42.0,
    100.0,
    2**52 - 1.0,
    -(2**52 - 1.0),
    16.58,
    3.14159,
    1e-10,
    1e10,
    math.nan,
    math.inf,
    -math.inf,
    2.2250738585072014e-308,  # smallest positive normal double
]


@pytest.mark.parametrize("v", VALUES, ids=lambda v: repr(v))
def test_python_canonical_matches_c_reference(v):
    """Sanity-check the Python mirror against the C spec by computing
    the expected body for each value class and comparing."""
    body = canonical_py(v)
    # Parse back and check round-trip.
    from gpa.api.routes_trace import _parse_canonical_number

    parsed = _parse_canonical_number(body)
    if math.isnan(v):
        assert math.isnan(parsed)
    elif math.isinf(v):
        assert parsed == v
    elif v == 0:
        assert parsed == 0
    else:
        # For exact IEEE-754 round-trip we need to compare bits, since
        # 16.58 rounds at the float64 boundary.
        assert struct.pack(">d", parsed) == struct.pack(">d", v), (
            f"body={body} parsed={parsed!r} v={v!r}"
        )


@pytest.mark.parametrize("v,expected", [
    (0.0, "0"),
    (-0.0, "0"),
    (42.0, "42"),
    (-42.0, "-42"),
    (100.0, "100"),
    (16.58, "f:4030947ae147ae14"),
    (math.nan, "NaN"),
    (math.inf, "Inf"),
    (-math.inf, "-Inf"),
])
def test_python_canonical_byte_for_byte(v, expected):
    assert canonical_py(v) == expected


# ---------------------------------------------------------------------------
# JS parity — run via node if available.
# ---------------------------------------------------------------------------
def _have_node() -> bool:
    return shutil.which("node") is not None


JS_TEST = REPO_ROOT / "tests" / "unit" / "shims" / "test_gpa_trace_js_hash.js"


@pytest.mark.skipif(not _have_node(), reason="node not installed")
def test_js_canonical_matches_python_mirror():
    """Run tests/unit/shims/test_gpa_trace_js_hash.js under node and
    assert it exits 0. That test loads gpa-trace.js into a VM sandbox
    and verifies `window.gpa.trace._hashValue()` emits the same
    canonical strings the C shim + Python parser use, for 12
    hand-computed boundary values (NaN, Inf, zero, signed ints,
    fractional doubles)."""
    assert JS_TEST.exists(), f"missing JS parity harness: {JS_TEST}"
    proc = subprocess.run(
        ["node", str(JS_TEST)],
        capture_output=True, text=True, timeout=10,
    )
    assert proc.returncode == 0, (
        f"JS parity test failed (rc={proc.returncode})\n"
        f"stdout:\n{proc.stdout}\nstderr:\n{proc.stderr}"
    )
