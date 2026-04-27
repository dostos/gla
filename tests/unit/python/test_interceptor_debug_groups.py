"""Python wrapper that runs the JS debug-marker interceptor parity test.

The actual test logic lives in
``tests/unit/shims/test_interceptor_debug_groups.js`` — a node + vm
sandbox harness that loads ``src/shims/webgl/extension/interceptor.js``
and drives push/pop/draw sequences against a stubbed WebGL context.
This wrapper just shells out to ``node`` (skipping if unavailable) so
the JS test runs as part of the regular ``pytest`` suite.

The JS test verifies the WebGL interceptor's per-drawcall
``debug_groups`` snapshot matches the wire-format the engine consumes
(``NormalizedDrawCall::debug_groups`` and the
``gpa.backends.base.DrawCall.debug_groups`` field — both snake_case).
"""
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
JS_TEST = (
    REPO_ROOT / "tests" / "unit" / "shims" / "test_interceptor_debug_groups.js"
)


def _have_node() -> bool:
    return shutil.which("node") is not None


@pytest.mark.skipif(not _have_node(), reason="node not installed")
def test_js_interceptor_debug_groups():
    """Run the JS debug-marker harness and assert it exits 0.

    Cases cover the full acceptance matrix for the Tier-3 link
    primitive: empty stack, single push+pop, nested push+pop, draw
    after pop reverts to outer group, popDebugGroup on empty stack
    increments debugGroupErrors, WebGL1 + EXT_debug_marker fallback
    populates the same field, WebGL1 without EXT_debug_marker is a
    silent no-op, the per-frame error counter resets between sends,
    and the message-coercion helper handles 0-arg + single-arg
    fallback paths.
    """
    assert JS_TEST.exists(), f"missing JS parity harness: {JS_TEST}"
    proc = subprocess.run(
        ["node", str(JS_TEST)],
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert proc.returncode == 0, (
        f"JS interceptor debug-group test failed (rc={proc.returncode})\n"
        f"stdout:\n{proc.stdout}\nstderr:\n{proc.stderr}"
    )
