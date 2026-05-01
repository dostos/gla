from __future__ import annotations
import json
import re
import subprocess
from dataclasses import dataclass, field
from typing import Optional

from gpa.eval.curation.llm_client import LLMClient
from gpa.eval.curation.prompts import load_prompt

_PR_REF_RE = re.compile(
    r"(?:^|[\s\(])"
    r"(?:https?://github\.com/([^/\s]+)/([^/\s]+)/(?:pull|issues|commit)/(?:(\d+)|([a-f0-9]{7,}))"
    r"|#(\d+))",
    re.IGNORECASE,
)

_MAX_LINKED_REF_BODY = 5000  # characters per fetched reference


def _extract_pr_refs(text: str, default_owner: str, default_repo: str) -> list[tuple[str, str, str]]:
    """Find GitHub references in text.

    Returns list of (owner, repo, ref) tuples. `ref` is either a commit SHA
    (hex string) or an issue/PR number (digit string). Deduplicated.

    Handles both:
    - Fully-qualified URLs: `https://github.com/owner/repo/pull/123`,
      `https://github.com/owner/repo/commit/abc123...`
    - Short-form references: `#123` (assumed to refer to default_owner/default_repo)

    Commit SHAs must be >= 7 hex chars (enforced in the regex pattern).
    """
    out: list[tuple[str, str, str]] = []
    seen: set[tuple[str, str, str]] = set()
    for m in _PR_REF_RE.finditer(text or ""):
        owner_url, repo_url, num_url, sha, num_short = m.groups()
        if owner_url and repo_url:
            owner, repo = owner_url, repo_url
            ref = num_url if num_url else sha
        elif num_short:
            owner, repo, ref = default_owner, default_repo, num_short
        else:
            continue
        if not ref:
            continue
        # sha group only fires for hex strings >= 7 chars (enforced by regex {7,}),
        # so no length check needed here — but guard anyway for safety.
        if sha and len(ref) < 7:
            continue
        key = (owner.lower(), repo.lower(), ref.lower())
        if key in seen:
            continue
        seen.add(key)
        out.append((owner, repo, ref))
    return out


def _fetch_linked_context(refs: list[tuple[str, str, str]], limit: int = 3) -> list[str]:
    """Fetch body + title of up to `limit` referenced issues/PRs/commits.

    Returns a list of rendered context blocks suitable for appending to an
    IssueThread.comments list.

    Failures are swallowed — a broken link must not break the parent fetch.
    """
    blocks: list[str] = []
    for i, (owner, repo, ref) in enumerate(refs[:limit]):
        try:
            # Commit refs are hex; issue/PR are digits
            if ref.isdigit():
                # Try PR first, fall back to issue
                endpoint_pr = f"repos/{owner}/{repo}/pulls/{ref}"
                proc = subprocess.run(
                    ["gh", "api", endpoint_pr],
                    capture_output=True, text=True,
                )
                if proc.returncode == 0:
                    data = json.loads(proc.stdout)
                    title = data.get("title", "")
                    body = (data.get("body") or "")[:_MAX_LINKED_REF_BODY]
                    blocks.append(
                        f"=== Linked PR #{ref}: {title} ===\n{body}"
                    )
                    continue
                # Fall back to issue
                endpoint_issue = f"repos/{owner}/{repo}/issues/{ref}"
                proc = subprocess.run(
                    ["gh", "api", endpoint_issue],
                    capture_output=True, text=True,
                )
                if proc.returncode == 0:
                    data = json.loads(proc.stdout)
                    title = data.get("title", "")
                    body = (data.get("body") or "")[:_MAX_LINKED_REF_BODY]
                    blocks.append(
                        f"=== Linked issue #{ref}: {title} ===\n{body}"
                    )
            else:
                # Commit ref
                endpoint = f"repos/{owner}/{repo}/commits/{ref}"
                proc = subprocess.run(
                    ["gh", "api", endpoint],
                    capture_output=True, text=True,
                )
                if proc.returncode == 0:
                    data = json.loads(proc.stdout)
                    message = (data.get("commit", {}).get("message", ""))[:_MAX_LINKED_REF_BODY]
                    blocks.append(
                        f"=== Linked commit {ref[:8]} ===\n{message}"
                    )
        except (subprocess.SubprocessError, json.JSONDecodeError):
            # Non-fatal — skip this ref
            continue
    return blocks


_VALID_CATEGORIES = {
    "state_leak", "uniform_lifecycle", "matrix_math", "numeric_precision",
    "depth_precision", "winding_culling", "sync", "shader_compile",
    "bind_point_collision", "other",
}

_VALID_VERDICTS = {"in_scope", "out_of_scope", "ambiguous"}

_VALID_REJECTIONS = {
    None, "out_of_scope_compile_error", "out_of_scope_not_rendering_bug",
    "out_of_scope_insufficient_info", "not_reproducible", "non_english",
}

# Drafter-routing classification.  Decides whether the drafter writes a C
# repro (graphics-lib-dev) or a maintainer-framing scenario (framework
# bugs).  None on legacy/cached results means "graphics-lib-dev" (back-compat
# default).  See iter-9 design in `docs/mining-yield-baseline.md`.
_VALID_BUG_CLASSES = {
    None,
    "graphics-lib-dev",
    "framework-internal",
    "consumer-misuse",
    "user-config",
}


@dataclass
class IssueThread:
    url: str
    title: str
    body: str
    comments: list[str] = field(default_factory=list)


@dataclass
class TriageResult:
    verdict: str
    fingerprint: str
    rejection_reason: Optional[str]
    summary: str
    # Drafter routing — see iter-9 bifurcation. None = legacy / unset =
    # graphics-lib-dev path. Values: graphics-lib-dev | framework-internal |
    # consumer-misuse | user-config.
    bug_class: Optional[str] = None


class Triage:
    def __init__(self, llm_client: LLMClient, model: str = "claude-opus-4-7"):
        self._llm = llm_client
        self._system = load_prompt("triage_system")

    def triage(self, thread: IssueThread) -> TriageResult:
        user = self._format_thread(thread)
        resp = self._llm.complete(
            system=self._system,
            messages=[{"role": "user", "content": user}],
        )
        parsed = self._parse_json_block(resp.text)
        return self._normalize(parsed)

    def _format_thread(self, t: IssueThread) -> str:
        parts = [f"URL: {t.url}", f"Title: {t.title}", "", "Body:", t.body]
        for i, c in enumerate(t.comments):
            parts.extend(["", f"Comment {i+1}:", c])
        return "\n".join(parts)

    @staticmethod
    def _parse_json_block(text: str) -> dict:
        m = re.search(r"```json\s*\n(.+?)\n```", text, re.DOTALL)
        raw = m.group(1) if m else text
        return json.loads(raw)

    def _normalize(self, d: dict) -> TriageResult:
        verdict = d.get("triage_verdict", "ambiguous")
        if verdict not in _VALID_VERDICTS:
            verdict = "ambiguous"
        fp = d.get("root_cause_fingerprint", "other:unknown")
        category, _, spec = fp.partition(":")
        if category not in _VALID_CATEGORIES:
            category, spec = "other", spec or "unknown"
        fp = f"{category}:{spec or 'unknown'}"

        reason = d.get("rejection_reason")
        if reason not in _VALID_REJECTIONS:
            reason = None

        bug_class = d.get("bug_class")
        if bug_class not in _VALID_BUG_CLASSES:
            bug_class = None
        return TriageResult(verdict=verdict, fingerprint=fp,
                            rejection_reason=reason,
                            summary=d.get("summary", "")[:200],
                            bug_class=bug_class)


def fetch_thread(url: str) -> IssueThread:
    """Dispatch to fetch_issue_thread, fetch_pr_thread, fetch_commit_thread,
    or SO fetcher."""
    if "stackoverflow.com/questions/" in url:
        from gpa.eval.curation.stackoverflow import fetch_stackoverflow_thread
        return fetch_stackoverflow_thread(url)
    if "/commit/" in url:
        return fetch_commit_thread(url)
    if "/pull/" in url:
        return fetch_pr_thread(url)
    return fetch_issue_thread(url)


def fetch_pr_thread(url: str) -> IssueThread:
    """Fetch a merged-PR thread as an ``IssueThread``.

    GitHub PR URLs (``.../pull/<n>``) need a different endpoint than issues:
    ``repos/<o>/<r>/pulls/<n>`` for the PR body + ``repos/<o>/<r>/issues/<n>/comments``
    for the conversation (PRs and issues share the numeric namespace, so the
    issues-endpoint comments work for PRs too). Linked issues mentioned in the
    PR body are pulled via the existing ``_fetch_linked_context`` helper so the
    drafter still sees the originating bug report when one is referenced.

    Mirrors :func:`fetch_issue_thread` shape so callers don't need to
    special-case PR URLs.
    """
    m = re.search(r"github\.com/([^/]+)/([^/]+)/pull/(\d+)", url)
    if not m:
        raise ValueError(f"Not a GitHub PR URL: {url}")
    owner, repo, number = m.group(1), m.group(2), m.group(3)

    pr_proc = subprocess.run(
        ["gh", "api", f"repos/{owner}/{repo}/pulls/{number}"],
        capture_output=True, text=True, check=True,
    )
    pr = json.loads(pr_proc.stdout)

    # PR comments live on the issues endpoint (shared numeric namespace).
    comments_proc = subprocess.run(
        ["gh", "api", f"repos/{owner}/{repo}/issues/{number}/comments"],
        capture_output=True, text=True, check=True,
    )
    comments = json.loads(comments_proc.stdout)

    title = pr.get("title", "")
    body = pr.get("body", "") or ""
    comment_bodies = [c.get("body", "") for c in comments]

    # Extract linked issues / PRs / commits the same way fetch_issue_thread does
    # so the drafter sees the originating bug report when the PR references one.
    all_text = "\n".join([body] + comment_bodies)
    refs = _extract_pr_refs(all_text, default_owner=owner, default_repo=repo)
    # Skip self-reference
    refs = [r for r in refs if not (r[0].lower() == owner.lower()
                                     and r[1].lower() == repo.lower()
                                     and r[2] == number)]
    linked_blocks = _fetch_linked_context(refs, limit=3)

    return IssueThread(
        url=url,
        title=title,
        body=body,
        comments=comment_bodies + linked_blocks,
    )


def fetch_issue_thread(url: str) -> IssueThread:
    m = re.search(r"github\.com/([^/]+)/([^/]+)/issues/(\d+)", url)
    if not m:
        raise ValueError(f"Not a GitHub issue URL: {url}")
    owner, repo, number = m.group(1), m.group(2), m.group(3)

    issue_proc = subprocess.run(
        ["gh", "api", f"repos/{owner}/{repo}/issues/{number}"],
        capture_output=True, text=True, check=True,
    )
    issue = json.loads(issue_proc.stdout)

    comments_proc = subprocess.run(
        ["gh", "api", f"repos/{owner}/{repo}/issues/{number}/comments"],
        capture_output=True, text=True, check=True,
    )
    comments = json.loads(comments_proc.stdout)

    title = issue.get("title", "")
    body = issue.get("body", "") or ""
    comment_bodies = [c.get("body", "") for c in comments]

    # GitHub's "linked PRs" sidebar exposes closing-PR refs only via GraphQL,
    # not via the REST issue body or comments. Fetch them so triage's
    # fix_pr_linked rule sees the link even when the body has no "Closes #N"
    # text. Best-effort: any failure is logged and skipped.
    closing_pr_refs = _fetch_closing_pr_refs(owner, repo, number)
    if closing_pr_refs:
        body = body.rstrip() + "\n\n" + "\n".join(
            f"Closes #{pr['number']} ({pr['url']})" for pr in closing_pr_refs
        )

    all_text = "\n".join([body] + comment_bodies)
    refs = _extract_pr_refs(all_text, default_owner=owner, default_repo=repo)
    # Skip references to the current issue itself
    refs = [r for r in refs if not (r[0].lower() == owner.lower()
                                     and r[1].lower() == repo.lower()
                                     and r[2] == number)]
    linked_blocks = _fetch_linked_context(refs, limit=3)

    return IssueThread(
        url=url,
        title=title,
        body=body,
        comments=comment_bodies + linked_blocks,
    )


def _fetch_closing_pr_refs(owner: str, repo: str, number: str) -> list[dict]:
    """Pull GitHub's sidebar `closedByPullRequestsReferences` via GraphQL.

    Returns a list of {"number": int, "url": str} dicts; empty on any
    failure (gh missing, auth failure, repo not found, network error).
    Best-effort by design — the caller falls back to body/comment text.
    """
    query = (
        "query($owner:String!,$repo:String!,$number:Int!){"
        "repository(owner:$owner,name:$repo){"
        "issue(number:$number){"
        "closedByPullRequestsReferences(first:5,includeClosedPrs:true){"
        "nodes{number url}}}}}"
    )
    try:
        proc = subprocess.run(
            ["gh", "api", "graphql",
             "-f", f"query={query}",
             "-F", f"owner={owner}", "-F", f"repo={repo}",
             "-F", f"number={number}"],
            capture_output=True, text=True, check=True,
        )
        data = json.loads(proc.stdout)
        nodes = (
            data.get("data", {}).get("repository", {}).get("issue", {})
                .get("closedByPullRequestsReferences", {}).get("nodes", [])
        )
        return [{"number": n["number"], "url": n["url"]} for n in (nodes or [])]
    except Exception:  # noqa: BLE001 — defensive: any failure falls back
        return []


def fetch_commit_thread(url: str) -> IssueThread:
    """Fetch a commit's message + diff as an IssueThread.

    Commit URL format: https://github.com/owner/repo/commit/<sha>
    Uses `gh api repos/{owner}/{repo}/commits/{sha}` which returns
    {sha, commit: {message, author}, files: [{filename, patch, ...}], ...}
    """
    m = re.search(r"github\.com/([^/]+)/([^/]+)/commit/([a-f0-9]+)", url)
    if not m:
        raise ValueError(f"Not a GitHub commit URL: {url}")
    owner, repo, sha = m.group(1), m.group(2), m.group(3)

    proc = subprocess.run(
        ["gh", "api", f"repos/{owner}/{repo}/commits/{sha}"],
        capture_output=True, text=True, check=True,
    )
    commit_data = json.loads(proc.stdout)

    message = commit_data.get("commit", {}).get("message", "")
    # Title is first line of message; body is rest
    lines = message.split("\n", 1)
    title = lines[0][:200]
    body = lines[1].strip() if len(lines) > 1 else ""

    # Extract diffs from `files`, but truncate aggressively — we only need enough
    # for Claude to see the fix pattern. Cap total diff to ~20KB.
    files = commit_data.get("files") or []
    diff_parts: list[str] = []
    total_size = 0
    MAX_DIFF_BYTES = 20000
    for f in files:
        patch = f.get("patch") or ""
        if not patch:
            continue
        filename = f.get("filename", "?")
        chunk = f"--- {filename}\n{patch}\n"
        if total_size + len(chunk) > MAX_DIFF_BYTES:
            remaining = MAX_DIFF_BYTES - total_size
            if remaining > 200:
                chunk = chunk[:remaining] + "\n... [truncated]"
                diff_parts.append(chunk)
            break
        diff_parts.append(chunk)
        total_size += len(chunk)

    diff = "\n".join(diff_parts)
    # Use "body" for commit message body, put diff into comments[] so the
    # existing Triage._format_thread renders it cleanly.
    comments = [f"=== Diff ===\n{diff}"] if diff else []

    return IssueThread(url=url, title=title, body=body, comments=comments)
