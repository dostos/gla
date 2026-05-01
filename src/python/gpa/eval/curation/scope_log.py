"""Cross-run search-scope log.

Each mining run aggregates its journey rows by `discovery_query` and
appends one row per unique query to `<workdir>/scope-log.jsonl`. The
log is the cross-run source of truth for "what scope have we already
mined" — a future run can `jq` it to find unexplored queries, lowest-
yield queries to retire, or repos we haven't touched.

This is deliberately simple: append-only JSONL, no schema migration,
no LLM. Analysis is `cat scope-log.jsonl | jq ...`.

Row shape::

    {
      "run_id": "2026-05-01-101530-a1b2c3d4",
      "ts": "2026-05-01T10:15:30Z",
      "source": "issue" | "commit" | "stackoverflow" | "unknown",
      "query": "repo:bevyengine/bevy is:closed flicker",
      "repos": ["bevyengine/bevy"],     # extracted from query when github
      "yielded": 5,                      # candidates discovered for this query
      "selected": 1,                     # candidates that passed SELECT
      "extracted": 1,                    # candidates that passed PRODUCE.extract
      "committed": 0                     # candidates committed in JUDGE
    }
"""
from __future__ import annotations

import json
import re
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path


_REPO_RE = re.compile(r"repo:([^\s]+)")


def _extract_repos(query: str) -> list[str]:
    """Pull `repo:owner/name` tokens from a GitHub search string."""
    return _REPO_RE.findall(query)


def _classify_source(row: dict) -> str:
    """Best-effort source kind from a journey row.

    Journey rows don't carry `source_query_kind` directly; we infer from
    the query string (presence of `repo:` and `is:issue|pr|commit`).
    """
    q = row.get("discovery_query") or ""
    if isinstance(q, str):
        if "is:commit" in q or "/commit/" in q:
            return "commit"
        if "stackoverflow" in q.lower():
            return "stackoverflow"
        if "repo:" in q or "is:issue" in q or "is:pr" in q:
            return "issue"
    elif isinstance(q, list):
        # Stackoverflow tag-list payload
        return "stackoverflow"
    return "unknown"


def aggregate_scope(*, journey_path: Path, run_id: str,
                    ts: str | None = None) -> list[dict]:
    """Read a single run's journey.jsonl and emit one scope row per
    unique discovery_query.
    """
    if not journey_path.exists():
        return []
    rows = [
        json.loads(line) for line in journey_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    timestamp = ts or datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")

    by_query: dict[str, list[dict]] = defaultdict(list)
    for r in rows:
        q = r.get("discovery_query") or ""
        if isinstance(q, list):
            q = json.dumps(sorted(q))
        by_query[q].append(r)

    out = []
    for query, group in by_query.items():
        yielded = len(group)
        selected = sum(1 for r in group if (r.get("select") or {}).get("selected"))
        extracted = sum(1 for r in group if (r.get("produce") or {}).get("extracted"))
        committed = sum(
            1 for r in group
            if (r.get("judge") or {}).get("committed_as")
        )
        source = _classify_source(group[0])
        out.append({
            "run_id": run_id,
            "ts": timestamp,
            "source": source,
            "query": query,
            "repos": _extract_repos(query),
            "yielded": yielded,
            "selected": selected,
            "extracted": extracted,
            "committed": committed,
        })

    out.sort(key=lambda r: r["query"])
    return out


def append_scope_rows(*, scope_log_path: Path, rows: list[dict]) -> None:
    """Append rows to the cross-run scope-log JSONL."""
    if not rows:
        return
    scope_log_path.parent.mkdir(parents=True, exist_ok=True)
    with scope_log_path.open("a", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r) + "\n")


def queries_already_mined(*, scope_log_path: Path) -> set[str]:
    """Return the set of query strings already represented in the log.

    Useful for an operator who wants to filter a candidate query pack
    against previously-mined queries before launching a run.
    """
    if not scope_log_path.exists():
        return set()
    out = set()
    for line in scope_log_path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            out.add(json.loads(line)["query"])
        except (KeyError, json.JSONDecodeError):
            continue
    return out


def repos_already_mined(*, scope_log_path: Path) -> Counter:
    """Histogram of repos mined across all runs (with counts).

    A future run can use this to bias toward unexplored repos: any repo
    not in the histogram, or with a low count, is a fresh candidate.
    """
    if not scope_log_path.exists():
        return Counter()
    c: Counter = Counter()
    for line in scope_log_path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            row = json.loads(line)
            for repo in row.get("repos") or []:
                c[repo] += 1
        except json.JSONDecodeError:
            continue
    return c
