"""Scoring and reporting metrics for GLA evaluation harness."""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from typing import Optional

from gla.eval.scenario import ScenarioMetadata


@dataclass
class EvalResult:
    scenario_id: str
    mode: str                  # "with_gla" or "code_only"

    # Accuracy
    correct_diagnosis: bool
    correct_fix: bool
    diagnosis_text: str        # LLM's diagnosis

    # Efficiency
    input_tokens: int
    output_tokens: int
    total_tokens: int
    tool_calls: int            # 0 for code_only mode
    num_turns: int             # conversation turns
    time_seconds: float        # wall-clock seconds

    # Details
    model: str
    timestamp: str             # ISO-8601

    # Observed-helpfulness (optional, filled by curation pipeline)
    observed_helps: Optional[str] = None
    observed_helps_evidence: Optional[str] = None
    failure_mode: Optional[str] = None
    failure_mode_details: Optional[str] = None

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "EvalResult":
        return cls(**d)


# ---------------------------------------------------------------------------
# Keyword extraction helpers
# ---------------------------------------------------------------------------

def _extract_keywords(text: str) -> list[str]:
    """Extract meaningful lowercase words (>3 chars) from text."""
    # Strip code blocks and markdown formatting
    text = re.sub(r"```.*?```", " ", text, flags=re.DOTALL)
    text = re.sub(r"`[^`]+`", " ", text)
    words = re.findall(r"[a-zA-Z_][a-zA-Z0-9_]{3,}", text)
    return [w.lower() for w in words]


def _keyword_overlap_ratio(candidate: str, reference: str) -> float:
    """Return fraction of reference keywords that appear in candidate."""
    ref_kw = set(_extract_keywords(reference))
    if not ref_kw:
        return 0.0
    cand_kw = set(_extract_keywords(candidate))
    return len(ref_kw & cand_kw) / len(ref_kw)


# Threshold for considering a keyword match "correct"
_DIAGNOSIS_THRESHOLD = 0.25
_FIX_THRESHOLD = 0.25


class DiagnosisScorer:
    """Scores whether an LLM's diagnosis matches ground truth via keyword matching."""

    def __init__(
        self,
        diagnosis_threshold: float = _DIAGNOSIS_THRESHOLD,
        fix_threshold: float = _FIX_THRESHOLD,
    ):
        self._diag_thresh = diagnosis_threshold
        self._fix_thresh = fix_threshold

    def score(
        self, diagnosis: str, ground_truth: ScenarioMetadata
    ) -> tuple[bool, bool]:
        """Return (correct_diagnosis, correct_fix).

        Checks keyword overlap between the LLM's diagnosis text and the
        ground truth diagnosis / fix extracted from the scenario metadata.
        """
        diag_ratio = _keyword_overlap_ratio(
            diagnosis, ground_truth.ground_truth_diagnosis
        )
        fix_ratio = _keyword_overlap_ratio(
            diagnosis, ground_truth.ground_truth_fix
        )
        return (diag_ratio >= self._diag_thresh, fix_ratio >= self._fix_thresh)


# ---------------------------------------------------------------------------
# Report generation
# ---------------------------------------------------------------------------

class ReportGenerator:
    """Generates comparison reports from a list of EvalResult objects."""

    def generate_summary(self, results: list[EvalResult]) -> dict:
        """Aggregate metrics by scenario and mode.

        Returns a dict with keys:
            scenarios: dict[scenario_id -> dict[mode -> aggregated_metrics]]
            overall: overall aggregate statistics
        """
        from collections import defaultdict

        by_scenario: dict[str, dict[str, list[EvalResult]]] = defaultdict(
            lambda: defaultdict(list)
        )
        for r in results:
            by_scenario[r.scenario_id][r.mode].append(r)

        def _avg(values: list) -> Optional[float]:
            return sum(values) / len(values) if values else None

        def _agg(rs: list[EvalResult]) -> dict:
            return {
                "count": len(rs),
                "accuracy_diagnosis": _avg([int(r.correct_diagnosis) for r in rs]),
                "accuracy_fix": _avg([int(r.correct_fix) for r in rs]),
                "avg_total_tokens": _avg([r.total_tokens for r in rs]),
                "avg_input_tokens": _avg([r.input_tokens for r in rs]),
                "avg_output_tokens": _avg([r.output_tokens for r in rs]),
                "avg_tool_calls": _avg([r.tool_calls for r in rs]),
                "avg_turns": _avg([r.num_turns for r in rs]),
                "avg_time_seconds": _avg([r.time_seconds for r in rs]),
            }

        summary_scenarios: dict[str, dict] = {}
        for sid, modes in sorted(by_scenario.items()):
            summary_scenarios[sid] = {
                mode: _agg(rs) for mode, rs in sorted(modes.items())
            }

        # Overall aggregation per mode
        all_modes: dict[str, list[EvalResult]] = defaultdict(list)
        for r in results:
            all_modes[r.mode].append(r)

        overall: dict[str, dict] = {
            mode: _agg(rs) for mode, rs in sorted(all_modes.items())
        }

        # Token reduction: with_gla vs code_only
        token_reduction: Optional[float] = None
        if "with_gla" in overall and "code_only" in overall:
            gla_tok = overall["with_gla"].get("avg_total_tokens") or 0
            base_tok = overall["code_only"].get("avg_total_tokens") or 0
            if base_tok:
                token_reduction = (base_tok - gla_tok) / base_tok

        return {
            "scenarios": summary_scenarios,
            "overall": overall,
            "token_reduction_fraction": token_reduction,
        }

    def generate_markdown(self, results: list[EvalResult]) -> str:
        """Generate a human-readable markdown comparison report."""
        summary = self.generate_summary(results)
        lines: list[str] = []

        lines.append("# GLA Evaluation Report")
        lines.append("")
        lines.append(
            f"Generated: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}"
        )
        lines.append(f"Total results: {len(results)}")
        lines.append("")

        # Overall summary table
        lines.append("## Overall")
        lines.append("")
        overall = summary["overall"]
        modes = sorted(overall.keys())
        headers = ["Metric"] + modes
        lines.append("| " + " | ".join(headers) + " |")
        lines.append("| " + " | ".join(["---"] * len(headers)) + " |")

        metrics_display = [
            ("avg_total_tokens", "Avg Total Tokens"),
            ("avg_input_tokens", "Avg Input Tokens"),
            ("avg_output_tokens", "Avg Output Tokens"),
            ("avg_tool_calls", "Avg Tool Calls"),
            ("avg_turns", "Avg Turns"),
            ("avg_time_seconds", "Avg Time (s)"),
            ("accuracy_diagnosis", "Diagnosis Accuracy"),
            ("accuracy_fix", "Fix Accuracy"),
        ]
        for key, label in metrics_display:
            row = [label]
            for mode in modes:
                val = overall.get(mode, {}).get(key)
                if val is None:
                    row.append("—")
                elif isinstance(val, float):
                    row.append(f"{val:.3f}")
                else:
                    row.append(str(val))
            lines.append("| " + " | ".join(row) + " |")

        if summary["token_reduction_fraction"] is not None:
            pct = summary["token_reduction_fraction"] * 100
            lines.append("")
            lines.append(
                f"**Token reduction (with_gla vs code_only): {pct:.1f}%**"
            )

        lines.append("")

        # Per-scenario breakdown
        lines.append("## Per-Scenario Results")
        lines.append("")

        for sid, modes_data in summary["scenarios"].items():
            lines.append(f"### {sid}")
            lines.append("")
            mode_names = sorted(modes_data.keys())
            headers = ["Metric"] + mode_names
            lines.append("| " + " | ".join(headers) + " |")
            lines.append("| " + " | ".join(["---"] * len(headers)) + " |")

            for key, label in metrics_display:
                row = [label]
                for mode in mode_names:
                    val = modes_data.get(mode, {}).get(key)
                    if val is None:
                        row.append("—")
                    elif isinstance(val, float):
                        row.append(f"{val:.3f}")
                    else:
                        row.append(str(val))
                lines.append("| " + " | ".join(row) + " |")
            lines.append("")

        return "\n".join(lines)
