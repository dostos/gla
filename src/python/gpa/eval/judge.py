"""Thin wrapper around the LLM-judge call for semantic-match scoring.

Reuses :class:`gpa.eval.curation.llm_client.LLMClient` so we don't take
any new third-party dependencies.  The canonical prompt lives in this
module so :func:`gpa.eval.scorer.judge_semantic_match` can delegate here
and keep the prompt in one place.
"""
from __future__ import annotations

import re
import subprocess
from pathlib import Path
from typing import Any, Optional


# The judge prompt.  Intentionally terse — the judge is asked to produce
# a single lowercase token on the last line.  Any prose above that token
# is ignored by the post-processor.
_JUDGE_SYSTEM_PROMPT = """\
You are judging whether two patch descriptions address the same bug.

Compare two patch descriptions. Do they address the same root cause and
produce the same behavioral effect?

Answer with exactly one word on the last line:
  - full    — same root cause, same behavioral effect
  - partial — related root cause or effect overlaps but is not equivalent
  - none    — different bug or no meaningful overlap

Do not output anything after the verdict word.
"""


def _build_judge_message(
    agent_change_summary: str,
    ground_truth_change_summary: str,
) -> str:
    return (
        "PROPOSED CHANGE:\n"
        f"{agent_change_summary.strip()}\n\n"
        "GROUND-TRUTH CHANGE:\n"
        f"{ground_truth_change_summary.strip()}\n\n"
        "Verdict (single word: full | partial | none):"
    )


_VERDICT_RE = re.compile(r"\b(full|partial|none)\b", re.IGNORECASE)


def _extract_verdict(response_text: str) -> str:
    """Scan the response for a valid verdict token and return it.

    Prefers the LAST occurrence (matching the "single word on the last
    line" instruction).  Returns ``"none"`` when no token is found — the
    safe fallback given we can't score without a verdict.
    """
    if not response_text:
        return "none"
    matches = _VERDICT_RE.findall(response_text)
    if not matches:
        return "none"
    return matches[-1].lower()


def run_semantic_judge(
    agent_change_summary: str,
    ground_truth_change_summary: str,
    llm_client: Any,
) -> str:
    """Invoke the LLM judge and return a verdict in ``{full, partial, none}``.

    Failures (network errors, empty responses, unparseable output) all
    degrade to ``"none"`` — the conservative choice, since we'd rather
    undercount than falsely inflate solve rates.
    """
    if llm_client is None:
        return "none"
    try:
        resp = llm_client.complete(
            system=_JUDGE_SYSTEM_PROMPT,
            messages=[
                {
                    "role": "user",
                    "content": _build_judge_message(
                        agent_change_summary, ground_truth_change_summary
                    ),
                }
            ],
        )
    except Exception:
        return "none"

    text = getattr(resp, "text", None) or ""
    return _extract_verdict(text)


def fetch_pr_diff_summary(
    fix_sha: str,
    snapshot_root: Optional[Path],
    *,
    max_bytes: int = 6000,
) -> str:
    """Return a compact string summarising the fix-PR's diff.

    Combines `git log -1 --format=%B <sha>` (commit message) with
    `git show --stat <sha>` (per-file change counts). Truncated to
    `max_bytes`. Best-effort: any subprocess failure or missing
    snapshot returns empty string — the judge tier degrades gracefully
    when ground-truth summary can't be assembled.
    """
    if not snapshot_root or not Path(snapshot_root).is_dir() or not fix_sha:
        return ""
    parts: list[str] = []
    try:
        log = subprocess.run(
            ["git", "log", "-1", "--format=%B", fix_sha],
            cwd=Path(snapshot_root), capture_output=True, text=True,
            timeout=10, check=True,
        )
        parts.append(log.stdout.strip())
    except (subprocess.SubprocessError, OSError):
        pass
    try:
        stat = subprocess.run(
            ["git", "show", "--stat", "--format=", fix_sha],
            cwd=Path(snapshot_root), capture_output=True, text=True,
            timeout=10, check=True,
        )
        parts.append(stat.stdout.strip())
    except (subprocess.SubprocessError, OSError):
        pass
    out = "\n\n".join(p for p in parts if p)
    if len(out) > max_bytes:
        out = out[:max_bytes] + "\n... [truncated]"
    return out


__all__ = [
    "run_semantic_judge",
    "fetch_pr_diff_summary",
]
