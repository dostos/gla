"""Single-path mining orchestrator (SELECT -> PRODUCE -> JUDGE).

This is the unified CLI entry point for the OpenGPA mining pipeline. It
discovers candidates, scores them via deterministic rules, optionally
extracts a DraftResult + validates it, and (in JUDGE phase) commits the
scenario into ``tests/eval/`` while writing a coverage-log entry.

A single run produces one append-only ``journey.jsonl`` file with one
row per candidate at its terminal phase. The journey row is the source
of truth for both per-run reporting and cross-run analysis.

Usage::

    python -m gpa.eval.curation.run \\
        --queries config/queries.yaml \\
        --rules config/rules.yaml \\
        --workdir .eval-pipeline \\
        --max-phase judge

By design there are NO LLM calls in this module. All decisions are
driven by the YAML rules + deterministic extractors. Test seams are
exposed at module scope so tests can stub network and filesystem
dependencies (``build_discoverer``, ``fetch_thread``,
``_fetch_fix_pr_metadata``, ``_validate_draft``, ``run_eval``,
``commit_scenario``).
"""
from __future__ import annotations

import argparse
import dataclasses
import json
import logging
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

import yaml

from gpa.eval.curation.classify import classify_observed_helps
from gpa.eval.curation.commit import commit_scenario
from gpa.eval.curation.coverage_log import CoverageLog
from gpa.eval.curation.discover import (
    Discoverer,
    GitHubSearch,
    StackExchangeSearch,
)
from gpa.eval.curation.extract_draft import (
    DraftResult,
    ExtractionFailure,
    extract_draft,
)
from gpa.eval.curation.journey import (
    JourneyRow,
    JourneyWriter,
    JudgeOutcome,
    ProduceOutcome,
    SelectOutcome,
    TerminalReason,
    TokenSpend,
)
from gpa.eval.curation.rules import (
    MiningRules,
    load_rules,
    score_candidate,
    select_stratified,
)
from gpa.eval.curation.run_dir import RunDir, generate_run_id
from gpa.eval.curation.scope_log import aggregate_scope, append_scope_rows
from gpa.eval.curation.summary import write_summary
from gpa.eval.curation.triage import IssueThread, fetch_thread

__all__ = [
    "main",
    "parse_args",
    "build_discoverer",
    "fetch_thread",
    "commit_scenario",
]


_LOG = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def parse_args(argv: Optional[list[str]] = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        prog="gpa.eval.curation.run",
        description=(
            "Single-path mining orchestrator: SELECT -> PRODUCE -> JUDGE. "
            "Discovers candidates, scores them, optionally extracts and "
            "validates a draft, and (in JUDGE phase) commits the scenario."
        ),
    )
    p.add_argument("--queries", required=True, help="Path to queries.yaml.")
    p.add_argument("--rules", required=True, help="Path to mining_rules.yaml.")
    p.add_argument(
        "--workdir", default=".eval-pipeline",
        help="Per-run output directory root. Default: .eval-pipeline",
    )
    p.add_argument(
        "--max-phase", default="judge",
        choices=["select", "produce", "judge"],
        help=(
            "Phase to stop at. select=score+rank only; produce=also "
            "extract+validate; judge=also commit (and optionally evaluate)."
        ),
    )
    p.add_argument(
        "--evaluate", action="store_true", default=False,
        help="In JUDGE phase, run the eval harness before committing.",
    )
    p.add_argument(
        "--batch-quota", type=int, default=20,
        help="Total candidates to discover. Default: 20",
    )
    p.add_argument(
        "--eval-dir", default="tests/eval",
        help="Directory to commit scenarios into. Default: tests/eval",
    )
    p.add_argument(
        "--backend", default="auto",
        help="LLM backend hint passed to RunEval (no effect without --evaluate).",
    )
    p.add_argument(
        "--run-id", default=None,
        help="Override the auto-generated run_id (for reproducible test runs).",
    )
    # Selection thresholds. Read from rules.yaml's `selection` block when
    # present; otherwise default to (min_score=4, per_cell_cap=4).
    p.add_argument(
        "--min-score", type=int, default=None,
        help="Override min_score (otherwise read from rules.yaml selection.min_score, default 4).",
    )
    p.add_argument(
        "--per-cell-cap", type=int, default=None,
        help="Override per_cell_cap (otherwise read from rules.yaml selection.per_cell_cap, default 4).",
    )
    p.add_argument(
        "--coverage-log", default="docs/superpowers/eval/coverage-log.jsonl",
        help="Coverage log path (read for dedup, written on commit).",
    )
    p.add_argument(
        "--summary-path", default="docs/superpowers/eval/coverage-gaps.md",
        help="Coverage-gaps summary path (regenerated on commit).",
    )
    return p.parse_args(argv)


# ---------------------------------------------------------------------------
# Test seams (module-level so monkeypatch.setattr(...) works).
# ---------------------------------------------------------------------------


def build_discoverer(queries: dict, coverage_log: CoverageLog,
                      batch_quota: int) -> Discoverer:
    """Construct the production Discoverer.

    Tests monkeypatch this to return a stub. The signature matches what
    the orchestrator passes in: queries dict, coverage log, batch quota.
    """
    return Discoverer(
        search=GitHubSearch(),
        coverage_log=coverage_log,
        queries=queries,
        batch_quota=batch_quota,
        so_search=StackExchangeSearch(),
    )


def _validate_draft(draft: DraftResult, eval_dir: Path) -> Any:
    """Default validator: static field-presence check on the new DraftResult.

    The new strict-CLI DraftResult has a different field shape than the
    LLM-era one Validator was built for (no scenario_id, no files dict).
    For the deterministic mining path we only need to confirm the required
    fields were extracted — build/capture verification belongs in --evaluate.

    Tests monkeypatch this seam to inject specific ValidationResult-shaped
    return values for failure-path tests.
    """
    @dataclasses.dataclass
    class _StaticResult:
        ok: bool
        reason: str = ""

    if not draft.user_report:
        return _StaticResult(ok=False, reason="empty user_report")
    if not draft.expected_files:
        return _StaticResult(ok=False, reason="no expected_files")
    if not draft.fix_commit_sha or not draft.fix_pr_url:
        return _StaticResult(ok=False, reason="missing fix-PR metadata")
    if not draft.bug_signature_yaml or not draft.bug_signature_yaml.startswith("type:"):
        return _StaticResult(ok=False, reason="malformed bug_signature_yaml")
    return _StaticResult(ok=True, reason="static_ok")


def run_eval(*, scenario_id: str, eval_dir: Path, backend: str) -> Any:
    """Default eval-harness wrapper.

    Tests monkeypatch this. Production callers should provide their own
    harness; the default raises so missing wiring fails loudly rather than
    silently committing a never-evaluated scenario.
    """
    raise NotImplementedError(
        "run_eval requires a configured EvalHarness; pass --evaluate only "
        "when the harness is available, or monkeypatch this seam in tests."
    )


run_eval._is_default = True  # cleared when callers replace the seam


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


_SCENARIO_SLUG_RE = re.compile(r"[^a-z0-9]+")


def _slugify(s: str, max_len: int = 30) -> str:
    s = (s or "").lower()
    s = _SCENARIO_SLUG_RE.sub("_", s).strip("_")
    return s[:max_len].rstrip("_") or "scenario"


def _make_scenario_id(rec: Any, cand: Any, *, run_id: str) -> str:
    """Build a deterministic scenario id from candidate + run.

    Format: ``r<short_run_id>_<taxonomy>_<title_slug>``. Both segments
    of taxonomy_cell get joined with ``_`` (cell uses dots; ``r``-prefix
    matches the ``rN_<slug>`` pattern that already exists in tests/eval/).
    """
    short = run_id.split("-")[-1][:6]
    cell = (rec.taxonomy_cell or "unknown").replace(".", "_").replace("/", "_")
    title_slug = _slugify(getattr(cand, "title", "") or "scenario")
    return f"r{short}_{cell}_{title_slug}"


def _fetch_fix_pr_metadata(thread: IssueThread, url: str) -> dict:
    """Best-effort: parse the closing-PR ref from the thread and fetch its
    metadata via ``gh api``.

    Returns ``{"url": str, "commit_sha": str, "files_changed": list[str]}``
    on success, or raises an exception which the caller catches and
    records as ``terminal_reason=extraction_failed``.

    On ``gh api`` failure, emits a WARNING-level log line including
    ``CalledProcessError.stderr`` so operators debugging a failed run can
    see the underlying API error rather than only "extraction failed".
    The journey-row schema does not admit a free-form failure-detail
    field (per Task 1), so the log is the surfacing mechanism.

    Tests monkeypatch this seam.
    """
    body_text = thread.body or ""
    comments_text = "\n".join(thread.comments or [])
    full = body_text + "\n" + comments_text

    # Owner/repo come from the candidate URL; the PR refs we look for are
    # short-form (#NNN) on the same repo, or fully-qualified pull URLs.
    repo_m = re.search(r"github\.com/([^/]+)/([^/]+)/", url)
    if not repo_m:
        raise ValueError(f"not a github URL: {url}")
    owner, repo = repo_m.group(1), repo_m.group(2)

    # PR candidates: the candidate PR IS the fix. Use it directly rather
    # than searching the body for another PR ref (which usually references
    # the issue being fixed, not another fix-PR — leading to a 404 on
    # `pulls/<issue-number>`).
    self_pr_m = re.match(
        r"https?://github\.com/([^/\s]+)/([^/\s]+)/pull/(\d+)", url
    )
    if self_pr_m:
        owner_pr, repo_pr, num = self_pr_m.group(1), self_pr_m.group(2), self_pr_m.group(3)
    else:
        # Issue candidate: prefer fully-qualified pull URLs in the body
        # (they're unambiguous; the GraphQL ``closedByPullRequestsReferences``
        # appended by ``triage.fetch_issue_thread`` shows up here).
        pr_url_m = re.search(
            r"https?://github\.com/([^/\s]+)/([^/\s]+)/pull/(\d+)", full
        )
        if pr_url_m:
            owner_pr, repo_pr, num = pr_url_m.group(1), pr_url_m.group(2), pr_url_m.group(3)
        else:
            # Fall back to short-form refs introduced by closing-keyword phrases.
            short_m = re.search(
                r"(?i)(?:closed by|fixed (?:in|by)|resolved by)[^#]*#(\d+)", full
            )
            if not short_m:
                short_m = re.search(r"#(\d+)", full)
            if not short_m:
                raise ValueError(f"no PR reference found in thread {url}")
            owner_pr, repo_pr, num = owner, repo, short_m.group(1)

    try:
        proc = subprocess.run(
            ["gh", "api", f"repos/{owner_pr}/{repo_pr}/pulls/{num}"],
            capture_output=True, text=True, check=True,
        )
        pr = json.loads(proc.stdout)

        files_proc = subprocess.run(
            ["gh", "api", f"repos/{owner_pr}/{repo_pr}/pulls/{num}/files"],
            capture_output=True, text=True, check=True,
        )
        files = json.loads(files_proc.stdout)
    except subprocess.CalledProcessError as exc:
        # Surface gh stderr so operators can see the underlying failure
        # (rate limit, 404, auth, etc.) rather than only "extraction failed".
        _LOG.warning(
            "gh api failed for %s (PR %s/%s#%s): %s",
            url, owner_pr, repo_pr, num, (exc.stderr or "").strip(),
        )
        raise

    return {
        "url": pr.get("html_url") or f"https://github.com/{owner_pr}/{repo_pr}/pull/{num}",
        "commit_sha": pr.get("merge_commit_sha") or pr.get("head", {}).get("sha", ""),
        "files_changed": [f.get("filename") for f in files if f.get("filename")],
    }


def _make_row(
    cand: Any, *,
    run_id: str,
    discovered_at: str,
    select: SelectOutcome,
    produce: Optional[ProduceOutcome] = None,
    judge: Optional[JudgeOutcome] = None,
    terminal_phase: str,
    terminal_reason: str,
    tokens: Optional[TokenSpend] = None,
    cache_hit: bool = False,
) -> JourneyRow:
    """Single source of truth for building JourneyRow instances."""
    # Pull the discovery query from candidate metadata if available.
    md = getattr(cand, "metadata", None) or {}
    discovery_query = md.get("source_query") or getattr(cand, "query", "") or ""
    if not isinstance(discovery_query, str):
        discovery_query = json.dumps(discovery_query)
    return JourneyRow(
        url=getattr(cand, "url", ""),
        run_id=run_id,
        discovered_at=discovered_at,
        discovery_query=discovery_query,
        select=select,
        produce=produce,
        judge=judge,
        tokens=tokens or TokenSpend(),
        cache_hit=cache_hit,
        terminal_phase=terminal_phase,
        terminal_reason=terminal_reason,
    )


def _select_outcome_for(rec: Any, *, selected: bool) -> SelectOutcome:
    """Build a SelectOutcome from a scored MiningPlanRecord."""
    return SelectOutcome(
        deduped=False, fetched=True,
        taxonomy_cell=rec.taxonomy_cell,
        score=rec.score,
        score_reasons=list(rec.score_reasons),
        selected=selected,
    )


def _thread_to_dict(thread: IssueThread) -> dict:
    """Adapt the IssueThread dataclass to the dict shape extract_draft expects."""
    return dataclasses.asdict(thread)


def _draft_to_files(draft: DraftResult) -> dict[str, str]:
    """Build the {filename: content} dict commit_scenario writes to disk.

    For maintainer-framing scenarios (no .c source), commit only scenario.md
    (the validator already enforced that the structural fields are present).
    """
    bug_class = str(draft.extras.get("bug_class") or "framework-internal")
    if bug_class not in {"framework-internal", "consumer-misuse", "user-config"}:
        bug_class = "framework-internal"

    md_lines = [
        "## User Report",
        "",
        draft.user_report.strip(),
        "",
    ]
    if draft.expected_section:
        md_lines += ["## Expected", "", draft.expected_section.strip(), ""]
    if draft.actual_section:
        md_lines += ["## Actual", "", draft.actual_section.strip(), ""]
    md_lines += [
        "## Ground Truth",
        "",
        f"See fix at {draft.fix_pr_url}.",
        "",
        "## Fix",
        "",
        "```yaml",
        f"fix_pr_url: {draft.fix_pr_url}",
        f"fix_sha: {draft.fix_commit_sha}",
        f"bug_class: {bug_class}",
        f"files:",
    ]
    for f in draft.expected_files:
        md_lines.append(f"  - {f}")
    md_lines.append("```")
    md_lines.append("")
    return {"scenario.md": "\n".join(md_lines)}


def _load_queries(queries_path: Path) -> dict:
    """Normalise queries.yaml into the {issue, commit, stackoverflow} shape."""
    raw = yaml.safe_load(queries_path.read_text(encoding="utf-8")) or {}
    # Accept either a top-level dict {issue: [...], commit: [...], stackoverflow: [...]}
    # or a wrapped form {queries: {...}}.
    if "queries" in raw and isinstance(raw["queries"], dict):
        raw = raw["queries"]
    out: dict[str, list] = {"issue": [], "commit": [], "stackoverflow": []}
    for key in out:
        val = raw.get(key)
        if isinstance(val, list):
            out[key] = list(val)
    return out


def _resolve_selection_thresholds(
    rules_path: Path, args: argparse.Namespace
) -> tuple[int, int]:
    """Resolve (min_score, per_cell_cap) from CLI flags or rules.yaml.

    The plan keeps these in rules.yaml under a top-level ``selection``
    block; if absent, fall back to (min_score=4, per_cell_cap=4) so
    old rules files keep working.
    """
    raw = yaml.safe_load(Path(rules_path).read_text(encoding="utf-8")) or {}
    sel = raw.get("selection") or {}
    min_score = (
        args.min_score if args.min_score is not None
        else int(sel.get("min_score", 4))
    )
    per_cell_cap = (
        args.per_cell_cap if args.per_cell_cap is not None
        else int(sel.get("per_cell_cap", 4))
    )
    return min_score, per_cell_cap


# ---------------------------------------------------------------------------
# Phase helpers (one per phase). Each is independently readable and only
# touches its own slice of journey rows + return value. ``main`` is the
# orchestration glue that wires them together.
# ---------------------------------------------------------------------------


def _run_select(
    *, candidates: list[Any], coverage: CoverageLog, rules: MiningRules,
    min_score: int, per_cell_cap: int, batch_quota: int,
    run_id: str, discovered_at: str, writer: JourneyWriter,
) -> list[tuple[Any, IssueThread, Any]]:
    """Run dedup -> fetch -> score -> stratified-select.

    Writes a journey row at SELECT terminal for every dropped candidate
    (DUPLICATE_URL, FETCH_FAILED, TRIAGE_REJECTED, BELOW_MIN_SCORE,
    NOT_SELECTED). Returns the list of selected ``(cand, thread, rec)``
    triples. Does NOT write rows for selected candidates -- the caller
    decides their terminal_phase/reason based on max-phase.
    """
    eligible: list[tuple[Any, IssueThread, Any]] = []

    for cand in candidates:
        # 1. dedup by URL
        if coverage.contains_url(cand.url):
            select = SelectOutcome(
                deduped=True, fetched=False, taxonomy_cell=None, score=0,
                score_reasons=[], selected=False,
            )
            writer.append(_make_row(
                cand, run_id=run_id, discovered_at=discovered_at,
                select=select,
                terminal_phase="select",
                terminal_reason=TerminalReason.DUPLICATE_URL.value,
            ))
            continue

        # 2. fetch_thread (network call; tests stub this)
        try:
            thread = fetch_thread(cand.url)
        except Exception:
            select = SelectOutcome(
                deduped=False, fetched=False, taxonomy_cell=None, score=0,
                score_reasons=[], selected=False,
            )
            writer.append(_make_row(
                cand, run_id=run_id, discovered_at=discovered_at,
                select=select,
                terminal_phase="select",
                terminal_reason=TerminalReason.FETCH_FAILED.value,
            ))
            continue

        # 3. score (triage_required/triage_reject gates run inside).
        rec = score_candidate(cand, thread=thread, rules=rules)
        if rec.terminal_reason == "triage_rejected":
            writer.append(_make_row(
                cand, run_id=run_id, discovered_at=discovered_at,
                select=_select_outcome_for(rec, selected=False),
                terminal_phase="select",
                terminal_reason=TerminalReason.TRIAGE_REJECTED.value,
            ))
            continue

        # 4. min-score gate
        if rec.score < min_score:
            writer.append(_make_row(
                cand, run_id=run_id, discovered_at=discovered_at,
                select=_select_outcome_for(rec, selected=False),
                terminal_phase="select",
                terminal_reason=TerminalReason.BELOW_MIN_SCORE.value,
            ))
            continue

        eligible.append((cand, thread, rec))

    # 5. stratified selection across eligible records.
    selected_records: list[tuple[Any, IssueThread, Any]] = []
    if not eligible:
        return selected_records

    selected_recs = select_stratified(
        [rec for (_c, _t, rec) in eligible],
        top_k=batch_quota,
        min_score=min_score,
        per_cell_cap=per_cell_cap,
    )
    selected_urls = {r.url for r in selected_recs}
    for cand, thread, rec in eligible:
        if rec.url in selected_urls:
            selected_records.append((cand, thread, rec))
        else:
            writer.append(_make_row(
                cand, run_id=run_id, discovered_at=discovered_at,
                select=_select_outcome_for(rec, selected=False),
                terminal_phase="select",
                terminal_reason=TerminalReason.NOT_SELECTED.value,
            ))
    return selected_records


def _run_produce(
    *, selected: list[tuple[Any, IssueThread, Any]],
    eval_dir: Path,
    run_id: str, discovered_at: str, writer: JourneyWriter,
) -> list[tuple[Any, IssueThread, Any, DraftResult, dict]]:
    """Run extract_draft + validate on each selected candidate.

    Writes a journey row at PRODUCE terminal for each failure
    (EXTRACTION_FAILED on fix-PR fetch, EXTRACTION_FAILED on extract
    raise, VALIDATION_FAILED on validator ok=False). Returns the list of
    successfully drafted ``(cand, thread, rec, draft, fix_pr)`` tuples.
    """
    drafted: list[tuple[Any, IssueThread, Any, DraftResult, dict]] = []
    for cand, thread, rec in selected:
        select = _select_outcome_for(rec, selected=True)

        # 1. Fetch fix-PR metadata
        try:
            fix_pr = _fetch_fix_pr_metadata(thread, cand.url)
        except Exception:
            writer.append(_make_row(
                cand, run_id=run_id, discovered_at=discovered_at,
                select=select,
                produce=ProduceOutcome(extracted=False, validated=False),
                terminal_phase="produce",
                terminal_reason=TerminalReason.EXTRACTION_FAILED.value,
            ))
            continue

        # 2. extract_draft
        try:
            draft = extract_draft(
                thread=_thread_to_dict(thread),
                fix_pr=fix_pr,
                taxonomy_cell=rec.taxonomy_cell,
            )
            draft.extras["bug_class"] = rec.bug_class_guess
        except ExtractionFailure:
            writer.append(_make_row(
                cand, run_id=run_id, discovered_at=discovered_at,
                select=select,
                produce=ProduceOutcome(extracted=False, validated=False),
                terminal_phase="produce",
                terminal_reason=TerminalReason.EXTRACTION_FAILED.value,
            ))
            continue

        # 3. validate (test seam)
        result = _validate_draft(draft, eval_dir)
        if not getattr(result, "ok", False):
            writer.append(_make_row(
                cand, run_id=run_id, discovered_at=discovered_at,
                select=select,
                produce=ProduceOutcome(extracted=True, validated=False),
                terminal_phase="produce",
                terminal_reason=TerminalReason.VALIDATION_FAILED.value,
            ))
            continue

        drafted.append((cand, thread, rec, draft, fix_pr))
    return drafted


def _run_judge(
    *, drafted: list[tuple[Any, IssueThread, Any, DraftResult, dict]],
    eval_dir: Path, summary_path: Path, backend: str, evaluate: bool,
    coverage: CoverageLog, run_id: str, discovered_at: str,
    writer: JourneyWriter,
) -> None:
    """Run optional eval, classify helpfulness, then commit.

    For each drafted candidate: optionally run_eval + classify, then commit
    (unless verdict=='no'). Writes a journey row at JUDGE terminal for
    every outcome (EVALUATE_ERROR, NOT_HELPFUL, COMMITTED).
    """
    for cand, thread, rec, draft, fix_pr in drafted:
        select = _select_outcome_for(rec, selected=True)
        produce = ProduceOutcome(extracted=True, validated=True)
        scenario_id = _make_scenario_id(rec, cand, run_id=run_id)

        with_gla_score: Optional[float] = None
        code_only_score: Optional[float] = None
        verdict: Optional[str] = None
        eval_summary: Optional[dict] = None

        if evaluate:
            try:
                ev = run_eval(
                    scenario_id=scenario_id,
                    eval_dir=eval_dir,
                    backend=backend,
                )
            except Exception:
                writer.append(_make_row(
                    cand, run_id=run_id, discovered_at=discovered_at,
                    select=select, produce=produce, judge=JudgeOutcome(),
                    terminal_phase="judge",
                    terminal_reason=TerminalReason.EVALUATE_ERROR.value,
                ))
                continue

            with_gla = getattr(ev, "with_gla", None)
            code_only = getattr(ev, "code_only", None)
            with_gla_score = float(getattr(with_gla, "score", 0.0)) if with_gla else None
            code_only_score = float(getattr(code_only, "score", 0.0)) if code_only else None

            try:
                obs = classify_observed_helps(with_gla, code_only)
            except Exception:
                obs = None
            verdict = getattr(obs, "verdict", None) if obs else None
            judge = JudgeOutcome(
                with_gla_score=with_gla_score,
                code_only_score=code_only_score,
                helps_verdict=verdict,
            )
            if verdict == "no":
                writer.append(_make_row(
                    cand, run_id=run_id, discovered_at=discovered_at,
                    select=select, produce=produce, judge=judge,
                    terminal_phase="judge",
                    terminal_reason=TerminalReason.NOT_HELPFUL.value,
                ))
                continue
            eval_summary = {
                "with_gla_score": with_gla_score,
                "code_only_score": code_only_score,
                "verdict": verdict,
            }

        # Commit the scenario into tests/eval/.
        commit_scenario(
            eval_dir=eval_dir,
            scenario_id=scenario_id,
            files=_draft_to_files(draft),
            coverage_log=coverage,
            summary_path=summary_path,
            issue_url=cand.url,
            source_type=getattr(cand, "source_type", "issue"),
            triage_verdict="in_scope",
            fingerprint=None,
            tier=rec.taxonomy_cell or "unknown",
            predicted_helps=None,
            observed_helps=verdict,
            failure_mode=None,
            eval_summary=eval_summary,
        )

        writer.append(_make_row(
            cand, run_id=run_id, discovered_at=discovered_at,
            select=select, produce=produce,
            judge=JudgeOutcome(
                with_gla_score=with_gla_score,
                code_only_score=code_only_score,
                helps_verdict=verdict,
                committed_as=scenario_id,
            ),
            terminal_phase="judge",
            terminal_reason=TerminalReason.COMMITTED.value,
        ))


def _write_select_terminal_rows(
    selected: list[tuple[Any, IssueThread, Any]],
    *, run_id: str, discovered_at: str, writer: JourneyWriter,
) -> None:
    """Write SELECT_DONE rows for candidates that successfully selected
    when --max-phase=select halts the run."""
    for cand, _thread, rec in selected:
        writer.append(_make_row(
            cand, run_id=run_id, discovered_at=discovered_at,
            select=_select_outcome_for(rec, selected=True),
            terminal_phase="select",
            terminal_reason=TerminalReason.SELECT_DONE.value,
        ))


def _write_produce_terminal_rows(
    drafted: list[tuple[Any, IssueThread, Any, DraftResult, dict]],
    *, run_id: str, discovered_at: str, writer: JourneyWriter,
) -> None:
    """Write PRODUCE_DONE rows for candidates that successfully drafted
    when --max-phase=produce halts the run."""
    for cand, _thread, rec, _draft, _fix_pr in drafted:
        writer.append(_make_row(
            cand, run_id=run_id, discovered_at=discovered_at,
            select=_select_outcome_for(rec, selected=True),
            produce=ProduceOutcome(extracted=True, validated=True),
            terminal_phase="produce",
            terminal_reason=TerminalReason.PRODUCE_DONE.value,
        ))


# ---------------------------------------------------------------------------
# main (orchestration glue)
# ---------------------------------------------------------------------------


def main(argv: Optional[list[str]] = None) -> int:
    args = parse_args(argv)

    if args.evaluate and getattr(run_eval, "_is_default", False):
        sys.stderr.write(
            "error: --evaluate requires an eval harness, but the default\n"
            "       gpa.eval.curation.run.run_eval seam is unconfigured.\n"
            "       Either drop --evaluate to commit without scoring, or\n"
            "       wire a harness by replacing run.run_eval before calling main().\n"
        )
        return 2

    queries_path = Path(args.queries)
    rules_path = Path(args.rules)
    cfg_payload = (
        queries_path.read_text(encoding="utf-8")
        + "\n# ---\n"
        + rules_path.read_text(encoding="utf-8")
    )
    run_id = args.run_id or generate_run_id(config_text=cfg_payload)
    rd = RunDir.create(
        root=Path(args.workdir), run_id=run_id, config_payload=cfg_payload
    )
    writer = JourneyWriter(rd.journey_path)

    queries = _load_queries(queries_path)
    rules: MiningRules = load_rules(rules_path)
    min_score, per_cell_cap = _resolve_selection_thresholds(rules_path, args)

    coverage = CoverageLog(args.coverage_log)
    discoverer = build_discoverer(queries, coverage, args.batch_quota)
    candidates = list(discoverer.run())
    discovered_at = datetime.now(timezone.utc).isoformat()

    selected = _run_select(
        candidates=candidates, coverage=coverage, rules=rules,
        min_score=min_score, per_cell_cap=per_cell_cap,
        batch_quota=args.batch_quota,
        run_id=run_id, discovered_at=discovered_at, writer=writer,
    )
    if args.max_phase == "select":
        _write_select_terminal_rows(
            selected, run_id=run_id, discovered_at=discovered_at, writer=writer,
        )
    else:
        drafted = _run_produce(
            selected=selected, eval_dir=Path(args.eval_dir),
            run_id=run_id, discovered_at=discovered_at, writer=writer,
        )
        if args.max_phase == "produce":
            _write_produce_terminal_rows(
                drafted, run_id=run_id, discovered_at=discovered_at, writer=writer,
            )
        else:
            _run_judge(
                drafted=drafted, eval_dir=Path(args.eval_dir),
                summary_path=Path(args.summary_path),
                backend=args.backend, evaluate=args.evaluate,
                coverage=coverage,
                run_id=run_id, discovered_at=discovered_at, writer=writer,
            )

    # Roll up journey.jsonl into the per-run summary.md regardless of
    # which phase halted the run.
    write_summary(journey_path=rd.journey_path, summary_path=rd.summary_path)

    # Append per-query scope rows to the cross-run scope log so future
    # runs can see what's been mined and find unexplored queries.
    scope_rows = aggregate_scope(
        journey_path=rd.journey_path, run_id=run_id,
        ts=discovered_at,
    )
    append_scope_rows(
        scope_log_path=Path(args.workdir) / "scope-log.jsonl",
        rows=scope_rows,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
