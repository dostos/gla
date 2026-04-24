"""Maintainer-framing scorer — file-overlap + optional semantic-match.

Replaces keyword-overlap scoring for scenarios that carry a `## Fix`
section (see `docs/superpowers/specs/2026-04-21-maintainer-framing-design.md`).

Primary entry point: :func:`score_maintainer_patch`. Given the agent's
final JSON object and the scenario's ground-truth :class:`FixMetadata`,
returns a :class:`ScoreResult` with file-level hits/misses and a verdict.

The semantic-match stage is optional and gated behind an explicit LLM
client — :func:`judge_semantic_match` returns ``"none"`` when no client
is supplied, so callers who cannot afford a judge call still get
deterministic output.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

from gpa.eval.scenario import FixMetadata


# File-overlap threshold at which a run is considered solved.
# 0.5 matches the spec: "a 2-file fix where agent got 1 is 0.5, scored
# as a partial solve."
_DEFAULT_SOLVE_THRESHOLD = 0.5


@dataclass
class ScoreResult:
    """Outcome of scoring an agent's proposed patches against ground truth.

    Attributes:
        solved: Primary boolean verdict — true when ``file_score`` meets
            the solve threshold (default 0.5).
        file_score: Fraction of ground-truth files the agent hit,
            in ``[0.0, 1.0]``.  ``0.0`` when ground truth is empty
            (can't score against an empty target).
        file_hits: Ground-truth files the agent correctly named
            (intersection of proposed and ground truth).
        file_misses: Ground-truth files the agent missed
            (ground truth minus proposed).
        file_extras: Files the agent proposed that are NOT in ground
            truth.  Out-of-tree paths (see below) are excluded from this
            list — they live in ``out_of_tree`` instead.
        out_of_tree: Proposed file paths that resolve outside the
            framework snapshot root.  These never count toward
            ``file_score`` regardless of whether their basename happens
            to match a ground-truth entry.
        semantic_match: LLM-judged semantic-match verdict, or ``None``
            when the judge was not run.  One of ``"full"``, ``"partial"``,
            ``"none"``, or ``None``.
        reasoning: Human-readable explanation of the verdict.
    """

    solved: bool
    file_score: float
    file_hits: list[str] = field(default_factory=list)
    file_misses: list[str] = field(default_factory=list)
    file_extras: list[str] = field(default_factory=list)
    out_of_tree: list[str] = field(default_factory=list)
    semantic_match: Optional[str] = None
    reasoning: str = ""


# ---------------------------------------------------------------------------
# JSON-tail parsing helpers
# ---------------------------------------------------------------------------


def _extract_json_tail(text: str) -> Optional[dict]:
    """Return the last top-level JSON object in ``text``, or None.

    The maintainer prompt instructs the agent to end with a single JSON
    object on the last line.  We allow some sloppiness (leading/trailing
    whitespace, surrounding markdown fences) so that near-miss formatting
    doesn't drop an otherwise-correct answer.

    Strategy:
      1. Scan from the end for a ``{`` that starts a balanced JSON
         object reaching the end of the string.
      2. ``json.loads`` that substring.
      3. Return None if no parse succeeds.
    """
    import json as _json

    if not isinstance(text, str) or not text.strip():
        return None

    stripped = text.rstrip()
    # Strip trailing code fence if present.
    if stripped.endswith("```"):
        stripped = stripped[:-3].rstrip()

    # Walk backwards looking for a matching '{' that starts a balanced
    # object ending at the end of the string.
    depth = 0
    end_idx: Optional[int] = None
    start_idx: Optional[int] = None
    in_str = False
    str_char = ""
    # Find the last '}' that anchors the object.
    for i in range(len(stripped) - 1, -1, -1):
        c = stripped[i]
        if c == "}":
            end_idx = i
            break
    if end_idx is None:
        return None

    # Walk forward from the start of likely JSON candidates.  Simpler to
    # just try each '{' from the latest backwards until one parses.
    candidate_starts = [
        i for i, c in enumerate(stripped[: end_idx + 1]) if c == "{"
    ]
    for s in reversed(candidate_starts):
        snippet = stripped[s : end_idx + 1]
        try:
            obj = _json.loads(snippet)
        except ValueError:
            continue
        if isinstance(obj, dict):
            return obj
    return None


# ---------------------------------------------------------------------------
# Public scoring API
# ---------------------------------------------------------------------------


def _normalise_rel_path(p: str) -> str:
    """Normalise a relative file path: strip ``./``, collapse slashes.

    Leaves absolute paths alone — the out-of-tree check will pick them up.
    """
    if not p:
        return ""
    # Windows-style separators get converted to POSIX for the overlap check.
    q = p.replace("\\", "/")
    # Strip a single leading "./"
    if q.startswith("./"):
        q = q[2:]
    # Collapse duplicate slashes
    while "//" in q:
        q = q.replace("//", "/")
    return q


def _is_out_of_tree(path: str, snapshot_root: Optional[Path]) -> bool:
    """Return True if ``path`` resolves outside ``snapshot_root``.

    When ``snapshot_root`` is None, the out-of-tree check is disabled and
    this always returns False (the caller didn't configure it).

    Absolute paths that don't start with the snapshot root are always
    out of tree.  Paths that try to traverse above the root via ``..``
    are also flagged.  A plain relative path like ``src/foo.js`` is
    in-tree only if it resolves to an existing or at-least-contained
    location under the root — we use string-prefix containment after
    resolving, without requiring the file to exist.
    """
    if snapshot_root is None:
        return False
    if not path:
        return True

    # Scenario-dir and repo-relative paths we explicitly reject as out of tree
    # per spec: agent must propose framework-internal files, not scenario files
    # or user app code.
    norm = _normalise_rel_path(path)
    # Reject files commonly produced by the scenario harness itself.
    if norm in {"main.c"} or norm.startswith("tests/") or norm.startswith("tests\\"):
        return True

    try:
        target = (snapshot_root / path).resolve()
        root_resolved = snapshot_root.resolve()
    except (OSError, ValueError):
        return True
    # Containment check — target must be inside root.
    try:
        target.relative_to(root_resolved)
    except ValueError:
        return True
    return False


def score_maintainer_patch(
    agent_output_json: Any,
    ground_truth_fix: FixMetadata,
    snapshot_root: Optional[Path] = None,
    solve_threshold: float = _DEFAULT_SOLVE_THRESHOLD,
) -> ScoreResult:
    """Score a maintainer-framing agent response against ground truth.

    Args:
        agent_output_json: Parsed final JSON object from the agent, OR
            the raw agent text (a string, which this function will try
            to extract the JSON tail from).  Passing a dict is preferred;
            the string path exists so harnesses don't need to duplicate
            the JSON-tail extraction logic.
        ground_truth_fix: The scenario's parsed ``## Fix`` metadata.
        snapshot_root: Optional root of the framework snapshot.  When
            provided, any proposed file path not resolving inside this
            root is listed in :attr:`ScoreResult.out_of_tree` and
            excluded from ``file_score`` (treated as wrong target).
        solve_threshold: Minimum ``file_score`` for ``solved=True``.
            Defaults to 0.5 per the maintainer-framing spec.

    Returns:
        A :class:`ScoreResult`.  Never raises — malformed inputs yield
        ``solved=False`` with a diagnostic ``reasoning``.
    """
    # Accept either a dict (already-parsed) or a raw string (try to parse
    # the JSON tail).
    parsed: Optional[dict]
    if isinstance(agent_output_json, dict):
        parsed = agent_output_json
    elif isinstance(agent_output_json, str):
        parsed = _extract_json_tail(agent_output_json)
    else:
        parsed = None

    if parsed is None:
        return ScoreResult(
            solved=False,
            file_score=0.0,
            reasoning=(
                "no parseable JSON object at end of agent response "
                "(malformed or missing)"
            ),
        )

    patches = parsed.get("proposed_patches")
    if not isinstance(patches, list):
        return ScoreResult(
            solved=False,
            file_score=0.0,
            reasoning=(
                "agent response JSON missing `proposed_patches` list "
                f"(got: {type(patches).__name__})"
            ),
        )

    # Extract proposed file paths, filtering out entries that don't have a
    # `file` key or whose `file` value is empty / non-string.
    proposed_raw: list[str] = []
    for entry in patches:
        if not isinstance(entry, dict):
            continue
        f = entry.get("file")
        if isinstance(f, str) and f.strip():
            proposed_raw.append(f.strip())

    # Classify each proposed path as in-tree vs out-of-tree.
    out_of_tree: list[str] = []
    in_tree_norm: list[str] = []
    for p in proposed_raw:
        if _is_out_of_tree(p, snapshot_root):
            out_of_tree.append(p)
        else:
            in_tree_norm.append(_normalise_rel_path(p))

    gt_norm = [_normalise_rel_path(f) for f in (ground_truth_fix.files or [])]
    gt_set = set(gt_norm)

    # Hits: ground-truth files that appear in the in-tree proposed set.
    in_tree_set = set(in_tree_norm)
    hits = sorted(gt_set & in_tree_set)
    misses = sorted(gt_set - in_tree_set)
    extras = sorted(in_tree_set - gt_set)

    if not gt_norm:
        # Scoring against an empty ground-truth list is not meaningful.
        # Return 0.0 and solved=False; callers (e.g. legacy scenarios
        # with bug_class=legacy) should not be routing through this
        # scorer.
        return ScoreResult(
            solved=False,
            file_score=0.0,
            file_hits=[],
            file_misses=[],
            file_extras=extras,
            out_of_tree=out_of_tree,
            reasoning=(
                "ground-truth fix has no files listed — maintainer scorer "
                "is not applicable (bug_class may be 'legacy')"
            ),
        )

    file_score = len(hits) / len(gt_norm)
    solved = file_score >= solve_threshold

    if solved:
        reasoning = (
            f"hit {len(hits)}/{len(gt_norm)} ground-truth files "
            f"(score {file_score:.2f} >= {solve_threshold:.2f})"
        )
    elif not in_tree_norm and out_of_tree:
        reasoning = (
            f"all {len(out_of_tree)} proposed file(s) were out of the "
            "framework tree (excluded from scoring)"
        )
    else:
        reasoning = (
            f"hit {len(hits)}/{len(gt_norm)} ground-truth files "
            f"(score {file_score:.2f} < {solve_threshold:.2f})"
        )

    return ScoreResult(
        solved=solved,
        file_score=file_score,
        file_hits=hits,
        file_misses=misses,
        file_extras=extras,
        out_of_tree=out_of_tree,
        semantic_match=None,
        reasoning=reasoning,
    )


# ---------------------------------------------------------------------------
# Semantic-match judge (optional, LLM-driven)
# ---------------------------------------------------------------------------


_VALID_JUDGE_VERDICTS = {"full", "partial", "none"}


def judge_semantic_match(
    agent_change_summary: str,
    ground_truth_change_summary: str,
    llm_client: Any = None,
) -> str:
    """Return a semantic-match verdict: ``"full"`` | ``"partial"`` | ``"none"``.

    When ``llm_client`` is None (the default) this returns ``"none"``
    silently — the deterministic fallback.  Callers that want the LLM
    judgement must pass an explicit client.

    The client is expected to duck-type to
    :class:`gpa.eval.curation.llm_client.LLMClient`: it must have a
    ``.complete(system=..., messages=...)`` method returning an object
    with a ``.text`` attribute.

    The judge prompt is intentionally terse and asks for a single token
    verdict; see :mod:`gpa.eval.judge` for the canonical prompt text.
    """
    if llm_client is None:
        return "none"
    if not isinstance(agent_change_summary, str):
        agent_change_summary = str(agent_change_summary)
    if not isinstance(ground_truth_change_summary, str):
        ground_truth_change_summary = str(ground_truth_change_summary)

    # Delegate to the thin judge-module wrapper so the prompt lives in
    # exactly one place.
    from gpa.eval.judge import run_semantic_judge

    verdict = run_semantic_judge(
        agent_change_summary=agent_change_summary,
        ground_truth_change_summary=ground_truth_change_summary,
        llm_client=llm_client,
    )
    if verdict not in _VALID_JUDGE_VERDICTS:
        return "none"
    return verdict


__all__ = [
    "ScoreResult",
    "score_maintainer_patch",
    "judge_semantic_match",
]
