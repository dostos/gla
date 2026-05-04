"""`score_run()` — verdict orchestrator across file-level / prose / gave-up.

Verdict precedence (top wins):
  1. gave_up=True → solved=False, scorer=gave_up, confidence=high
  2. file_level returned solved=True → solved=True, scorer=file_level, confidence=high
  3. prose returned solved=True → solved=True, scorer=prose, confidence=medium
  4. prose any_hit but below threshold → solved=False, needs_review=True, confidence=low
  5. zero hits, no give-up → solved=False, scorer=no_signal, confidence=high

LLM-judge layer (2c) is intentionally NOT wired here — it's a separate
opt-in tier (task #43, P2).
"""
from __future__ import annotations

from dataclasses import dataclass

import pytest

from gpa.eval.scorer import ScoreResult, score_run


# Light-weight stand-in for ScenarioMetadata.fix
@dataclass
class _Fix:
    files: list
    fix_pr_url: str = ""
    fix_sha: str = ""
    bug_class: str = "framework-internal"


def _fr_solved(files):
    return ScoreResult(
        solved=True, file_score=1.0,
        file_hits=tuple(files), file_misses=(), file_extras=(),
        out_of_tree=(),
    )


def _fr_failed(misses):
    return ScoreResult(
        solved=False, file_score=0.0,
        file_hits=(), file_misses=tuple(misses), file_extras=(),
        out_of_tree=(),
    )


# ---------------------------------------------------------------------------
# Gave-up veto
# ---------------------------------------------------------------------------


def test_gave_up_vetoes_positive_file_level():
    """Even when file_level says solved=True, a give-up phrase in the
    diagnosis tail forces solved=False."""
    fix = _Fix(files=["src/render/draw_fill.ts"])
    out = score_run(
        diagnosis_text=(
            "DIAGNOSIS: matrix order swap — but I cannot provide a "
            "specific diagnosis without source access."
        ),
        fix=fix,
        file_score=_fr_solved(fix.files),
    )
    assert out.solved is False
    assert out.scorer == "gave_up"
    assert out.gave_up is True
    assert out.confidence == "high"


def test_gave_up_with_no_other_signal():
    fix = _Fix(files=["src/render/draw_fill.ts"])
    out = score_run(
        diagnosis_text=(
            "I can't give a concrete fix without access to the codebase."
        ),
        fix=fix,
        file_score=None,
    )
    assert out.scorer == "gave_up"
    assert out.solved is False


# ---------------------------------------------------------------------------
# File-level wins when solved
# ---------------------------------------------------------------------------


def test_file_level_solved_wins():
    fix = _Fix(files=["src/render/draw_fill.ts"])
    out = score_run(
        diagnosis_text="DIAGNOSIS: render-pass mismatch. FIX: at line 42.",
        fix=fix,
        file_score=_fr_solved(fix.files),
    )
    assert out.solved is True
    assert out.scorer == "file_level"
    assert out.confidence == "high"
    assert out.file_score == 1.0


# ---------------------------------------------------------------------------
# Prose path: file_level missing or failed → prose tries
# ---------------------------------------------------------------------------


def test_prose_solved_when_file_level_absent():
    """No JSON tail → file_level is None → fall through to prose
    extractor on `diagnosis_text`."""
    fix = _Fix(files=["src/render/draw_fill.ts", "src/render/painter.ts"])
    text = (
        "After tracing the bug, the issue lives in `src/render/draw_fill.ts` "
        "and `src/render/painter.ts`."
    )
    out = score_run(
        diagnosis_text=text, fix=fix, file_score=None,
    )
    assert out.solved is True
    assert out.scorer == "prose"
    assert out.confidence == "medium"


def test_prose_any_hit_routes_to_needs_review():
    """1 of 3 files cited — recall too low to mark solved, but it's not
    a clear miss either."""
    fix = _Fix(files=[
        "src/render/draw_fill.ts",
        "src/render/draw_line.ts",
        "src/render/painter.ts",
    ])
    out = score_run(
        diagnosis_text="Bug is in `src/render/draw_fill.ts`.",
        fix=fix,
        file_score=_fr_failed(fix.files),
    )
    assert out.solved is False
    assert out.needs_review is True
    assert out.confidence == "low"


# ---------------------------------------------------------------------------
# Clear miss
# ---------------------------------------------------------------------------


def test_no_signal_no_review():
    """Zero hits + no give-up + no file-level signal → clear miss with
    high confidence."""
    fix = _Fix(files=["src/render/draw_fill.ts"])
    out = score_run(
        diagnosis_text="The bug is in `src/totally_unrelated.ts`.",
        fix=fix,
        file_score=None,
    )
    assert out.solved is False
    assert out.scorer == "no_signal"
    assert out.confidence == "high"
    assert out.needs_review is False


def test_no_fix_metadata_no_signal():
    """Scenarios without fix.files can't be scored by this orchestrator
    at all."""
    out = score_run(
        diagnosis_text="anything", fix=None, file_score=None,
    )
    assert out.solved is False
    assert out.scorer == "no_signal"


# ---------------------------------------------------------------------------
# File-level fails → prose still considered
# ---------------------------------------------------------------------------


def test_file_level_failed_falls_through_to_prose():
    """If the JSON tail parsed but listed wrong files, prose still
    has a chance to find the right answer in the prose part."""
    fix = _Fix(files=["src/render/draw_fill.ts"])
    out = score_run(
        diagnosis_text=(
            "After investigation, the bug is actually in "
            "`src/render/draw_fill.ts`.\n"
            "```json\n"
            '{"proposed_patches":[{"file":"src/totally_unrelated.ts"}]}\n'
            "```"
        ),
        fix=fix,
        file_score=_fr_failed(fix.files),
    )
    assert out.solved is True
    assert out.scorer == "prose"
