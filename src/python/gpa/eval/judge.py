"""Thin wrapper around the LLM-judge call for semantic-match scoring.

Reuses :class:`gpa.eval.curation.llm_client.LLMClient` so we don't take
any new third-party dependencies.  The canonical prompt lives in this
module so :func:`gpa.eval.scorer.judge_semantic_match` can delegate here
and keep the prompt in one place.
"""
from __future__ import annotations

import re
from typing import Any


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


__all__ = [
    "run_semantic_judge",
]
