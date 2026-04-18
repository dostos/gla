"""Scenario loader for OpenGPA evaluation harness.

Parses adversarial eval scenario .md files and provides structured
metadata for use by the evaluation harness.
"""
from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

import yaml


@dataclass
class ScenarioMetadata:
    id: str                            # e.g., "e1_state_leak"
    title: str                         # from .md H1
    bug_description: str               # what's wrong
    expected_output: str               # what it should look like
    actual_output: str                 # what it actually looks like
    ground_truth_diagnosis: str        # root cause
    ground_truth_fix: str              # how to fix (extracted from diagnosis)
    difficulty: int                    # 1-5
    adversarial_principles: list[str]  # bullet points from Adversarial Principles
    gla_advantage: str                 # how GLA helps
    source_path: str                   # absolute path to primary source file (main.c)
    binary_name: str                   # bazel target name (same as id)
    # --- Directory-form scenario fields ---
    scenario_dir: Optional[str] = None                      # absolute path to scenario dir
    source_files: list[str] = field(default_factory=list)   # basenames of source files in dir
    # --- New fields (all optional; existing E1-E10 continue to parse) ---
    source_url: Optional[str] = None
    source_type: Optional[str] = None           # "issue" | "fix_commit" | "stackoverflow"
    source_date: Optional[str] = None           # ISO-8601 date
    source_commit_sha: Optional[str] = None
    source_attribution: Optional[str] = None
    tier: Optional[str] = None                  # "core" | "showcase" | None for legacy
    api: Optional[str] = None                   # "opengl" | "opengles" | "webgl1" | "webgl2"
    framework: Optional[str] = None             # "none" | "three.js" | ...
    bug_signature: Optional[dict[str, Any]] = None   # {type: str, spec: dict}
    predicted_helps: Optional[str] = None       # "yes" | "no" | "ambiguous"
    predicted_helps_reasoning: Optional[str] = None
    observed_helps: Optional[str] = None        # "yes" | "no" | "ambiguous"
    observed_helps_evidence: Optional[str] = None
    failure_mode: Optional[str] = None
    failure_mode_details: Optional[str] = None


# Section heading aliases — maps canonical name -> list of accepted headings
_SECTION_ALIASES: dict[str, list[str]] = {
    "bug": ["bug"],
    "expected_output": ["expected correct output", "expected output"],
    "actual_output": ["actual broken output", "actual output"],
    "ground_truth_diagnosis": ["ground truth diagnosis"],
    "difficulty": ["difficulty rating", "difficulty"],
    "adversarial_principles": ["adversarial principles"],
    "gla_advantage": ["how gla helps", "how opengpa helps", "gla advantage", "opengpa advantage"],
    "source": ["source"],
    "tier": ["tier"],
    "api": ["api"],
    "framework": ["framework"],
    "bug_signature": ["bug signature"],
    "predicted_helps": ["predicted gla helpfulness", "predicted opengpa helpfulness", "predicted helpfulness"],
    "observed_helps": ["observed gla helpfulness", "observed opengpa helpfulness", "observed helpfulness"],
    "failure_mode": ["failure mode"],
}


def _normalise_heading(heading: str) -> str:
    return heading.strip().lower()


def parse_key_value_bullets(text: str) -> dict[str, str]:
    """Parse `- **Key**: value` bullet lines into a dict. Public helper."""
    out: dict[str, str] = {}
    for line in text.splitlines():
        m = re.match(r"-\s+\*\*(.+?)\*\*:\s*(.+)", line.strip())
        if m:
            key = m.group(1).strip().lower().replace(" ", "_")
            out[key] = m.group(2).strip()
    return out


# Internal callers may alias the private name to preserve stability inside
# scenario.py, but external callers should use `parse_key_value_bullets`.
_extract_key_value_bullets = parse_key_value_bullets


def _extract_yaml_block(text: str) -> Optional[dict]:
    """Extract the first ```yaml ... ``` fenced block and parse it, or return None."""
    m = re.search(r"```yaml\n(.+?)\n```", text, re.DOTALL)
    if not m:
        return None
    try:
        return yaml.safe_load(m.group(1))
    except yaml.YAMLError:
        return None


def _extract_single_line(text: str) -> Optional[str]:
    """Return the first non-empty trimmed line, or None."""
    for line in text.splitlines():
        s = line.strip()
        if s:
            return s
    return None


def _parse_md(text: str) -> dict[str, str]:
    """Parse a scenario .md file into a dict of canonical_key -> content."""
    # Build reverse lookup: normalised heading -> canonical key
    reverse: dict[str, str] = {}
    for canonical, aliases in _SECTION_ALIASES.items():
        for alias in aliases:
            reverse[alias] = canonical

    sections: dict[str, str] = {}
    current_key: Optional[str] = None
    current_lines: list[str] = []

    def flush():
        if current_key is not None:
            sections[current_key] = "\n".join(current_lines).strip()

    lines = text.splitlines()
    # Extract H1 title
    title = ""
    for line in lines:
        if line.startswith("# ") and not line.startswith("## "):
            title = line[2:].strip()
            break
    sections["_title"] = title

    for line in lines:
        if line.startswith("## "):
            flush()
            heading = _normalise_heading(line[3:])
            current_key = reverse.get(heading)
            current_lines = []
        elif current_key is not None:
            current_lines.append(line)

    flush()
    return sections


def _extract_difficulty(text: str) -> int:
    """Extract numeric difficulty 1-5 from a section string."""
    m = re.search(r"(\d)/5", text)
    if m:
        return int(m.group(1))
    # Fallback: keyword matching (strip markdown formatting first)
    lower = re.sub(r"[*_`]", "", text).lower()
    if "very hard" in lower or "expert" in lower:
        return 5
    if "hard" in lower:
        return 4
    if "medium" in lower:
        return 3
    if "easy" in lower:
        return 1
    return 3


def _extract_adversarial_principles(text: str) -> list[str]:
    """Extract bullet points (lines starting with - or *) as principle names."""
    principles: list[str] = []
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("- ") or stripped.startswith("* "):
            # Grab the bold title if present, otherwise use the whole line
            m = re.match(r"[-*]\s+\*\*(.+?)\*\*", stripped)
            if m:
                principles.append(m.group(1))
            else:
                principles.append(stripped[2:].strip())
    return principles


def _extract_fix(diagnosis_text: str) -> str:
    """Try to extract a 'fix' sentence from the diagnosis section.

    The diagnosis sections often contain 'The fix is ...' or 'Fix: ...'.
    Returns the relevant sentence(s) or the full text if nothing specific found.
    """
    sentences = re.split(r"(?<=[.!?])\s+", diagnosis_text)
    fix_sentences = [s for s in sentences if re.search(r"\bfix\b|\bcorrect\b|\bshould\b", s, re.IGNORECASE)]
    if fix_sentences:
        return " ".join(fix_sentences)
    return diagnosis_text


class ScenarioLoader:
    """Loads OpenGPA evaluation scenarios from the tests/eval directory."""

    def __init__(self, eval_dir: str = "tests/eval"):
        # Allow both relative (resolved from cwd) and absolute paths
        p = Path(eval_dir)
        if not p.is_absolute():
            # Try relative to this file's repo root first
            repo_root = Path(__file__).parent.parent.parent.parent.parent
            candidate = repo_root / eval_dir
            if candidate.exists():
                p = candidate
        self._eval_dir = p

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def load(self, scenario_id: str) -> ScenarioMetadata:
        """Load a single scenario by ID (e.g. 'e1_state_leak').

        Scenarios are stored as directories containing a scenario.md and
        one or more source files (``main.c`` + optional ``.h``, ``.glsl``,
        ``.js``, ``.html``, ``.json``, ...).
        """
        scenario_dir = self._eval_dir / scenario_id
        md_path = scenario_dir / "scenario.md"

        if not md_path.exists():
            raise FileNotFoundError(f"Scenario .md not found: {md_path}")

        # Discover source files in the scenario directory.
        # TODO: recurse into subdirs (e.g. upstream_snapshot/) once multi-file
        # scenarios ship; for v1 we only list top-level files.
        allowed_exts = {".c", ".h", ".glsl", ".vert", ".frag", ".js", ".html", ".json"}
        source_files: list[str] = []
        for entry in sorted(scenario_dir.iterdir()):
            if entry.is_dir():
                continue
            if entry.name == "scenario.md":
                continue
            if entry.suffix in allowed_exts:
                source_files.append(entry.name)

        # Primary source path: prefer main.c, else first .c alphabetically, else "".
        c_files = sorted(f for f in source_files if f.endswith(".c"))
        if "main.c" in c_files:
            primary = scenario_dir / "main.c"
        elif c_files:
            primary = scenario_dir / c_files[0]
        else:
            primary = None
        source_path = str(primary.resolve()) if primary is not None else ""

        text = md_path.read_text(encoding="utf-8")
        sections = _parse_md(text)

        difficulty_text = sections.get("difficulty", "")
        diagnosis_text = sections.get("ground_truth_diagnosis", "")

        source_kv = _extract_key_value_bullets(sections.get("source", ""))
        source_url = source_kv.get("url")
        source_type = source_kv.get("type")
        source_date = source_kv.get("date")
        _sha = source_kv.get("commit_sha", "")
        source_commit_sha = None if _sha in ("", "(n/a)") else _sha
        source_attribution = source_kv.get("attribution")

        tier = _extract_single_line(sections.get("tier", ""))
        api = _extract_single_line(sections.get("api", ""))
        framework = _extract_single_line(sections.get("framework", ""))
        bug_signature = _extract_yaml_block(sections.get("bug_signature", ""))

        predicted_kv = _extract_key_value_bullets(sections.get("predicted_helps", ""))
        predicted_helps = predicted_kv.get("verdict")
        predicted_helps_reasoning = predicted_kv.get("reasoning")

        observed_kv = _extract_key_value_bullets(sections.get("observed_helps", ""))
        observed_helps = observed_kv.get("verdict")
        observed_helps_evidence = observed_kv.get("evidence")

        failure_kv = _extract_key_value_bullets(sections.get("failure_mode", ""))
        failure_mode = failure_kv.get("category")
        failure_mode_details = failure_kv.get("details")

        return ScenarioMetadata(
            id=scenario_id,
            title=sections.get("_title", scenario_id),
            bug_description=sections.get("bug", ""),
            expected_output=sections.get("expected_output", ""),
            actual_output=sections.get("actual_output", ""),
            ground_truth_diagnosis=diagnosis_text,
            ground_truth_fix=_extract_fix(diagnosis_text),
            difficulty=_extract_difficulty(difficulty_text),
            adversarial_principles=_extract_adversarial_principles(
                sections.get("adversarial_principles", "")
            ),
            gla_advantage=sections.get("gla_advantage", ""),
            source_path=source_path,
            binary_name=scenario_id,
            scenario_dir=str(scenario_dir.resolve()),
            source_files=source_files,
            source_url=source_url,
            source_type=source_type,
            source_date=source_date,
            source_commit_sha=source_commit_sha,
            source_attribution=source_attribution,
            tier=tier,
            api=api,
            framework=framework,
            bug_signature=bug_signature,
            predicted_helps=predicted_helps,
            predicted_helps_reasoning=predicted_helps_reasoning,
            observed_helps=observed_helps,
            observed_helps_evidence=observed_helps_evidence,
            failure_mode=failure_mode,
            failure_mode_details=failure_mode_details,
        )

    def load_all(self) -> list[ScenarioMetadata]:
        """Load all available scenarios in sorted order.

        Discovers every subdirectory of ``eval_dir`` that contains a
        ``scenario.md`` file.
        """
        ids = sorted(
            p.parent.name
            for p in self._eval_dir.glob("*/scenario.md")
            if not p.parent.name.startswith(".")
        )
        return [self.load(sid) for sid in ids]
