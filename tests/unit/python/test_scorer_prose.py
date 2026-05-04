"""`score_prose()` — free-form prose path/symbol extraction.

When the agent emits prose-only diagnosis (no JSON tail), `score_run`
falls through to this scorer. It mines:

- relative paths with known source extensions
- bare basenames the agent cites
- backticked symbols (CamelCase, snake_case, dotted)

then intersects with the ground-truth file list to compute file_hits +
precision + recall. FP guards reject too-common basenames (`index.ts`,
`utils.js`) and single-word symbols (`update`, `render`). Out-of-tree
paths (anything not under the snapshot's filesystem layout, conceptually)
are reported separately rather than counted as misses.
"""
from __future__ import annotations

import pytest

from gpa.eval.scorer_prose import score_prose


# ---------------------------------------------------------------------------
# Path extraction
# ---------------------------------------------------------------------------


def test_exact_path_match_counts_as_hit():
    text = "The bug is in `src/render/draw_fill.ts` at line 123."
    out = score_prose(
        text, gt_files=["src/render/draw_fill.ts"]
    )
    assert "src/render/draw_fill.ts" in out.file_hits
    assert out.recall == 1.0


def test_unquoted_path_match():
    """Paths can appear without backticks too."""
    text = "The diff lands in src/render/draw_fill.ts and src/render/painter.ts."
    out = score_prose(
        text,
        gt_files=["src/render/draw_fill.ts", "src/render/painter.ts"],
    )
    assert out.recall == 1.0


def test_basename_match_when_directory_omitted():
    """Agent cites `Picking.js` without the directory prefix —
    intersect against gt basenames."""
    text = "The cache invalidation bug lives in `Picking.js`."
    out = score_prose(
        text,
        gt_files=["packages/engine/Source/Scene/Picking.js"],
    )
    assert "packages/engine/Source/Scene/Picking.js" in out.file_hits


def test_common_basename_stoplisted():
    """`index.ts` is too common to count — without a directory prefix,
    citing `index.ts` shouldn't auto-hit."""
    text = "The bug is in `index.ts` somewhere."
    out = score_prose(
        text,
        gt_files=["packages/engine/Source/index.ts"],
    )
    assert out.file_hits == set()


# ---------------------------------------------------------------------------
# Recall / precision
# ---------------------------------------------------------------------------


def test_recall_partial():
    text = "The bug is in `src/a.ts` and `src/b.ts`."
    out = score_prose(
        text, gt_files=["src/a.ts", "src/b.ts", "src/c.ts"],
    )
    # 2/3 cited
    assert out.recall == pytest.approx(2 / 3)


def test_precision_drops_when_agent_lists_many_files():
    """Listing every framework file shouldn't pass — precision floor
    rejects shotgun answers."""
    text = (
        "The bug could be in any of: `src/a.ts`, `src/b.ts`, `src/c.ts`, "
        "`src/d.ts`, `src/e.ts`, `src/f.ts`, `src/g.ts`."
    )
    out = score_prose(text, gt_files=["src/a.ts"])
    assert out.recall == 1.0
    assert out.precision < 0.25
    assert out.solved is False


def test_solved_when_recall_and_precision_high():
    """recall ≥ 0.5 AND precision ≥ 0.25 → solved=True."""
    text = "Bug is in `src/render/draw_fill.ts` and `src/render/painter.ts`."
    out = score_prose(
        text,
        gt_files=["src/render/draw_fill.ts", "src/render/painter.ts"],
    )
    assert out.solved is True


def test_not_solved_when_recall_below_threshold():
    """1 of 3 files cited → recall=0.33 → not solved even with
    precision=1.0."""
    text = "Bug is in `src/render/draw_fill.ts`."
    out = score_prose(
        text,
        gt_files=[
            "src/render/draw_fill.ts",
            "src/render/draw_line.ts",
            "src/render/painter.ts",
        ],
    )
    assert out.precision == 1.0
    assert out.recall == pytest.approx(1 / 3)
    assert out.solved is False
    # Still has any_hit signal — orchestrator may use this for needs_review.
    assert out.any_hit is True


def test_no_hits_at_all():
    text = "I think the issue is in `src/something_else.ts`."
    out = score_prose(text, gt_files=["src/render/draw_fill.ts"])
    assert out.file_hits == set()
    assert out.recall == 0.0
    assert out.any_hit is False


def test_empty_diagnosis():
    out = score_prose("", gt_files=["src/foo.ts"])
    assert out.file_hits == set()
    assert out.solved is False


def test_empty_gt_files():
    """No ground truth → can't score anything — orchestrator should
    skip prose scoring in this case, but the helper itself returns a
    benign zero."""
    out = score_prose("any text here", gt_files=[])
    assert out.file_hits == set()
    assert out.solved is False


# ---------------------------------------------------------------------------
# Robustness — agent quoting the user report
# ---------------------------------------------------------------------------


def test_user_report_quote_does_not_inflate_hits():
    """When the agent verbatim-quotes the user report, paths inside
    the quoted block shouldn't count as the agent's identification.
    The scorer doesn't see the user report directly — but the
    backticked-path heuristic still uses surrounding context to
    distinguish citation from quotation. This test pins behavior:
    the path is cited at least once outside any quote so the hit is
    real."""
    text = (
        "User report says the bug is in `src/foo.ts`.\n"
        "After investigating, I confirm: `src/foo.ts` line 42 is wrong."
    )
    out = score_prose(text, gt_files=["src/foo.ts"])
    # The path appears citation-style; the hit is correct.
    assert "src/foo.ts" in out.file_hits


# ---------------------------------------------------------------------------
# FP guards — common-basename stoplist
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "stop_basename",
    ["index.ts", "main.c", "utils.js", "types.ts", "helper.h",
     "index.js", "config.js"],
)
def test_common_basename_alone_does_not_hit(stop_basename):
    text = f"Bug is in `{stop_basename}`."
    out = score_prose(text, gt_files=[f"packages/engine/Source/{stop_basename}"])
    assert out.file_hits == set()
