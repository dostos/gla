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
    "ScoreVerdict",
    "score_maintainer_patch",
    "judge_semantic_match",
    "score_run",
    "judge_residual",
]


# ---------------------------------------------------------------------------
# LLM-judge residual upgrader (cost-bounded, opt-in)
# ---------------------------------------------------------------------------


def _judge_cache_key(fix_sha: str, diagnosis_text: str) -> str:
    import hashlib
    h = hashlib.sha256()
    h.update((fix_sha or "").encode("utf-8"))
    h.update(b"\n--\n")
    h.update((diagnosis_text or "").encode("utf-8"))
    return h.hexdigest()


def judge_residual(
    verdict: ScoreVerdict,
    *,
    fix: Any,
    diagnosis_text: str,
    snapshot_root: Any,
    llm_client: Any,
    cache_dir: Any = None,
    max_diff_bytes: int = 6000,
) -> ScoreVerdict:
    """Upgrade a `needs_review` prose verdict via LLM semantic judge.

    Eligibility (all required):
      - verdict.scorer == "prose" AND verdict.needs_review
      - fix has fix_sha
      - snapshot_root exists
      - llm_client is non-None

    On `full` → solved=True, scorer="judge", confidence="medium".
    On `partial`/`none` → keeps solved=False; records `judge_verdict`.

    Disk cache (when `cache_dir` is set) keyed on
    sha256(fix_sha + diagnosis_text). Repeat invocations skip the LLM.
    """
    # Eligibility: any "we have evidence but couldn't auto-decide"
    # verdict — prose/file_level/no_signal — provided needs_review=True
    # and we have everything required to fetch the real fix-PR diff.
    if not (
        verdict.scorer in ("prose", "file_level", "no_signal")
        and verdict.needs_review
        and llm_client is not None
        and snapshot_root
        and fix is not None
        and getattr(fix, "fix_sha", None)
    ):
        return verdict

    cache_path = None
    if cache_dir is not None:
        from pathlib import Path
        cache_dir = Path(cache_dir)
        try:
            cache_dir.mkdir(parents=True, exist_ok=True)
            key = _judge_cache_key(fix.fix_sha, diagnosis_text or "")
            cache_path = cache_dir / f"{key}.txt"
            if cache_path.exists():
                cached = cache_path.read_text(encoding="utf-8").strip()
                if cached in {"full", "partial", "none"}:
                    return _apply_judge_verdict(verdict, cached)
        except OSError:
            cache_path = None

    from gpa.eval import judge as judge_mod
    gt_summary = judge_mod.fetch_pr_diff_summary(
        fix.fix_sha, snapshot_root, max_bytes=max_diff_bytes,
    )
    if not gt_summary:
        return verdict
    judged = judge_mod.run_semantic_judge(
        agent_change_summary=(diagnosis_text or "")[:max_diff_bytes],
        ground_truth_change_summary=gt_summary,
        llm_client=llm_client,
    )
    if cache_path is not None:
        try:
            cache_path.write_text(judged, encoding="utf-8")
        except OSError:
            pass
    return _apply_judge_verdict(verdict, judged)


def _apply_judge_verdict(verdict: ScoreVerdict, judged: str) -> ScoreVerdict:
    """Build the upgraded ScoreVerdict from a raw judge-tag."""
    if judged not in {"full", "partial", "none"}:
        return verdict
    if judged == "full":
        return ScoreVerdict(
            scorer="judge", solved=True, confidence="medium",
            file_score=verdict.file_score,
            prose_recall=verdict.prose_recall,
            prose_precision=verdict.prose_precision,
            judge_verdict="full",
            gave_up=verdict.gave_up, needs_review=False,
            reasoning="LLM judge: full match against fix-PR diff",
        )
    return ScoreVerdict(
        scorer=verdict.scorer, solved=False, confidence="low",
        file_score=verdict.file_score,
        prose_recall=verdict.prose_recall,
        prose_precision=verdict.prose_precision,
        judge_verdict=judged,
        gave_up=verdict.gave_up, needs_review=True,
        reasoning=f"LLM judge: {judged} (partial overlap or no match)",
    )


# ---------------------------------------------------------------------------
# Verdict orchestrator (file-level → prose → gave-up veto)
# ---------------------------------------------------------------------------


@dataclass
class ScoreVerdict:
    """Final verdict for a single run, combining file-level + prose +
    gave-up + (optional) LLM-judge signals.

    `scorer` records which leg produced the binding answer:
      - "file_level": JSON tail parsed AND ScoreResult.solved=True.
      - "prose":      no JSON or file_level failed; prose extractor solved.
      - "judge":      LLM-judge upgraded a needs_review prose verdict.
      - "gave_up":    bail-out phrase vetoed any positive verdict.
      - "no_signal":  zero hits, no give-up, no signal at all.

    `confidence` is high for definitive ✓/✗, medium for prose- or
    judge-derived ✓ (smaller signal set), low for `needs_review` rows.
    """
    scorer: str               # file_level | prose | judge | gave_up | no_signal
    solved: bool
    confidence: str           # high | medium | low
    file_score: Optional[float] = None
    prose_recall: Optional[float] = None
    prose_precision: Optional[float] = None
    judge_verdict: Optional[str] = None  # full | partial | none
    gave_up: bool = False
    needs_review: bool = False
    reasoning: str = ""


def score_run(
    *,
    diagnosis_text: str,
    fix: Optional[FixMetadata],
    file_score: Optional[ScoreResult],
) -> ScoreVerdict:
    """Combine file-level + prose + gave-up signals into a single verdict.

    Precedence (top wins):
      1. gave_up phrase in tail → solved=False, scorer=gave_up, conf=high.
      2. file_score.solved → solved=True, scorer=file_level, conf=high.
      3. prose extractor solved (recall ≥ 0.5 AND precision ≥ 0.25)
         → solved=True, scorer=prose, conf=medium.
      4. prose any_hit but below threshold → solved=False,
         needs_review=True, conf=low.
      5. no signal at all → solved=False, scorer=no_signal, conf=high.

    The LLM-judge tier (2c) is intentionally not wired here; it belongs
    behind an opt-in flag and a separate cost budget. See task #43.
    """
    from gpa.eval.scorer_giveup import is_gave_up
    from gpa.eval.scorer_prose import score_prose

    gave_up = is_gave_up(diagnosis_text)
    if gave_up:
        return ScoreVerdict(
            scorer="gave_up", solved=False, confidence="high",
            gave_up=True,
            reasoning="diagnosis tail matches a bail-out pattern",
        )

    if file_score is not None and file_score.solved:
        return ScoreVerdict(
            scorer="file_level", solved=True, confidence="high",
            file_score=file_score.file_score,
            reasoning="file_level scorer solved=True",
        )

    if fix is None or not getattr(fix, "files", None):
        return ScoreVerdict(
            scorer="no_signal", solved=False, confidence="high",
            reasoning="no fix.files ground truth to score against",
        )

    # File-level partial hit: agent named at least one ground-truth file
    # but not enough to clear the recall threshold. R12c/R12d showed this
    # is the dominant failure mode for multi-file refactor PRs (e.g. a
    # godot fix that touches 13 files — the agent correctly names 3 of
    # them but file_score=0.23 is below the 0.5 threshold). Mark as
    # needs_review so the LLM judge gets a chance to upgrade against the
    # actual diff hunks.
    if file_score is not None and file_score.file_hits:
        return ScoreVerdict(
            scorer="file_level", solved=False, confidence="low",
            file_score=file_score.file_score,
            needs_review=True,
            reasoning=(
                f"file_level any_hit but below threshold "
                f"({len(file_score.file_hits)}/{len(fix.files)} files, "
                f"score={file_score.file_score:.2f})"
            ),
        )

    prose = score_prose(diagnosis_text or "", list(fix.files))
    if prose.solved:
        return ScoreVerdict(
            scorer="prose", solved=True, confidence="medium",
            file_score=file_score.file_score if file_score else None,
            prose_recall=prose.recall, prose_precision=prose.precision,
            reasoning=(
                f"prose extractor recall={prose.recall:.2f} "
                f"precision={prose.precision:.2f}"
            ),
        )
    if prose.any_hit:
        return ScoreVerdict(
            scorer="prose", solved=False, confidence="low",
            file_score=file_score.file_score if file_score else None,
            prose_recall=prose.recall, prose_precision=prose.precision,
            needs_review=True,
            reasoning=(
                f"prose any_hit but below threshold "
                f"(recall={prose.recall:.2f}, "
                f"precision={prose.precision:.2f})"
            ),
        )
    # Substantive diagnosis with no file or prose hits — still worth
    # judging when we have a real diagnosis to compare. Filters out
    # short or empty responses (the gave_up/timeout cases above already
    # short-circuit; this catches the "agent diagnosed correctly but
    # used different file path conventions" tail).
    if (diagnosis_text or "").strip() and len(diagnosis_text) >= 200:
        return ScoreVerdict(
            scorer="no_signal", solved=False, confidence="medium",
            file_score=file_score.file_score if file_score else None,
            prose_recall=prose.recall, prose_precision=prose.precision,
            needs_review=True,
            reasoning="no file or prose hits but substantive diagnosis — judge eligible",
        )
    return ScoreVerdict(
        scorer="no_signal", solved=False, confidence="high",
        file_score=file_score.file_score if file_score else None,
        prose_recall=prose.recall, prose_precision=prose.precision,
        reasoning="no file-level or prose hits",
    )
