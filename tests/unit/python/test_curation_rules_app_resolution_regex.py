"""`app_resolution` regex must match maintainer-response phrasing only,
not bare keywords in user-report prose.

R12 codex-mined cohort surfaced that the bare-token literals
(`use `, `set `, `enable `, `disable `, `configure ` with trailing
space, no right-anchor word boundary) hit almost any English issue body
("Enable Glow", "Use a custom terrain source") and forced
`infer_bug_class` to return `consumer-misuse` even when the fix-PR
patches framework code.

This test pins the new regex's behavior for the concrete failure cases
plus the canonical positives.
"""
from __future__ import annotations

import re

import pytest

from gpa.eval.curation.rules import infer_bug_class, load_rules


# Canonical user-report prose that triggered false `consumer-misuse`
# in R12 — these must NOT match the tightened regex.
_USER_PROSE_THAT_PREVIOUSLY_FALSE_POSITIVED = [
    "Enable Glow in the Environment panel and the engine crashes",
    "Use a custom 3D terrain source with a raster background — bug appears",
    "Set the camera position to (0, 5, 0) and the artifact appears",
    "Disable shadow casting on the mesh and re-render",
    "Configure the renderer with antialias=true to reproduce",
    "I tried to enable depth testing but the result is wrong",
]

# Real maintainer-response phrasing — these MUST still match.
_MAINTAINER_RESPONSE_PHRASES = [
    "Closing as not a bug.",
    "This is by design.",
    "Works as expected — see the docs.",
    "won't fix — out of scope",
    "wontfix",
    "Please use the `setSize` API instead.",
    "You should use `colorSpace` rather than `outputEncoding`.",
    "you should set `depthWrite` to false in this case",
    "please configure the renderer with antialias",
    "Please enable the gl_FragDepth extension.",
    "user error: the index buffer was Uint16Array",
]

_ACCEPTED_ANSWER_MARKER = "=== Accepted Answer ==="


@pytest.fixture(scope="module")
def app_resolution_re():
    rules = load_rules()
    pat = rules.patterns.get("app_resolution")
    assert pat, "app_resolution pattern missing from mining_rules.yaml"
    return re.compile(pat, flags=re.IGNORECASE)


@pytest.mark.parametrize("text", _USER_PROSE_THAT_PREVIOUSLY_FALSE_POSITIVED)
def test_user_prose_does_not_match_app_resolution(app_resolution_re, text):
    """Bare `Enable`/`Use`/`Set`/etc. in user-report prose must not
    flip a framework-internal bug into `consumer-misuse`."""
    assert app_resolution_re.search(text) is None, (
        f"unexpected match in user prose: {text!r}"
    )


@pytest.mark.parametrize("text", _MAINTAINER_RESPONSE_PHRASES)
def test_maintainer_response_matches_app_resolution(app_resolution_re, text):
    """Genuine maintainer-resolution phrasing must still match — that's
    what `infer_bug_class` keys on for the consumer-misuse path."""
    assert app_resolution_re.search(text) is not None, (
        f"expected match in maintainer phrasing: {text!r}"
    )


def test_accepted_answer_still_matches(app_resolution_re):
    """Stack Overflow's `=== Accepted Answer` marker is the canonical
    consumer-misuse signal for SO-sourced candidates."""
    assert app_resolution_re.search(_ACCEPTED_ANSWER_MARKER) is not None


# ---------------------------------------------------------------------------
# Functional: infer_bug_class no longer fires `consumer-misuse` on the
# R12 false-positive bodies.
# ---------------------------------------------------------------------------


def test_infer_bug_class_no_longer_consumer_misuse_on_glow_body():
    """The R12 godot world_environment_glow body said `Enable Glow`. The
    issue is in framework-maintenance category; with the regex tightened,
    it should fall through to `framework-internal`."""
    body = (
        "When you Enable Glow on the World Environment, the rendering "
        "produces incorrect output."
    )
    out = infer_bug_class(
        category="framework-maintenance",
        source_type="issue",
        text=body,
        url="https://github.com/godotengine/godot/issues/12345",
    )
    assert out == "framework-internal"


def test_infer_bug_class_no_longer_consumer_misuse_on_terrain_body():
    """The R12 maplibre 3d_terrain body said `Use a custom 3D terrain
    source`. Should resolve to framework-internal now."""
    body = (
        "Use a custom 3D terrain source with a partially transparent "
        "raster background and stripes appear."
    )
    out = infer_bug_class(
        category="framework-maintenance",
        source_type="issue",
        text=body,
        url="https://github.com/maplibre/maplibre-gl-js/issues/5746",
    )
    assert out == "framework-internal"


def test_infer_bug_class_still_consumer_misuse_on_real_maintainer_response():
    """An issue that's actually closed with a maintainer 'use the X API'
    response should still be classified consumer-misuse. (Use a body
    that avoids `config_terms` keywords so the test is decoupled from
    the user-config branch.)"""
    body = (
        "Maintainer comment: This is by design — please use the "
        "`updateProjectionMatrix` method instead of mutating the matrix "
        "directly."
    )
    out = infer_bug_class(
        category="framework-maintenance",
        source_type="issue",
        text=body,
        url="https://github.com/maplibre/maplibre-gl-js/issues/5747",
    )
    assert out == "consumer-misuse"


def test_infer_bug_class_so_with_accepted_answer_still_consumer_misuse():
    """Stack Overflow path keys on the `=== Accepted Answer` marker."""
    body = "Some question body\n\n=== Accepted Answer ===\nDo X."
    out = infer_bug_class(
        category="framework-maintenance",
        source_type="stackoverflow",
        text=body,
        url="https://stackoverflow.com/questions/123",
    )
    # SO + accepted answer hits `app_side` → consumer-misuse path
    assert out == "consumer-misuse"
