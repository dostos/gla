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


# The judge prompt. Refined after R12c surfaced that a terse rubric
# collapses "sharp single-cause diagnosis vs multi-file refactor PR"
# into `none`, missing real solves. The new prompt explicitly admits
# matching one causal file in a multi-file refactor as `full`.
_JUDGE_SYSTEM_PROMPT = """\
You are judging whether an agent's bug diagnosis matches a maintainer's fix.

You will be shown:
  - PROPOSED CHANGE: the agent's free-form diagnosis + suggested fix.
  - GROUND-TRUTH CHANGE: the maintainer's commit message + diff hunks
    from the merged fix-PR.

Decision rubric (output exactly one of full | partial | none):

  full    — the agent identifies the actual root cause AND points at
    code site(s) (file, function, or symbol) that appear in the
    ground-truth diff. This applies even when:
    - the gt PR is a multi-file refactor bundling unrelated changes;
      naming ONE causal file with the right reasoning counts as full
    - the agent names methods/classes rather than file paths, as long
      as those symbols appear in the diff hunks

  partial — agent points at the right component or symptom but a
    different root cause or fix site than the gt; or names a
    contributing factor but misses the primary cause.

  none    — different bug entirely, or pure speculation with no
    overlap to the gt diff.

Output format: a single word (full|partial|none) on the last line.
Do not output anything after the verdict.
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
    """Return a compact string summarising the fix-PR for the LLM judge.

    Layout (in order, each truncated to fit `max_bytes` total):
      1. Commit message (`git log -1 --format=%B`).
      2. Short stat (`git diff --shortstat <sha>^..<sha>`).
      3. Diff hunks (`git show --no-color --no-prefix <sha>`).

    The diff hunks are the primary signal — without them the judge
    only sees file counts and tends to call sharp single-cause
    diagnoses against multi-file refactor PRs `none` (R12c finding).
    Best-effort: any subprocess failure or missing snapshot returns
    empty string.
    """
    if not snapshot_root or not Path(snapshot_root).is_dir() or not fix_sha:
        return ""
    parts: list[str] = []
    cwd = Path(snapshot_root)

    def _run(argv):
        # `errors="replace"` because merge commits sometimes carry
        # binary blobs (icons, fonts, textures) that aren't valid utf-8;
        # we don't want a single byte to kill the whole judge call.
        return subprocess.run(
            argv, cwd=cwd, capture_output=True, text=True,
            errors="replace", timeout=30, check=True,
        )

    # The snapshot was originally cloned at fix_parent_sha with depth=1,
    # so the fix_sha commit (and its parents) may not be in the local
    # repo. Without the parents `git show` thinks the merge added the
    # whole tree from nothing (millions of lines). Fetch with depth=2
    # so both the merge commit AND its first parent land locally —
    # that lets `git show` produce a real diff. Best effort: silent on
    # failure, the show below will then return empty.
    try:
        _run(["git", "cat-file", "-e", fix_sha + "^1"])
    except (subprocess.SubprocessError, OSError):
        try:
            _run(["git", "fetch", "--depth", "2", "origin", fix_sha])
        except (subprocess.SubprocessError, OSError):
            pass

    try:
        log = _run(["git", "log", "-1", "--format=%B", fix_sha])
        msg = log.stdout.strip()
        if msg:
            parts.append(f"=== Commit message ===\n{msg}")
    except (subprocess.SubprocessError, OSError):
        pass
    try:
        shortstat = _run(
            ["git", "show", "--shortstat", "--format=", fix_sha]
        )
        ss = shortstat.stdout.strip()
        if ss:
            parts.append(f"=== Short stat ===\n{ss}")
    except (subprocess.SubprocessError, OSError):
        pass
    try:
        # Skip binary diffs and cap per-file output so a giant merge
        # doesn't drown the relevant hunks. `--first-parent` keeps the
        # merge-commit case readable (we want the merge's net effect,
        # not every commit on the side branch).
        diff = _run([
            "git", "show",
            "--no-color", "--no-prefix",
            "--format=", "--first-parent", "--no-ext-diff",
            "--text",  # treat binary files as text (we'll truncate anyway)
            fix_sha,
        ])
        hunks = diff.stdout
        if hunks:
            parts.append(f"=== Diff hunks ===\n{hunks}")
    except (subprocess.SubprocessError, OSError):
        pass

    out = "\n\n".join(parts)
    if len(out) > max_bytes:
        out = out[:max_bytes] + "\n... [truncated]"
    return out


__all__ = [
    "run_semantic_judge",
    "fetch_pr_diff_summary",
]
