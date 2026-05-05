"""Classify observed helpfulness of OpenGPA vs code-only from two EvalResult objects.

6-rule decision table (first match wins):
  Rule 1: correct_with_gla AND NOT correct_code_only  -> yes
  Rule 2: NOT correct_with_gla AND correct_code_only   -> no  (GPA regressed)
  Rule 3: both wrong                                   -> no
  Rule 4: both correct AND ratio < 0.5                 -> yes
  Rule 5: both correct AND ratio > 0.8                 -> no
  Rule 6: both correct AND 0.5 <= ratio <= 0.8         -> ambiguous

Guard: code_only.total_tokens <= 0 -> ambiguous (avoid division by zero).
"""
from __future__ import annotations
import json
import re
from dataclasses import dataclass
from typing import Optional
from gpa.eval.metrics import EvalResult
from gpa.eval.curation.llm_client import LLMClient
from gpa.eval.curation.prompts import load_prompt


_VALID_CATEGORIES = {
    "shader_compile_not_exposed", "framework_internal_state",
    "needs_temporal_diff", "driver_specific",
    "bug_requires_multi_frame_capture", "scorer_ambiguous",
    "gpa_query_insufficient", "other",
}


@dataclass
class ObservedClassification:
    verdict: str   # "yes" | "no" | "ambiguous"
    evidence: str


@dataclass
class FailureModeResult:
    category: str
    suggested_new_category: Optional[str]
    details: str


def _solved(result: EvalResult) -> bool:
    """True when the verdict orchestrator marked this result as solved.

    R17 deleted the legacy keyword-based DiagnosisScorer
    (correct_diagnosis / correct_fix). The verdict orchestrator's
    `solved` flag is now the single source of truth across file_level,
    prose, and judge scoring tiers.
    """
    return bool((result.verdict or {}).get("solved"))


def classify_observed_helps(
    with_gla: EvalResult, code_only: EvalResult
) -> ObservedClassification:
    """Return an ObservedClassification based on the 6-rule decision table."""
    # Rule 1
    if _solved(with_gla) and not _solved(code_only):
        return ObservedClassification(
            "yes",
            "solved_with_gla=True, solved_code_only=False",
        )
    # Rule 2
    if not _solved(with_gla) and _solved(code_only):
        return ObservedClassification(
            "no",
            "OpenGPA regressed vs code_only",
        )
    # Rule 3: both wrong
    if not _solved(with_gla) and not _solved(code_only):
        return ObservedClassification(
            "no",
            "both modes wrong",
        )
    # Both correct from here — guard against degenerate token count first
    if code_only.total_tokens <= 0:
        return ObservedClassification(
            "ambiguous",
            f"code_only tokens degenerate ({code_only.total_tokens})",
        )
    ratio = with_gla.total_tokens / code_only.total_tokens
    # Rule 4
    if ratio < 0.5:
        return ObservedClassification(
            "yes",
            f"both correct, token_ratio={ratio:.2f} < 0.5",
        )
    # Rule 5
    if ratio > 0.8:
        return ObservedClassification(
            "no",
            f"both correct, token_ratio={ratio:.2f} > 0.8",
        )
    # Rule 6
    return ObservedClassification(
        "ambiguous",
        f"both correct, token_ratio={ratio:.2f} in [0.5, 0.8]",
    )


def attribute_failure_mode(
    llm_client: LLMClient,
    scenario_md: str,
    with_gpa_diagnosis: str,
    code_only_diagnosis: str,
    ground_truth: str,
) -> FailureModeResult:
    """Call the LLM to categorize WHY OpenGPA did not help in a given scenario."""
    system = load_prompt("classify_failure_mode_system")
    user = (
        f"SCENARIO_MD:\n{scenario_md}\n\n"
        f"GROUND_TRUTH:\n{ground_truth}\n\n"
        f"WITH_GPA_DIAGNOSIS:\n{with_gpa_diagnosis}\n\n"
        f"CODE_ONLY_DIAGNOSIS:\n{code_only_diagnosis}\n"
    )
    resp = llm_client.complete(system=system,
                               messages=[{"role": "user", "content": user}])
    m = re.search(r"```json\s*\n(.+?)\n```", resp.text, re.DOTALL)
    raw = m.group(1) if m else resp.text
    d = json.loads(raw)
    cat = d.get("category", "other")
    if cat not in _VALID_CATEGORIES:
        cat = "other"
    return FailureModeResult(
        category=cat,
        suggested_new_category=d.get("suggested_new_category"),
        details=d.get("details", "")[:500],
    )
