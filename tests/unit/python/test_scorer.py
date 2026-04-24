"""Tests for :mod:`gpa.eval.scorer` — maintainer-framing file-overlap scorer.

Covers the Phase 3 contract from
``docs/superpowers/specs/2026-04-21-maintainer-framing-design.md``:

- Perfect file-match → solved with file_score=1.0.
- Partial match (1/2 files) → solved at the 0.5 threshold.
- No match → wrong, file_score=0.0.
- Out-of-tree paths (main.c, tests/...) → listed in ``out_of_tree``,
  excluded from scoring.
- Missing ``proposed_patches`` key → solved=False.
- Malformed JSON tail (string input) → solved=False, timeout-style.
- Extra proposed files → captured in ``file_extras``.
- ``classify_verdict`` integrates with scorer output.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from gpa.eval.scenario import FixMetadata
from gpa.eval.scorer import (
    ScoreResult,
    judge_semantic_match,
    score_maintainer_patch,
)
from gpa.eval.telemetry import classify_verdict


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _gt(*files: str, summary: str = "gt summary") -> FixMetadata:
    """Build a FixMetadata with the given ground-truth file list."""
    return FixMetadata(
        fix_pr_url="https://github.com/x/y/pull/1",
        fix_sha="deadbeef",
        fix_parent_sha="cafebabe",
        bug_class="framework-internal",
        files=list(files),
        change_summary=summary,
    )


def _proposal(*files: str, bug_class: str = "framework-internal") -> dict:
    """Build an agent-output JSON with the given proposed file paths."""
    return {
        "bug_class": bug_class,
        "proposed_patches": [
            {"file": f, "change_summary": f"change {f}"} for f in files
        ],
        "confidence": "medium",
        "reasoning": "mock",
    }


# ---------------------------------------------------------------------------
# Core scoring
# ---------------------------------------------------------------------------


def test_score_exact_file_match_solves():
    """Agent proposes exactly the ground-truth file set → solved=True, 1.0."""
    gt = _gt("src/a.js", "src/b.js")
    agent = _proposal("src/a.js", "src/b.js")
    r = score_maintainer_patch(agent, gt)
    assert r.solved is True
    assert r.file_score == pytest.approx(1.0)
    assert set(r.file_hits) == {"src/a.js", "src/b.js"}
    assert r.file_misses == []
    assert r.file_extras == []
    assert r.out_of_tree == []


def test_score_partial_match():
    """One of two ground-truth files hit → score 0.5, solved at threshold."""
    gt = _gt("src/a.js", "src/b.js")
    agent = _proposal("src/a.js")
    r = score_maintainer_patch(agent, gt)
    assert r.file_score == pytest.approx(0.5)
    # 0.5 is the default solve threshold — boundary is solved.
    assert r.solved is True
    assert r.file_hits == ["src/a.js"]
    assert r.file_misses == ["src/b.js"]


def test_score_no_match():
    """Agent proposes wrong file → score 0.0, solved=False."""
    gt = _gt("src/a.js")
    agent = _proposal("src/other.js")
    r = score_maintainer_patch(agent, gt)
    assert r.file_score == pytest.approx(0.0)
    assert r.solved is False
    assert r.file_hits == []
    assert r.file_misses == ["src/a.js"]
    assert r.file_extras == ["src/other.js"]


def test_out_of_tree_path_rejected(tmp_path):
    """Paths under tests/ or basename main.c land in out_of_tree, not scored."""
    # Snapshot_root is just used for path-is-inside checks.
    # A "tests/" path is rejected by policy regardless of whether the
    # resolved path is under the snapshot.
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "real.js").write_text("// ok", encoding="utf-8")
    gt = _gt("src/real.js")
    agent = _proposal("main.c", "tests/eval/foo/main.c", "src/real.js")
    r = score_maintainer_patch(agent, gt, snapshot_root=tmp_path)
    # main.c and tests/... are out of tree and must NOT count.
    assert "main.c" in r.out_of_tree
    assert "tests/eval/foo/main.c" in r.out_of_tree
    # src/real.js is a legitimate hit.
    assert r.file_hits == ["src/real.js"]
    assert r.file_score == pytest.approx(1.0)
    assert r.solved is True


def test_out_of_tree_absolute_path(tmp_path):
    """An absolute path outside the snapshot root is out-of-tree."""
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "a.js").write_text("// ok", encoding="utf-8")
    gt = _gt("src/a.js")
    # /etc/passwd is outside tmp_path — out of tree.
    agent = _proposal("/etc/passwd")
    r = score_maintainer_patch(agent, gt, snapshot_root=tmp_path)
    assert "/etc/passwd" in r.out_of_tree
    assert r.file_hits == []
    assert r.file_score == pytest.approx(0.0)
    assert r.solved is False
    # Reasoning mentions the out-of-tree classification for transparency.
    assert "out of" in r.reasoning.lower() or "tree" in r.reasoning.lower()


def test_missing_proposed_patches_key():
    """Agent JSON without `proposed_patches` → solved=False."""
    gt = _gt("src/a.js")
    agent = {"bug_class": "framework-internal", "reasoning": "forgot key"}
    r = score_maintainer_patch(agent, gt)
    assert r.solved is False
    assert r.file_score == pytest.approx(0.0)
    assert "proposed_patches" in r.reasoning


def test_malformed_json_tail():
    """Passing a raw string with no parseable JSON at the end → solved=False."""
    gt = _gt("src/a.js")
    # The maintainer-framing scorer accepts a raw string and tries to
    # extract the JSON tail.  A plain prose message has no JSON.
    agent_text = "Here is my analysis: the bug is obviously in frobnicator.c."
    r = score_maintainer_patch(agent_text, gt)
    assert r.solved is False
    assert r.file_score == pytest.approx(0.0)
    assert "json" in r.reasoning.lower()


def test_malformed_json_tail_trailing_brace_only():
    """Unbalanced JSON at the end shouldn't parse — treated like no JSON."""
    gt = _gt("src/a.js")
    agent_text = "... unbalanced }"
    r = score_maintainer_patch(agent_text, gt)
    assert r.solved is False


def test_file_extras_captured():
    """Agent proposes 3 files, 1 is ground-truth → 2 listed in file_extras."""
    gt = _gt("src/fix.js")
    agent = _proposal("src/fix.js", "src/extra1.js", "src/extra2.js")
    r = score_maintainer_patch(agent, gt)
    assert r.file_hits == ["src/fix.js"]
    assert set(r.file_extras) == {"src/extra1.js", "src/extra2.js"}
    assert r.file_score == pytest.approx(1.0)  # all ground-truth files hit
    assert r.solved is True


def test_patch_entry_without_file_key_ignored():
    """Malformed patch entry (no `file`) is silently skipped, not crashed on."""
    gt = _gt("src/a.js")
    agent = {
        "bug_class": "framework-internal",
        "proposed_patches": [
            {"file": "src/a.js", "change_summary": "ok"},
            {"change_summary": "no file key"},
            {"file": ""},  # empty
            "not a dict",
        ],
    }
    r = score_maintainer_patch(agent, gt)
    assert r.file_hits == ["src/a.js"]
    assert r.solved is True


def test_json_tail_extraction_from_string():
    """Well-formed JSON at the end of an agent response parses successfully."""
    gt = _gt("src/renderer.js")
    text = """Analysis follows ... after reviewing the snapshot I propose:

{
  "bug_class": "framework-internal",
  "proposed_patches": [
    {"file": "src/renderer.js", "change_summary": "swap draw order"}
  ],
  "confidence": "high",
  "reasoning": "matches clear-before-bg pattern"
}"""
    r = score_maintainer_patch(text, gt)
    assert r.solved is True
    assert r.file_hits == ["src/renderer.js"]


def test_json_tail_with_trailing_code_fence():
    """Trailing ``` after the JSON shouldn't break the parser."""
    gt = _gt("src/a.js")
    text = """analysis

```json
{"proposed_patches": [{"file": "src/a.js"}]}
```"""
    r = score_maintainer_patch(text, gt)
    assert r.solved is True


def test_path_normalisation_leading_dot_slash():
    """./src/a.js and src/a.js should score as the same path."""
    gt = _gt("src/a.js")
    agent = _proposal("./src/a.js")
    r = score_maintainer_patch(agent, gt)
    assert r.solved is True
    assert r.file_hits == ["src/a.js"]


def test_empty_ground_truth_returns_zero():
    """Scoring against an empty ground-truth list returns 0.0 + unsolved."""
    gt = FixMetadata(
        fix_pr_url="https://x/y/issues/1",
        bug_class="legacy",
        files=[],
        change_summary="legacy escape hatch",
    )
    agent = _proposal("src/whatever.js")
    r = score_maintainer_patch(agent, gt)
    assert r.file_score == pytest.approx(0.0)
    assert r.solved is False
    assert "legacy" in r.reasoning.lower() or "no files" in r.reasoning.lower()


def test_no_proposed_files_all_out_of_tree(tmp_path):
    """Every proposed path is out of tree → solved=False, explanatory reason."""
    (tmp_path / "src").mkdir()
    gt = _gt("src/x.js")
    agent = _proposal("main.c", "tests/fixtures/y.c")
    r = score_maintainer_patch(agent, gt, snapshot_root=tmp_path)
    assert r.solved is False
    assert r.file_score == pytest.approx(0.0)
    assert len(r.out_of_tree) == 2


# ---------------------------------------------------------------------------
# Semantic judge — deterministic path (no llm_client)
# ---------------------------------------------------------------------------


def test_judge_without_client_returns_none():
    """No llm_client → ``"none"`` returned silently, no network calls."""
    result = judge_semantic_match("agent change", "ground truth change")
    assert result == "none"


def test_judge_with_client_uses_client():
    """A fake client returning 'full' produces ``"full"``."""
    class _Client:
        def complete(self, system, messages, **kwargs):
            class R:
                text = "full"
            return R()

    result = judge_semantic_match("agent", "ground truth", llm_client=_Client())
    assert result == "full"


def test_judge_partial_verdict():
    class _Client:
        def complete(self, system, messages, **kwargs):
            class R:
                text = "After consideration the verdict is: partial"
            return R()

    result = judge_semantic_match("a", "b", llm_client=_Client())
    assert result == "partial"


def test_judge_unparseable_verdict_defaults_none():
    """Response with no recognisable verdict → defensive fallback 'none'."""
    class _Client:
        def complete(self, system, messages, **kwargs):
            class R:
                text = "I am not sure."
            return R()

    result = judge_semantic_match("a", "b", llm_client=_Client())
    assert result == "none"


def test_judge_network_error_degrades_to_none():
    """Client raising an exception must not propagate; returns 'none'."""
    class _Client:
        def complete(self, system, messages, **kwargs):
            raise RuntimeError("network")

    result = judge_semantic_match("a", "b", llm_client=_Client())
    assert result == "none"


# ---------------------------------------------------------------------------
# Verdict classifier integration
# ---------------------------------------------------------------------------


def test_classify_verdict_uses_scorer_output_solved():
    """score_result.solved=True + parsed_json=True → 'solved'."""
    gt = _gt("src/a.js")
    agent = _proposal("src/a.js")
    sr = score_maintainer_patch(agent, gt)
    run = {
        "parsed_json": True,
        "score_result": sr,
        "turns": 15,
        "result": "…",
    }
    assert classify_verdict(run) == "solved"


def test_classify_verdict_missing_json_is_timeout():
    """parsed_json=False (no JSON tail) → timeout regardless of turn count."""
    run = {
        "parsed_json": False,
        "score_result": None,
        "turns": 10,
        "result": "no json tail",
    }
    assert classify_verdict(run) == "timeout"


def test_classify_verdict_zero_file_score_is_wrong():
    """parsed_json but file_score=0 → wrong (agent named zero GT files)."""
    gt = _gt("src/a.js")
    agent = _proposal("src/other.js")
    sr = score_maintainer_patch(agent, gt)
    assert sr.file_score == 0.0
    run = {
        "parsed_json": True,
        "score_result": sr,
        "turns": 8,
        "result": "…",
    }
    assert classify_verdict(run) == "wrong"


def test_classify_verdict_partial_below_threshold_is_wrong():
    """parsed_json with file_score between 0 and solve_threshold → wrong."""
    gt = _gt("src/a.js", "src/b.js", "src/c.js")  # 3 files
    # Hit only 1 of 3 → file_score 0.333, below 0.5 threshold.
    agent = _proposal("src/a.js")
    sr = score_maintainer_patch(agent, gt)
    assert 0 < sr.file_score < 0.5
    run = {
        "parsed_json": True,
        "score_result": sr,
        "turns": 12,
        "result": "…",
    }
    assert classify_verdict(run) == "wrong"


def test_classify_verdict_score_result_as_dict():
    """score_result accepts a plain dict (not just ScoreResult dataclass)."""
    run = {
        "parsed_json": True,
        "score_result": {"solved": True, "file_score": 1.0},
        "turns": 5,
    }
    assert classify_verdict(run) == "solved"


def test_classify_verdict_legacy_signal_still_works():
    """Runs without maintainer signals keep the legacy correct-based rules."""
    # correct=True, no score_result → solved.
    assert classify_verdict({"correct": True, "turns": 10, "result": "ok"}) == "solved"
    # correct=False, no score_result, at budget → timeout.
    assert classify_verdict({"correct": False, "turns": 40, "result": ""}) == "timeout"
    # correct=False, no score_result, early stop → wrong.
    assert classify_verdict({"correct": False, "turns": 15, "result": "x"}) == "wrong"
