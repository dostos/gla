"""Per-candidate journey records for a single mining run.

One JourneyRow per discovered URL. Phase outcomes for skipped phases are
None. The row is the source of truth for both per-run reporting and
cross-run analysis (cat runs/*/journey.jsonl | jq).
"""
from __future__ import annotations
import json
from dataclasses import dataclass, field, asdict
from enum import Enum
from pathlib import Path
from typing import Optional


class TerminalReason(str, Enum):
    # SELECT terminal reasons
    DUPLICATE_URL = "duplicate_url"
    FETCH_FAILED = "fetch_failed"
    BELOW_MIN_SCORE = "below_min_score"
    NOT_SELECTED = "not_selected"  # ranked too low for top_k / per_cell_cap
    TRIAGE_REJECTED = "triage_rejected"  # caught by classify_score reject rules
    # Used when --max-phase=select stops the pipeline at a successful selection.
    SELECT_DONE = "select_done"
    # PRODUCE terminal reasons
    EXTRACTION_FAILED = "extraction_failed"
    VALIDATION_FAILED = "validation_failed"
    # Used when --max-phase=produce stops the pipeline at a successful draft.
    PRODUCE_DONE = "produce_done"
    # JUDGE terminal reasons
    EVALUATE_TIMEOUT = "evaluate_timeout"
    EVALUATE_ERROR = "evaluate_error"
    NOT_HELPFUL = "not_helpful"  # helps_verdict=no
    COMMITTED = "committed"


@dataclass
class SelectOutcome:
    deduped: bool
    fetched: bool
    taxonomy_cell: Optional[str]
    score: int
    score_reasons: list[str] = field(default_factory=list)
    selected: bool = False


@dataclass
class ProduceOutcome:
    extracted: bool = False
    validated: bool = False


@dataclass
class JudgeOutcome:
    with_gla_score: Optional[float] = None
    code_only_score: Optional[float] = None
    helps_verdict: Optional[str] = None  # "yes" | "no" | "ambiguous"
    committed_as: Optional[str] = None


@dataclass
class TokenSpend:
    triage: int = 0
    draft: int = 0
    evaluate: int = 0

    @property
    def total(self) -> int:
        return self.triage + self.draft + self.evaluate


@dataclass
class JourneyRow:
    url: str
    run_id: str
    discovered_at: str
    discovery_query: str
    select: SelectOutcome
    produce: Optional[ProduceOutcome] = None
    judge: Optional[JudgeOutcome] = None
    tokens: TokenSpend = field(default_factory=TokenSpend)
    cache_hit: bool = False
    terminal_phase: str = "select"  # "select" | "produce" | "judge"
    terminal_reason: str = TerminalReason.NOT_SELECTED.value

    @classmethod
    def dropped_at_select(cls, *, url, run_id, discovered_at, discovery_query,
                           select, terminal_reason) -> "JourneyRow":
        return cls(url=url, run_id=run_id, discovered_at=discovered_at,
                   discovery_query=discovery_query, select=select,
                   produce=None, judge=None,
                   terminal_phase="select", terminal_reason=terminal_reason)

    def to_dict(self) -> dict:
        d = {
            "url": self.url,
            "run_id": self.run_id,
            "discovered_at": self.discovered_at,
            "discovery_query": self.discovery_query,
            "select": asdict(self.select),
            "produce": asdict(self.produce) if self.produce else None,
            "judge": asdict(self.judge) if self.judge else None,
            "tokens": {**asdict(self.tokens), "total": self.tokens.total},
            "cache_hit": self.cache_hit,
            "terminal_phase": self.terminal_phase,
            "terminal_reason": self.terminal_reason,
        }
        return d


class JourneyWriter:
    """Append-only JSONL writer. One file per run."""
    def __init__(self, path: Path):
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)

    def append(self, row: JourneyRow) -> None:
        with self.path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(row.to_dict()) + "\n")

    def read_all(self) -> list[dict]:
        if not self.path.exists():
            return []
        return [json.loads(line) for line in self.path.read_text(encoding="utf-8").splitlines() if line.strip()]
