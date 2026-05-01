"""Per-run directory layout: .eval-pipeline/runs/<run_id>/{config.yaml,journey.jsonl,issues/,summary.md}.

run_id format: YYYY-MM-DD-HHMMSS-<8-hex hash of config>. Stable for a given
(timestamp, config) pair so identical inputs from the same second collapse
into one run dir.
"""
from __future__ import annotations
import hashlib
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Optional


def _default_clock() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d-%H%M%S")


def generate_run_id(*, config_text: str,
                     clock: Optional[Callable[[], str]] = None) -> str:
    ts = (clock or _default_clock)()
    h = hashlib.sha256(config_text.encode("utf-8")).hexdigest()[:8]
    return f"{ts}-{h}"


@dataclass
class RunDir:
    root: Path
    run_id: str

    @property
    def config_path(self) -> Path: return self.root / "config.yaml"
    @property
    def journey_path(self) -> Path: return self.root / "journey.jsonl"
    @property
    def issues_dir(self) -> Path: return self.root / "issues"
    @property
    def summary_path(self) -> Path: return self.root / "summary.md"

    @classmethod
    def create(cls, *, root: Path, run_id: str, config_payload: str) -> "RunDir":
        run_root = root / "runs" / run_id
        run_root.mkdir(parents=True, exist_ok=True)
        rd = cls(root=run_root, run_id=run_id)
        rd.config_path.write_text(config_payload, encoding="utf-8")
        rd.issues_dir.mkdir(exist_ok=True)
        return rd
