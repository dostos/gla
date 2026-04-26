"""Yield-measurement instrument for the curation pipeline.

Runs discover -> URL dedup -> triage -> draft, and emits one JSONL record per
candidate plus a final summary report. Does NOT commit, does NOT validate, and
does NOT touch the production coverage log.

Stages tracked (each is a yield-killing point):

  discovered      : query returned this URL
  deduped         : URL not in coverage log (passed dedup)
  thread_fetched  : fetch_thread() succeeded
  in_scope        : triager verdict was not 'out_of_scope'
  not_fingerprint_dup : fingerprint not seen as a committed scenario
  drafted         : drafter produced a parseable, validating draft
  not_too_easy    : (optional) sonnet code_only failed to solve in 15 turns

End-to-end yield = drafted / discovered (or not_too_easy / discovered when
--with-difficulty-check is on).

Usage:

    PYTHONPATH=src/python python3 -m gpa.eval.curation.measure_yield \\
        --config /tmp/breadcrumb_queries.yaml \\
        --jsonl /tmp/yield-records.jsonl \\
        --report docs/mining-yield-baseline.md
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from collections import Counter
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Optional

import yaml


class _NoOpCoverageLog:
    """Stand-in passed to the Discoverer during a yield-measurement run.

    The production :class:`Discoverer` consults its ``coverage_log`` for two
    side-effects we MUST suppress when measuring yield:

    1. ``contains_url(url)`` — used to drop already-reviewed candidates.
       For yield measurement, we want to *see* dedup as its own stage, so we
       must let every discovered URL through here and let the YieldMeasurer's
       own snapshot do the dedup.
    2. ``append(entry)`` — used to record the cheap pre-triage
       'non-rendering' rejections. Writing these would pollute the real
       coverage log with measurement-only entries.

    Returns False / no-op for everything the Discoverer currently calls.
    """
    path = None  # consumed by CoverageLog API but unused by Discoverer

    def contains_url(self, url: str) -> bool:  # pragma: no cover - trivial
        return False

    def contains_fingerprint(self, fingerprint: str) -> bool:  # pragma: no cover
        return False

    def append(self, entry) -> None:  # pragma: no cover - trivial
        return None

    def read_all(self) -> list:  # pragma: no cover
        return []


# Stages, in order, that a candidate passes through. Each stage subsumes the
# prior one (a candidate that reaches "drafted" also passed all earlier stages).
STAGE_ORDER = [
    "discovered",
    "deduped",
    "thread_fetched",
    "in_scope",
    "not_fingerprint_dup",
    "drafted",
    "not_too_easy",
]


@dataclass
class YieldRecord:
    """One candidate's path through the pipeline.

    `stage_reached` is the LAST stage successfully passed; `rejection_reason`
    explains why the candidate did not progress further (None if it made it
    all the way through).
    """
    url: str
    source_type: str
    title: str
    stage_reached: str
    rejection_reason: Optional[str] = None
    fingerprint: Optional[str] = None
    fix_pr_url: Optional[str] = None
    draft_size_lines: Optional[int] = None
    triage_summary: Optional[str] = None
    notes: Optional[str] = None

    def to_dict(self) -> dict:
        return {k: v for k, v in asdict(self).items() if v is not None or k in
                ("rejection_reason", "fingerprint")}


def _hash(*parts: str) -> str:
    h = hashlib.sha256()
    for p in parts:
        h.update(p.encode())
    return h.hexdigest()[:16]


def _extract_fix_pr_url_from_md(md_body: str) -> Optional[str]:
    """Pull `fix_pr_url:` value from the YAML block in the drafter's md output.

    Best-effort; returns None if the value isn't present or the YAML can't
    be parsed.
    """
    import re
    m = re.search(r"```yaml\s*\n(.+?)\n```", md_body, re.DOTALL)
    if not m:
        return None
    try:
        data = yaml.safe_load(m.group(1)) or {}
    except yaml.YAMLError:
        return None
    if not isinstance(data, dict):
        return None
    val = data.get("fix_pr_url")
    return val if isinstance(val, str) else None


class YieldMeasurer:
    """Drives candidates through discover -> dedup -> triage -> draft and
    records the stage each one reaches.

    Mirrors the early/middle of CurationPipeline._process but:
      - never commits a scenario file,
      - never appends to the coverage log,
      - skips Validator and RunEval entirely (too slow for yield measurement),
      - logs structured per-candidate records instead of mutating state.
    """

    def __init__(
        self,
        *,
        discoverer,
        fetch_thread: Callable,
        triager,
        drafter,
        coverage_log,
        records_out: list,
        with_difficulty_check: bool = False,
        difficulty_check_fn: Optional[Callable] = None,
        progress_fn: Optional[Callable] = None,
    ):
        self._discoverer = discoverer
        self._fetch = fetch_thread
        self._triager = triager
        self._drafter = drafter
        self._log = coverage_log
        self._records: list = records_out
        self._progress = progress_fn
        # Snapshot the URL/fingerprint sets ONCE up front so dedup is O(1) and
        # we don't reread the (potentially large) jsonl coverage log on every
        # candidate.
        entries = coverage_log.read_all()
        self._known_urls = {e.issue_url for e in entries}
        self._known_committed_fingerprints = {
            e.root_cause_fingerprint for e in entries
            if e.outcome == "scenario_committed" and e.root_cause_fingerprint
        }
        self._with_difficulty = with_difficulty_check
        self._difficulty_fn = difficulty_check_fn

    def run(self) -> None:
        candidates = self._discoverer.run()
        if self._progress:
            self._progress(f"discovered {len(candidates)} candidates after pre-filter")
        for i, cand in enumerate(candidates, 1):
            if self._progress:
                self._progress(f"[{i}/{len(candidates)}] processing {cand.url}")
            self._measure(cand)

    def _emit(self, rec: YieldRecord) -> None:
        if self._progress:
            self._progress(
                f"  -> stage={rec.stage_reached} reason={rec.rejection_reason}"
            )
        self._records.append(rec)

    def _measure(self, cand) -> None:
        rec = YieldRecord(
            url=cand.url,
            source_type=cand.source_type,
            title=cand.title or "",
            stage_reached="discovered",
        )

        # --- URL dedup ---
        if cand.url in self._known_urls:
            rec.rejection_reason = "url_dedup"
            self._emit(rec)
            return
        rec.stage_reached = "deduped"

        # --- Fetch thread ---
        try:
            thread = self._fetch(cand.url)
        except Exception as e:
            rec.rejection_reason = "fetch_failed"
            rec.notes = type(e).__name__
            self._emit(rec)
            return
        rec.stage_reached = "thread_fetched"

        # --- Triage ---
        try:
            triage = self._triager.triage(thread)
        except Exception as e:
            rec.rejection_reason = "triage_error"
            rec.notes = type(e).__name__
            self._emit(rec)
            return
        rec.fingerprint = triage.fingerprint
        rec.triage_summary = (triage.summary or "")[:200]

        if triage.verdict == "out_of_scope":
            rec.rejection_reason = (
                triage.rejection_reason or "out_of_scope_not_rendering_bug"
            )
            self._emit(rec)
            return
        rec.stage_reached = "in_scope"

        # --- Fingerprint dedup (committed scenarios only, mirrors pipeline) ---
        if triage.fingerprint in self._known_committed_fingerprints:
            rec.rejection_reason = "duplicate_of_existing_scenario"
            self._emit(rec)
            return
        rec.stage_reached = "not_fingerprint_dup"

        # --- Draft ---
        # Use a sortable but stable proposed scenario id; the drafter will pick
        # its own id baked into the source comment, but we need a placeholder.
        proposed_id = f"yield_{_hash(cand.url)[:10]}"
        from gpa.eval.curation.draft import DraftRejectedByModel
        try:
            draft = self._drafter.draft(thread, triage, scenario_id=proposed_id)
        except DraftRejectedByModel as e:
            # Principled refusal by the drafter LLM. Distinct bucket from
            # format failures: it tells us the candidate was reviewed and
            # judged un-draftable, not that the LLM mis-formatted its output.
            rec.rejection_reason = f"drafter_declined:{e.reason}"
            rec.notes = str(e)[:200]
            self._emit(rec)
            return
        except ValueError as e:
            # Drafter validation failure (missing citation, malformed YAML, etc.)
            rec.rejection_reason = "draft_invalid"
            rec.notes = str(e)[:200]
            self._emit(rec)
            return
        except Exception as e:
            # Network / LLM backend failure
            rec.rejection_reason = "draft_error"
            rec.notes = type(e).__name__
            self._emit(rec)
            return

        rec.stage_reached = "drafted"
        rec.fix_pr_url = _extract_fix_pr_url_from_md(draft.scenario_md)
        rec.draft_size_lines = sum(
            content.count("\n") + 1 for content in draft.files.values()
        )

        # --- Optional difficulty check (skip-by-default; expensive) ---
        if self._with_difficulty and self._difficulty_fn is not None:
            try:
                solved = bool(self._difficulty_fn(draft))
            except Exception:
                solved = False
            if solved:
                rec.rejection_reason = "would_be_too_easy"
                self._emit(rec)
                return
            rec.stage_reached = "not_too_easy"

        self._emit(rec)


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------


def _stage_counts(records: list) -> dict[str, int]:
    """Count how many candidates *reached* each stage (cumulative, not bucketed).

    A candidate at stage_reached='drafted' counts toward every stage up to and
    including 'drafted'. A candidate at stage_reached='in_scope' counts toward
    discovered, deduped, thread_fetched, and in_scope.
    """
    counts = {s: 0 for s in STAGE_ORDER}
    for r in records:
        try:
            idx = STAGE_ORDER.index(r.stage_reached)
        except ValueError:
            continue
        for s in STAGE_ORDER[: idx + 1]:
            counts[s] += 1
    return counts


def _rejection_breakdown(records: list) -> Counter:
    return Counter(r.rejection_reason for r in records if r.rejection_reason)


def render_report(
    records: list,
    *,
    queries_used: int,
    config_path: Optional[str],
    with_difficulty_check: bool,
) -> str:
    """Render a markdown yield-baseline report."""
    counts = _stage_counts(records)
    rej = _rejection_breakdown(records)
    discovered = counts["discovered"]

    def _pct(num: int, denom: int) -> str:
        return f"{(100.0 * num / denom):.1f}%" if denom > 0 else "n/a"

    final_stage = "not_too_easy" if with_difficulty_check else "drafted"
    end_to_end = counts.get(final_stage, 0)

    lines = []
    lines.append("# Mining Yield Baseline")
    lines.append("")
    lines.append(f"_Generated: {datetime.now(timezone.utc).isoformat()}_")
    if config_path:
        lines.append(f"_Config: `{config_path}`_")
    lines.append("")
    lines.append(f"Queries:                {queries_used}")
    lines.append(f"URLs from discovery:    {counts['discovered']}")
    lines.append(
        f"After URL dedup:        {counts['deduped']}   "
        f"({counts['deduped']}/{discovered} = {_pct(counts['deduped'], discovered)} fresh)"
    )
    lines.append(
        f"After thread fetch:     {counts['thread_fetched']}   "
        f"({counts['thread_fetched']}/{counts['deduped']} = "
        f"{_pct(counts['thread_fetched'], counts['deduped'])} fetched)"
    )
    lines.append(
        f"After triage in_scope:  {counts['in_scope']}   "
        f"({counts['in_scope']}/{counts['thread_fetched']} = "
        f"{_pct(counts['in_scope'], counts['thread_fetched'])} accept)"
    )
    lines.append(
        f"After fingerprint dedup:{counts['not_fingerprint_dup']}   "
        f"({counts['not_fingerprint_dup']}/{counts['in_scope']} = "
        f"{_pct(counts['not_fingerprint_dup'], counts['in_scope'])} novel)"
    )
    lines.append(
        f"After successful draft: {counts['drafted']}   "
        f"({counts['drafted']}/{counts['not_fingerprint_dup']} = "
        f"{_pct(counts['drafted'], counts['not_fingerprint_dup'])} draft success)"
    )
    if with_difficulty_check:
        lines.append(
            f"Would-be-not-too-easy:  {counts['not_too_easy']}   "
            f"({counts['not_too_easy']}/{counts['drafted']} = "
            f"{_pct(counts['not_too_easy'], counts['drafted'])} remaining)"
        )
    else:
        lines.append("Would-be-too-easy:      [skipped — pass --with-difficulty-check to enable]")
    lines.append("")
    lines.append(
        f"**End-to-end yield:**     {end_to_end}/{discovered} = "
        f"{_pct(end_to_end, discovered)}"
    )
    lines.append("")
    if rej:
        lines.append("## Top rejection reasons")
        for reason, count in rej.most_common():
            lines.append(f"- {reason}: {count}")
    lines.append("")
    return "\n".join(lines) + "\n"


def write_jsonl(records: list, path: Path | str) -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("w", encoding="utf-8") as f:
        for r in records:
            f.write(json.dumps(r.to_dict()) + "\n")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Curation pipeline yield-measurement dry-run",
    )
    parser.add_argument(
        "--config", default=None,
        help="YAML config with batch_quota + queries (same shape as pipeline.py)",
    )
    parser.add_argument("--batch-quota", type=int, default=20)
    parser.add_argument(
        "--log", default="docs/superpowers/eval/coverage-log.jsonl",
        help="Coverage log to read for URL/fingerprint dedup (READ-ONLY)",
    )
    parser.add_argument(
        "--jsonl", default="/tmp/yield-records.jsonl",
        help="Per-candidate JSONL output path",
    )
    parser.add_argument(
        "--report", default=None,
        help="Markdown report output path (default: stdout only)",
    )
    parser.add_argument(
        "--backend", default="auto",
        choices=["auto", "anthropic", "claude-code"],
    )
    parser.add_argument(
        "--with-difficulty-check", action="store_true",
        help="Run sonnet code_only on each drafted scenario; exclude solved ones",
    )
    parser.add_argument(
        "--skip-draft", action="store_true",
        help="Stop after triage; useful for cheap yield measurements that "
             "only care about discovery + triage stages.",
    )
    return parser.parse_args(argv)


def _build_components(args, queries: dict, batch_quota: int):
    """Wire up the production discoverer/triager/drafter for a CLI run."""
    from gpa.eval.curation.coverage_log import CoverageLog
    from gpa.eval.curation.discover import (
        Discoverer, GitHubSearch, StackExchangeSearch,
    )
    from gpa.eval.curation.triage import Triage, fetch_thread as _fetch
    from gpa.eval.curation.draft import Draft
    from gpa.eval.curation.llm_client import LLMClient, ClaudeCodeLLMClient

    backend = args.backend
    if backend == "auto":
        backend = "claude-code" if not os.environ.get("ANTHROPIC_API_KEY") else "anthropic"
    if backend == "claude-code":
        llm = ClaudeCodeLLMClient()
    else:
        llm = LLMClient.from_env()

    # Real coverage log — read-only, used by YieldMeasurer for dedup snapshot.
    log = CoverageLog(args.log)
    # Stub log handed to the Discoverer so it neither dedups (we want to
    # measure dedup as its own stage) nor mutates the real coverage log
    # (its pre-triage rejections would pollute the production log).
    disc = Discoverer(
        search=GitHubSearch(),
        so_search=StackExchangeSearch(),
        coverage_log=_NoOpCoverageLog(),
        queries=queries,
        batch_quota=batch_quota,
    )
    triager = Triage(llm_client=llm)
    drafter = Draft(llm_client=llm)
    return log, disc, _fetch, triager, drafter


class _SkipDrafter:
    """Drop-in stub used with --skip-draft: never produces a draft, always
    raises ValueError so the candidate is logged at stage_reached='not_fingerprint_dup'.
    """
    def draft(self, thread, triage, *, scenario_id, previous_error=None):
        raise ValueError("draft skipped (--skip-draft)")


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)

    cfg = {}
    if args.config:
        with open(args.config, encoding="utf-8") as f:
            cfg = yaml.safe_load(f) or {}
    batch_quota = cfg.get("batch_quota", args.batch_quota)
    from gpa.eval.curation.discover import DEFAULT_QUERIES
    queries = cfg.get("queries", DEFAULT_QUERIES)
    queries_count = (
        len(queries.get("issue", []))
        + len(queries.get("commit", []))
        + len(queries.get("stackoverflow", []))
    )

    log, disc, fetch_fn, triager, drafter = _build_components(
        args, queries, batch_quota
    )
    if args.skip_draft:
        drafter = _SkipDrafter()

    records: list = []

    def _progress(msg: str) -> None:
        # Print to stdout so the parent's `tee`/`tail`/Monitor sees it
        # without merge-with-stderr gymnastics. flush=True so the line
        # surfaces immediately, not at process exit.
        print(f"[measure_yield] {msg}", flush=True)

    measurer = YieldMeasurer(
        discoverer=disc,
        fetch_thread=fetch_fn,
        triager=triager,
        drafter=drafter,
        coverage_log=log,
        records_out=records,
        with_difficulty_check=args.with_difficulty_check,
        progress_fn=_progress,
    )

    _progress(f"Running with {queries_count} queries, batch_quota={batch_quota}")
    measurer.run()

    write_jsonl(records, args.jsonl)
    report = render_report(
        records,
        queries_used=queries_count,
        config_path=args.config,
        with_difficulty_check=args.with_difficulty_check,
    )
    print(report)
    if args.report:
        Path(args.report).parent.mkdir(parents=True, exist_ok=True)
        Path(args.report).write_text(report)
        print(f"[measure_yield] Wrote report: {args.report}", file=sys.stderr)
    print(f"[measure_yield] Wrote per-candidate JSONL: {args.jsonl}",
          file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
