"""Deterministic field extraction from an issue thread + fix-PR.

Replaces the LLM-based draft.py for routine mining: produces the same
DraftResult shape using only regex + parsing. If required fields can't
be extracted, raises ExtractionFailure (the caller records this in the
journey row with terminal_reason="extraction_failed").

Required output fields (all must be derivable from the inputs):
  - user_report: cleaned body text (stripping HTML, normalising whitespace)
  - expected_section: text under "## Expected" / "Expected behaviour" / etc.
  - actual_section:   text under "## Actual" / "Actual behaviour" / etc.
  - fix_commit_sha:   from fix_pr["commit_sha"]
  - fix_pr_url:       from fix_pr["url"]
  - expected_files:   from fix_pr["files_changed"], filtered to source files
  - bug_signature_yaml: derived ground-truth block built from
                        expected_files + taxonomy_cell + fix_commit_sha
"""
from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from typing import Any


_SECTION_HEADERS = {
    "expected": [
        r"^#+\s*Expected",
        r"^\*\*Expected",
        r"^Expected\s+(behaviou?r|output|result)",
        r"^What I expected",
    ],
    "actual": [
        r"^#+\s*Actual",
        r"^\*\*Actual",
        r"^Actual\s+(behaviou?r|output|result)",
        r"^What actually",
        # Godot-style and other common trackers that describe symptoms under
        # a generic header instead of an Expected/Actual split.
        r"^#+\s*Issue description",
        r"^#+\s*Description",
        r"^#+\s*Steps to reproduce",
        r"^#+\s*What happen(ed|s)",
        r"^#+\s*Bug description",
    ],
}

_STRUCTURED_BODY_RE = re.compile(r"^#{2,}\s+\S", flags=re.MULTILINE)


class ExtractionFailure(Exception):
    """Raised when required fields cannot be extracted from the issue thread."""


@dataclass
class DraftResult:
    user_report: str
    expected_section: str
    actual_section: str
    fix_commit_sha: str
    fix_pr_url: str
    expected_files: list[str]
    bug_signature_yaml: str
    extras: dict[str, Any] = field(default_factory=dict)


def _clean_body(body: str) -> str:
    """Strip HTML comment blocks (PR templates), normalise CRLF, trim trailing
    whitespace per line, collapse runs of 3+ blank lines down to 2."""
    # Strip HTML comment blocks Bevy/three use as PR templates
    cleaned = re.sub(r"<!--.*?-->", "", body, flags=re.DOTALL)
    # Normalise CRLF
    cleaned = cleaned.replace("\r\n", "\n").replace("\r", "\n")
    # Strip trailing whitespace per line, collapse 3+ blank lines to 2
    lines = [line.rstrip() for line in cleaned.split("\n")]
    cleaned = "\n".join(lines)
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    return cleaned.strip()


def _extract_section(body: str, kind: str) -> str:
    """Find a section by header (any of the patterns for `kind`) and
    return the text up to the next # heading or EOF."""
    patterns = _SECTION_HEADERS[kind]
    for pat in patterns:
        m = re.search(pat, body, flags=re.IGNORECASE | re.MULTILINE)
        if m:
            start = m.end()
            tail = body[start:]
            next_h = re.search(r"^#+\s", tail, flags=re.MULTILINE)
            return (tail[: next_h.start()] if next_h else tail).strip()
    return ""


def _build_bug_signature(*, expected_files: list[str], fix_commit_sha: str) -> str:
    """Render a ground-truth bug-signature YAML block (type: code_location)."""
    files_yaml = "\n".join(f"    - {f}" for f in expected_files)
    return (
        "type: code_location\n"
        "spec:\n"
        "  expected_files:\n"
        f"{files_yaml}\n"
        f"  fix_commit: {fix_commit_sha}\n"
    )


def _filter_source_files(files: list[str]) -> list[str]:
    """Drop test, doc, example, and changelog files from fix-PR's files_changed.

    Path-segment heuristics catch the common layouts (e.g. /tests/, /docs/),
    and a basename heuristic catches inline test files such as
    `mesh_test.rs` or `test_foo.py` that don't sit under a /tests/ dir.

    Note (plan deviation): the plan's reference filter only checked path
    substrings ("/tests/", "/test/", ...). That alone wouldn't drop
    `crates/bevy_pbr/src/render/mesh_test.rs`, nor `tests/integration/...`
    when given as a leading-segment path with no leading slash. The plan's
    Step 3.6 assertion requires both to be dropped, so we additionally
    (a) check leading-segment matches (e.g. `tests/...`, `examples/...`)
    by splitting on '/', and (b) inspect the basename for `_test.<ext>` /
    `test_*.<ext>` patterns. All checks are case-insensitive.
    """
    excluded_segments = {
        "tests",
        "test",
        "__tests__",
        "docs",
        "examples",
        "example",
        "fixtures",
        "fixture",
    }
    excluded_basenames = {
        "package.json",
        "package-lock.json",
        "npm-shrinkwrap.json",
        "yarn.lock",
        "pnpm-lock.yaml",
        "bun.lockb",
    }
    keep: list[str] = []
    for f in files:
        low = f.lower()
        # Path-segment exclusions: any path segment that matches an excluded
        # name (e.g. `crates/.../tests/foo.rs` or `tests/integration/...`).
        segments = low.split("/")
        if any(seg in excluded_segments for seg in segments):
            continue
        # Substring exclusions: changelog & markdown documentation.
        if "changelog" in low or low.endswith(".md"):
            continue
        # Basename-level test heuristics: `mesh_test.rs`, `test_foo.py`, etc.
        base = os.path.basename(low)
        if base in excluded_basenames:
            continue
        stem, _, _ext = base.partition(".")
        if (
            stem.endswith("_test")
            or stem.startswith("test_")
            or ".test." in base
            or ".spec." in base
        ):
            continue
        keep.append(f)
    return keep


def extract_draft(
    *, thread: dict, fix_pr: dict, taxonomy_cell: str
) -> DraftResult:
    """Deterministically build a DraftResult from a fetched issue thread + fix PR.

    Raises ExtractionFailure if any required field can't be extracted. The
    caller (run.py orchestrator) records the failure as
    terminal_reason="extraction_failed" in the journey row.
    """
    body = thread.get("body") or ""
    body = _clean_body(body)
    if not body:
        raise ExtractionFailure("issue body is empty after cleaning")

    expected = _extract_section(body, "expected")
    actual = _extract_section(body, "actual")
    if not expected and not actual:
        # Short bodies (<1500 chars) without sections are acceptable as the
        # whole user_report. Longer bodies are accepted if they have ANY
        # recognizable section structure (`## ...` markdown headers) — the
        # body itself becomes the user_report. Only reject long unstructured
        # walls of text where we have nothing to anchor on.
        if len(body) > 1500 and not _STRUCTURED_BODY_RE.search(body):
            raise ExtractionFailure(
                "issue body lacks Expected/Actual sections and has no "
                "section structure, too long to use raw"
            )

    expected_files = _filter_source_files(fix_pr.get("files_changed") or [])
    if not expected_files:
        raise ExtractionFailure(
            "fix-PR files_changed had no source files after filtering"
        )

    fix_sha = fix_pr.get("commit_sha")
    fix_url = fix_pr.get("url")
    if not fix_sha or not fix_url:
        raise ExtractionFailure("fix-PR missing commit_sha or url")

    sig = _build_bug_signature(
        expected_files=expected_files, fix_commit_sha=fix_sha
    )

    return DraftResult(
        user_report=body,
        expected_section=expected,
        actual_section=actual,
        fix_commit_sha=fix_sha,
        fix_pr_url=fix_url,
        expected_files=expected_files,
        bug_signature_yaml=sig,
        extras={"taxonomy_cell": taxonomy_cell},
    )
