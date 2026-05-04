"""`is_gave_up()` — veto signal for the score orchestrator.

R12 surfaced two scenarios where the agent bailed out with boilerplate
("no upstream snapshot accessible", "cannot investigate without source")
yet the legacy keyword scorer marked them ✓ on lexical accident. The
gave-up detector vetoes any positive verdict by inspecting the tail of
the diagnosis_text for a small bank of bail-out patterns.
"""
from __future__ import annotations

import pytest

from gpa.eval.scorer_giveup import is_gave_up


_GAVE_UP_BODIES = [
    "DIAGNOSIS: no upstream snapshot accessible. FIX: investigate locally.",
    "I cannot investigate without source code being available.",
    "The upstream snapshot is not accessible; speculative diagnosis follows.",
    "Unable to read the upstream repo. Final answer: speculative.",
    "I have no access to the framework code, so I'll guess.",
    "I cannot provide a specific diagnosis without seeing the implementation.",
    "I can't give a concrete fix without access to the codebase, sorry.",
    "Without access to the source repo I cannot pinpoint the bug.",
    "This is a speculative answer based on pattern matching alone.",
    "This is a guess — I don't have the framework source.",
]

_REAL_DIAGNOSES = [
    # Genuine answers that mention "without" / "cannot" but aren't bail-outs.
    "DIAGNOSIS: matrix multiply order is reversed in renderForwardMobile.cpp. "
    "FIX: swap the operands at line 423.",
    "The bug is that `setColorSpace` is called on the canvas, not the renderer. "
    "Without this fix, the framebuffer keeps the linear encoding.",
    "Speculatively, the index buffer overflowed Uint16 — but checking the "
    "draw-call list confirms it. FIX: use Uint32Array.",
    # "I cannot reproduce" is a comment, not a give-up.
    "I cannot reproduce the bug, but the diff shows that depthWrite was "
    "added in commit abc123. FIX: revert that line.",
]


@pytest.mark.parametrize("text", _GAVE_UP_BODIES)
def test_gave_up_patterns_match(text):
    assert is_gave_up(text) is True, f"expected gave-up: {text!r}"


@pytest.mark.parametrize("text", _REAL_DIAGNOSES)
def test_real_diagnoses_not_marked_gave_up(text):
    assert is_gave_up(text) is False, f"unexpected gave-up flag: {text!r}"


def test_only_inspects_tail():
    """A gave-up phrase early in a long diagnosis should NOT veto if
    the tail has a real answer. (Limit reduces false positives where
    the agent says 'I was about to give up' before solving.)"""
    text = (
        "I almost said 'I cannot provide a specific diagnosis' "
        "but then I found the bug.\n"
        "...\n"
        + ("real analysis " * 200)
        + "DIAGNOSIS: matrix multiply ordering. FIX: swap operands."
    )
    assert is_gave_up(text) is False


def test_empty_text():
    assert is_gave_up("") is False


def test_none_text():
    assert is_gave_up(None) is False
