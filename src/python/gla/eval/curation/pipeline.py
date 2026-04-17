"""Pipeline orchestrator — wires all curation stages together.

For each discovered candidate, the pipeline runs:
  1. fetch_thread -> triage
  2. fingerprint dedup (log_rejection if duplicate)
  3. draft -> validate -> run_eval
  4. classify observed_helps; attribute failure_mode if no
  5. commit scenario + append observed/failure sections to md
"""
from __future__ import annotations

import argparse
import hashlib
import os
import re
from pathlib import Path
from typing import Callable, Optional

import yaml

from gla.eval.curation.classify import classify_observed_helps
from gla.eval.curation.commit import commit_scenario, log_rejection
from gla.eval.curation.coverage_log import CoverageLog
from gla.eval.curation.draft import DraftResult
from gla.eval.curation.triage import TriageResult
from gla.eval.curation.workdir import IssueWorkdir


def _hash(*parts: str) -> str:
    """Short stable hash used as the input_hash for IssueWorkdir stages."""
    h = hashlib.sha256()
    for p in parts:
        h.update(p.encode())
    return h.hexdigest()[:16]


def load_config(path: str) -> dict:
    """Load a YAML config file and return its contents as a dict."""
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


class CurationPipeline:
    def __init__(
        self,
        *,
        discoverer,
        fetch_thread: Callable,
        triager,
        drafter,
        validator,
        run_eval,
        failure_mode_fn: Callable,
        eval_dir: Path | str,
        workdir_root: Path | str,
        coverage_log_path: Path | str,
        summary_path: Path | str,
    ):
        self._discoverer = discoverer
        self._fetch = fetch_thread
        self._triager = triager
        self._drafter = drafter
        self._validator = validator
        self._run_eval = run_eval
        self._failure_mode_fn = failure_mode_fn
        self._eval_dir = Path(eval_dir)
        self._workdir_root = Path(workdir_root)
        self._log = CoverageLog(coverage_log_path)
        self._summary = Path(summary_path)

    def run_batch(self) -> None:
        candidates = self._discoverer.run()
        counter = self._next_scenario_index()
        for cand in candidates:
            self._process(cand, counter)
            counter += 1

    def _next_scenario_index(self) -> int:
        existing = (
            [p.stem for p in self._eval_dir.glob("r*.c")]
            if self._eval_dir.exists()
            else []
        )
        nums = [
            int(m.group(1))
            for s in existing
            if (m := re.match(r"r(\d+)_", s))
        ]
        return max(nums, default=0) + 1

    def _process(self, cand, index: int) -> None:
        workdir = IssueWorkdir.for_url(self._workdir_root, cand.url)

        try:
            thread = self._fetch(cand.url)
        except Exception:
            log_rejection(
                coverage_log=self._log,
                summary_path=self._summary,
                issue_url=cand.url,
                source_type=cand.source_type,
                triage_verdict="ambiguous",
                fingerprint=None,
                rejection_reason="not_reproducible",
            )
            return

        # --- Triage (cached on the fetched thread contents) ---
        triage_hash = _hash(
            thread.url, thread.title, thread.body, *thread.comments
        )
        if workdir.should_skip_stage("triage", current_input_hash=triage_hash):
            cached = workdir.read_stage("triage")
            triage = TriageResult(**cached["output"])
        else:
            triage = self._triager.triage(thread)
            workdir.write_stage(
                "triage",
                {
                    "verdict": triage.verdict,
                    "fingerprint": triage.fingerprint,
                    "rejection_reason": triage.rejection_reason,
                    "summary": triage.summary,
                },
                input_hash=triage_hash,
            )

        if triage.verdict == "out_of_scope":
            log_rejection(
                coverage_log=self._log,
                summary_path=self._summary,
                issue_url=cand.url,
                source_type=cand.source_type,
                triage_verdict=triage.verdict,
                fingerprint=triage.fingerprint,
                rejection_reason=(
                    triage.rejection_reason or "out_of_scope_not_rendering_bug"
                ),
            )
            return

        if triage.verdict == "ambiguous":
            log_rejection(
                coverage_log=self._log,
                summary_path=self._summary,
                issue_url=cand.url,
                source_type=cand.source_type,
                triage_verdict=triage.verdict,
                fingerprint=triage.fingerprint,
                rejection_reason="out_of_scope_insufficient_info",
            )
            return

        if self._log.contains_fingerprint(triage.fingerprint):
            log_rejection(
                coverage_log=self._log,
                summary_path=self._summary,
                issue_url=cand.url,
                source_type=cand.source_type,
                triage_verdict=triage.verdict,
                fingerprint=triage.fingerprint,
                rejection_reason="duplicate_of_existing_scenario",
            )
            return

        slug = re.sub(r"\W+", "_", cand.title.lower()).strip("_")[:40] or "unnamed"
        proposed_scenario_id = f"r{index}_{slug}"

        # --- Draft (cached on thread + triage fingerprint + proposed id) ---
        draft_hash = _hash(
            triage_hash, triage.fingerprint, triage.summary, proposed_scenario_id
        )
        if workdir.should_skip_stage("draft", current_input_hash=draft_hash):
            cached = workdir.read_stage("draft")
            draft = DraftResult(**cached["output"])
        else:
            try:
                draft = self._drafter.draft(
                    thread, triage, scenario_id=proposed_scenario_id
                )
            except Exception:
                log_rejection(
                    coverage_log=self._log,
                    summary_path=self._summary,
                    issue_url=cand.url,
                    source_type=cand.source_type,
                    triage_verdict=triage.verdict,
                    fingerprint=triage.fingerprint,
                    rejection_reason="not_reproducible",
                )
                return
            workdir.write_stage(
                "draft",
                {
                    "scenario_id": draft.scenario_id,
                    "c_source": draft.c_source,
                    "md_body": draft.md_body,
                },
                input_hash=draft_hash,
            )

        # Trust the drafter's scenario_id — it is baked into the generated C
        # source and md. The proposed_scenario_id is only a hint to the drafter.
        scenario_id = draft.scenario_id

        vres = self._validator.validate(draft)
        if not vres.ok:
            log_rejection(
                coverage_log=self._log,
                summary_path=self._summary,
                issue_url=cand.url,
                source_type=cand.source_type,
                triage_verdict=triage.verdict,
                fingerprint=triage.fingerprint,
                rejection_reason="symptom_mismatch_at_validation",
            )
            return

        run_result = self._run_eval.run(scenario_id)
        if run_result.scorer_ambiguous:
            log_rejection(
                coverage_log=self._log,
                summary_path=self._summary,
                issue_url=cand.url,
                source_type=cand.source_type,
                triage_verdict=triage.verdict,
                fingerprint=triage.fingerprint,
                rejection_reason="eval_scorer_ambiguous",
            )
            return

        observed = classify_observed_helps(run_result.with_gla, run_result.code_only)
        failure_mode: Optional[str] = None
        failure_details: Optional[str] = None
        if observed.verdict == "no":
            try:
                fm = self._failure_mode_fn(
                    scenario_md=draft.md_body,
                    with_gla_diagnosis=run_result.with_gla.diagnosis_text,
                    code_only_diagnosis=run_result.code_only.diagnosis_text,
                    ground_truth="",
                )
                failure_mode = fm.category
                failure_details = fm.details
            except Exception:
                failure_mode = "other"

        from gla.eval.scenario import parse_key_value_bullets

        predicted_section = self._grep_section(
            draft.md_body, "predicted gla helpfulness"
        )
        predicted = parse_key_value_bullets(predicted_section).get("verdict")

        md_with_observed = self._append_observed_sections(
            draft.md_body,
            observed=observed,
            failure_category=failure_mode,
            failure_details=failure_details,
        )

        commit_scenario(
            eval_dir=self._eval_dir,
            scenario_id=scenario_id,
            c_source=draft.c_source,
            md_body=md_with_observed,
            coverage_log=self._log,
            summary_path=self._summary,
            issue_url=cand.url,
            source_type=cand.source_type,
            triage_verdict=triage.verdict,
            fingerprint=triage.fingerprint,
            tier="core",
            predicted_helps=predicted,
            observed_helps=observed.verdict,
            failure_mode=failure_mode,
            eval_summary={
                "with_gla": {
                    "correct_diagnosis": run_result.with_gla.correct_diagnosis,
                    "total_tokens": run_result.with_gla.total_tokens,
                },
                "code_only": {
                    "correct_diagnosis": run_result.code_only.correct_diagnosis,
                    "total_tokens": run_result.code_only.total_tokens,
                },
            },
        )

    @staticmethod
    def _grep_section(md_body: str, heading_lower: str) -> str:
        """Return the body of the `## <heading>` section, case-insensitive."""
        pattern = re.compile(
            rf"##\s+{re.escape(heading_lower)}\s*\n(.+?)(?=\n##\s+|\Z)",
            re.DOTALL | re.IGNORECASE,
        )
        m = pattern.search(md_body)
        return m.group(1) if m else ""

    @staticmethod
    def _append_observed_sections(
        md_body: str,
        observed,
        failure_category: Optional[str],
        failure_details: Optional[str],
    ) -> str:
        obs_section = (
            "\n## Observed GLA Helpfulness\n"
            f"- **Verdict**: {observed.verdict}\n"
            f"- **Evidence**: {observed.evidence}\n"
        )
        if failure_category:
            obs_section += (
                "\n## Failure Mode\n"
                f"- **Category**: {failure_category}\n"
                f"- **Details**: {failure_details or ''}\n"
            )
        return md_body.rstrip() + "\n" + obs_section


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Parse command-line arguments for the curation pipeline."""
    parser = argparse.ArgumentParser(
        description="GLA eval-set curation pipeline",
    )
    parser.add_argument("--eval-dir", default="tests/eval")
    parser.add_argument("--workdir", default=".eval-pipeline")
    parser.add_argument(
        "--log", default="docs/superpowers/eval/coverage-log.jsonl"
    )
    parser.add_argument(
        "--summary", default="docs/superpowers/eval/coverage-gaps.md"
    )
    parser.add_argument("--batch-quota", type=int, default=20)
    parser.add_argument(
        "--config", default=None,
        help="Path to YAML config file (overrides --batch-quota and queries)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Run discovery + triage only; do not draft/validate/commit",
    )
    parser.add_argument("--backend", default="auto",
                        choices=["auto", "anthropic", "claude-code"],
                        help="LLM backend: 'anthropic' uses the SDK (requires ANTHROPIC_API_KEY); "
                             "'claude-code' shells to the `claude` CLI; 'auto' picks claude-code "
                             "if ANTHROPIC_API_KEY is unset.")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    """CLI entry point. Constructs real stage instances and runs a batch."""
    args = parse_args(argv)
    cfg = load_config(args.config) if args.config else {}
    batch_quota = cfg.get("batch_quota", args.batch_quota)

    # Imports kept inside main() so `--help` / module import does not need
    # network-capable deps (e.g. anthropic) to load.
    from gla.eval.curation.llm_client import LLMClient, ClaudeCodeLLMClient
    from gla.eval.curation.discover import (
        GitHubSearch,
        Discoverer,
        DEFAULT_QUERIES,
    )
    from gla.eval.curation.triage import Triage, fetch_issue_thread
    from gla.eval.curation.draft import Draft
    from gla.eval.curation.validate import Validator
    from gla.eval.curation.run_eval import RunEval
    from gla.eval.curation.classify import attribute_failure_mode
    from gla.eval.harness import EvalHarness
    from gla.eval.runner import ScenarioRunner
    from gla.eval.llm_agent import build_agent_fn

    queries = cfg.get("queries", DEFAULT_QUERIES)

    backend = args.backend
    if backend == "auto":
        backend = "claude-code" if not os.environ.get("ANTHROPIC_API_KEY") else "anthropic"
    if backend == "claude-code":
        llm = ClaudeCodeLLMClient()
    else:
        llm = LLMClient.from_env()
    log = CoverageLog(args.log)
    disc = Discoverer(
        search=GitHubSearch(),
        coverage_log=log,
        queries=queries,
        batch_quota=batch_quota,
    )
    triager = Triage(llm_client=llm)
    drafter = Draft(llm_client=llm)

    # Shared ScenarioRunner for Validator + RunEval.
    runner = ScenarioRunner.from_env()
    validator = Validator(eval_dir=args.eval_dir, runner=runner)

    harness = EvalHarness(config={
        "eval_dir": args.eval_dir,
        "gla_base_url": os.environ.get("GLA_BASE_URL", "http://127.0.0.1:18080"),
        "gla_token": os.environ.get("GLA_TOKEN", ""),
        "shim_path": os.environ.get("GLA_SHIM_PATH", ""),
        "bazel_bin": os.environ.get("BAZEL", "bazel"),
        "repo_root": os.environ.get("GLA_REPO_ROOT"),
    })
    agent_fn = build_agent_fn()
    run_eval = RunEval(harness=harness, agent_fn=agent_fn)

    def failure_mode(**kwargs):
        return attribute_failure_mode(llm_client=llm, **kwargs)

    pipeline = CurationPipeline(
        discoverer=disc,
        fetch_thread=fetch_issue_thread,
        triager=triager,
        drafter=drafter,
        validator=validator,
        run_eval=run_eval,
        failure_mode_fn=failure_mode,
        eval_dir=args.eval_dir,
        workdir_root=args.workdir,
        coverage_log_path=args.log,
        summary_path=args.summary,
    )
    pipeline.run_batch()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
