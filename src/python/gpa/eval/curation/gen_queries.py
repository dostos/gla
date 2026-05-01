"""Generate new mining queries from a free-form instruction.

This is the only LLM-using CLI in the curation package besides the
opt-in --evaluate path. The job is narrow: take a natural-language
instruction (e.g. "find WebGPU compute shader bugs in repos we
haven't touched"), look at the cross-run scope log to know what's
already been mined, and ask an LLM to propose new GitHub Search
queries that probe unexplored scope.

Output is a YAML fragment ready to be merged into a queries pack.
The LLM's proposals are filtered against the scope log so duplicates
never reach the YAML.

Usage::

    python -m gpa.eval.curation.gen_queries \\
        --instruction "WebGPU compute shader artifacts" \\
        --scope-log .eval-pipeline/scope-log.jsonl \\
        --out /tmp/new_queries.yaml \\
        --max-queries 10

The output is a draft — review it before committing or feeding into
``gpa.eval.curation.run``. The dedup is exact-string against the scope
log; near-duplicates (same repo, similar keywords) still need a human
eye.
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any, Optional

import yaml

from gpa.eval.curation.scope_log import (
    queries_already_mined,
    repos_already_mined,
)


_SYSTEM_PROMPT = """You generate GitHub Search query strings for mining \
graphics rendering bugs. Each query must be a valid GitHub search \
expression that returns issues or merged PRs from real repos. Prefer \
narrowly-scoped queries (one or two repos, specific keywords, \
is:closed/is:merged + reason:completed/fix-PR signals) over broad \
shotgun queries.

You are given:
1. The user's INSTRUCTION (what kind of bugs to mine).
2. ALREADY_MINED queries (do NOT propose any of these literally).
3. REPO_HISTOGRAM showing repos already touched and how many times.

Your output is JSON only, no commentary:

{"queries": ["...", "..."]}

Rules:
- Each query must be a single string suitable for GitHub Search.
- Bias toward repos NOT in REPO_HISTOGRAM, or with low count.
- Do NOT propose any string that appears in ALREADY_MINED.
- Use closing-PR signals when possible: "is:closed reason:completed" or
  "is:merged \\"fix:\\"".
- Avoid feature-request keywords ("please add", "would be nice").
- Stay focused on the user's INSTRUCTION; don't drift into adjacent topics.
"""


def build_user_message(*, instruction: str,
                       already_mined: set[str],
                       repos: Counter,
                       max_queries: int) -> str:
    mined_lines = "\n".join(f"  - {q!r}" for q in sorted(already_mined))
    repo_lines = "\n".join(f"  {repo}: {count}"
                            for repo, count in repos.most_common(50))
    return (
        f"INSTRUCTION:\n{instruction}\n\n"
        f"ALREADY_MINED ({len(already_mined)} queries):\n"
        f"{mined_lines or '  (none)'}\n\n"
        f"REPO_HISTOGRAM ({len(repos)} repos already touched):\n"
        f"{repo_lines or '  (none)'}\n\n"
        f"Propose up to {max_queries} new queries probing scope NOT covered above. "
        f"JSON output only."
    )


def parse_llm_response(text: str) -> list[str]:
    """Extract a list of query strings from the LLM's reply.

    Tolerates fenced code blocks (```json ... ```) and stray prose
    before/after the JSON.
    """
    # Strip fenced markdown if present
    txt = text.strip()
    if txt.startswith("```"):
        # Drop opening fence (with or without language tag) and closing fence
        lines = txt.splitlines()
        # Skip the first line (```json or ```), find the closing ```
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        txt = "\n".join(lines)

    # Find the first { and matching final }
    start = txt.find("{")
    end = txt.rfind("}")
    if start == -1 or end == -1 or end < start:
        raise ValueError(f"no JSON object found in LLM response: {text[:200]!r}")
    obj = json.loads(txt[start:end + 1])
    queries = obj.get("queries") or []
    if not isinstance(queries, list):
        raise ValueError(f"queries field is not a list: {queries!r}")
    return [str(q).strip() for q in queries if str(q).strip()]


def filter_duplicates(*, proposed: list[str],
                       already_mined: set[str]) -> tuple[list[str], list[str]]:
    """Split proposed queries into (kept, dropped). dropped = exact dupes."""
    kept, dropped = [], []
    seen_in_batch: set[str] = set()
    for q in proposed:
        if q in already_mined or q in seen_in_batch:
            dropped.append(q)
        else:
            kept.append(q)
            seen_in_batch.add(q)
    return kept, dropped


def write_yaml_fragment(*, queries: list[str], out_path: Path,
                         instruction: str, batch_quota: int) -> None:
    """Write a queries.yaml fragment that gpa.eval.curation.run can consume."""
    payload = {
        "# instruction": instruction,
        "batch_quota": batch_quota,
        "queries": {
            "issue": queries,
        },
    }
    # yaml.safe_dump quotes the "# instruction" key oddly; emit a header line manually.
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", encoding="utf-8") as f:
        f.write(f"# Generated from instruction: {instruction!r}\n")
        f.write(f"# Pre-deduped against the scope log at generation time.\n")
        f.write(f"batch_quota: {batch_quota}\n")
        yaml.safe_dump(
            {"queries": {"issue": queries}},
            f, sort_keys=False, default_flow_style=False, width=200,
        )


def parse_args(argv: Optional[list[str]] = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        prog="gpa.eval.curation.gen_queries",
        description="Generate new mining queries from a free-form instruction, "
                    "deduped against an existing scope-log.",
    )
    p.add_argument("--instruction", required=True,
                   help="Natural-language description of what to mine.")
    p.add_argument("--scope-log", default=".eval-pipeline/scope-log.jsonl",
                   help="Path to cross-run scope log (default: "
                        ".eval-pipeline/scope-log.jsonl).")
    p.add_argument("--out", required=True,
                   help="Output queries.yaml fragment path.")
    p.add_argument("--max-queries", type=int, default=10,
                   help="Maximum queries to propose. Default: 10.")
    p.add_argument("--batch-quota", type=int, default=20,
                   help="batch_quota field written into the output yaml. "
                        "Default: 20.")
    p.add_argument("--llm-backend", default="api",
                   choices=["api", "claude-cli"],
                   help="LLM backend: 'api' (Anthropic SDK, needs "
                        "ANTHROPIC_API_KEY) or 'claude-cli' (shells out to "
                        "the `claude` CLI). Default: api.")
    p.add_argument("--model", default="claude-opus-4-7",
                   help="LLM model. Default: claude-opus-4-7.")
    return p.parse_args(argv)


def _build_llm_client(backend: str, model: str) -> Any:
    """Test seam for the LLM client."""
    if backend == "api":
        from gpa.eval.curation.llm_client import LLMClient
        return LLMClient.from_env(model=model)
    if backend == "claude-cli":
        from gpa.eval.curation.llm_client import ClaudeCodeLLMClient
        return ClaudeCodeLLMClient()
    raise ValueError(f"unknown llm backend: {backend}")


def main(argv: Optional[list[str]] = None,
         *, llm_client_factory=_build_llm_client) -> int:
    args = parse_args(argv)
    scope_log = Path(args.scope_log)
    already_mined = queries_already_mined(scope_log_path=scope_log)
    repos = repos_already_mined(scope_log_path=scope_log)

    user_msg = build_user_message(
        instruction=args.instruction,
        already_mined=already_mined,
        repos=repos,
        max_queries=args.max_queries,
    )

    client = llm_client_factory(args.llm_backend, args.model)
    resp = client.complete(
        system=_SYSTEM_PROMPT,
        messages=[{"role": "user", "content": user_msg}],
        cache_system=True,
    )

    proposed = parse_llm_response(resp.text)
    kept, dropped = filter_duplicates(
        proposed=proposed, already_mined=already_mined,
    )

    write_yaml_fragment(
        queries=kept, out_path=Path(args.out),
        instruction=args.instruction, batch_quota=args.batch_quota,
    )

    sys.stderr.write(
        f"gen_queries: {len(kept)} new, {len(dropped)} dropped as duplicates "
        f"(LLM proposed {len(proposed)} total)\n"
        f"  scope-log had {len(already_mined)} mined queries across "
        f"{len(repos)} repos\n"
        f"  output: {args.out}\n"
    )
    if dropped:
        sys.stderr.write(f"  dropped duplicates:\n")
        for q in dropped:
            sys.stderr.write(f"    - {q!r}\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
