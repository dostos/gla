"""Context enrichment: fetch upstream source files at pre-fix SHA
so the drafter has the actual buggy code, not just thread discussion.

When a bug-report thread mentions a fix PR or commit, this module pre-fetches
the changed files' contents AT THE PR'S PARENT SHA (i.e. before the fix was
applied). That pre-fix state is the buggy code the drafter needs in order to
write an accurate ground-truth diagnosis and, optionally, to include the files
as ``upstream_snapshot/*`` in the generated scenario.
"""
from __future__ import annotations

import base64
import json
import re
import subprocess
from dataclasses import dataclass
from typing import Optional

_MAX_FILES_PER_REF = 10
_MAX_FILE_SIZE = 20_000  # chars; truncate larger files with a marker

# Regex to find PR references in thread text.
# Matches either a full PR URL or the short-form `#NNN`.
_PR_REF_RE = re.compile(
    r"https?://github\.com/([^/\s]+)/([^/\s]+)/pull/(\d+)"
    r"|#(\d+)",
    re.IGNORECASE,
)
# Regex for commit references (full URLs only; short-form SHAs are ambiguous).
_COMMIT_REF_RE = re.compile(
    r"https?://github\.com/([^/\s]+)/([^/\s]+)/commit/([a-f0-9]{7,})",
    re.IGNORECASE,
)

# Source-file extensions we want to snapshot. Tests, docs, lockfiles and YAML
# are skipped because they rarely contain the faulty rendering logic.
_SOURCE_EXTS = {
    ".c", ".h", ".cc", ".cpp", ".js", ".ts", ".glsl", ".vert",
    ".frag", ".wgsl", ".py", ".gd", ".gdshader",
}


@dataclass
class UpstreamFile:
    path: str           # e.g., "src/renderers/WebGLShadowMap.js"
    content: str        # file content at parent SHA
    ref: str            # "PR #12345" or "commit abc1234"
    truncated: bool     # True if content was truncated to _MAX_FILE_SIZE


def extract_refs(
    text: str, default_owner: str, default_repo: str
) -> list[tuple[str, str, str, str]]:
    """Extract ``(owner, repo, kind, id)`` tuples from thread text.

    ``kind`` is ``'pull'`` or ``'commit'``. ``id`` is a PR number (digits) or
    SHA (hex). Short-form ``#NNN`` uses ``default_owner``/``default_repo``.

    Dedups identical tuples and returns at most 10 unique references (in order
    of appearance) to bound fetch cost.
    """
    out: list[tuple[str, str, str, str]] = []
    seen: set[tuple[str, str, str, str]] = set()

    def _add(tup: tuple[str, str, str, str]) -> None:
        if tup not in seen and len(out) < 10:
            seen.add(tup)
            out.append(tup)

    # Commit URLs (full) — matched first so they win ordering over later PR refs.
    for m in _COMMIT_REF_RE.finditer(text or ""):
        _add((m.group(1), m.group(2), "commit", m.group(3).lower()))

    # PR URLs (full) and short-form #NNN.
    for m in _PR_REF_RE.finditer(text or ""):
        full_owner, full_repo, full_num, short_num = m.groups()
        if full_owner and full_repo and full_num:
            _add((full_owner, full_repo, "pull", full_num))
        elif short_num:
            _add((default_owner, default_repo, "pull", short_num))

    return out


def _fetch_file_at_ref(
    owner: str, repo: str, path: str, ref_sha: str, ref_label: str,
) -> Optional[UpstreamFile]:
    """Fetch a single file's contents at ``ref_sha`` via the GitHub contents API.

    Returns ``None`` on any failure (HTTP error, not base64, decode error).
    """
    try:
        proc = subprocess.run(
            ["gh", "api",
             f"repos/{owner}/{repo}/contents/{path}?ref={ref_sha}"],
            capture_output=True, text=True, timeout=30,
        )
        if proc.returncode != 0:
            return None
        cdata = json.loads(proc.stdout)
    except (subprocess.SubprocessError, json.JSONDecodeError):
        return None

    if cdata.get("encoding") != "base64":
        return None
    try:
        raw = base64.b64decode(cdata["content"]).decode("utf-8", errors="replace")
    except Exception:
        return None

    truncated = False
    if len(raw) > _MAX_FILE_SIZE:
        raw = raw[:_MAX_FILE_SIZE] + "\n/* ... [truncated] */\n"
        truncated = True
    return UpstreamFile(
        path=path, content=raw, ref=ref_label, truncated=truncated,
    )


def fetch_pr_files_at_parent(
    owner: str, repo: str, pr_number: str,
    max_files: int = _MAX_FILES_PER_REF,
) -> list[UpstreamFile]:
    """For a PR, fetch modified files' contents at the PR's parent (pre-fix) SHA.

    Steps:
      1. ``gh api repos/<o>/<r>/pulls/<n>`` → read ``base.sha`` (pre-merge base).
      2. ``gh api repos/<o>/<r>/pulls/<n>/files`` → list files changed.
      3. For each source file (up to ``max_files``):
         ``gh api repos/<o>/<r>/contents/<path>?ref=<base_sha>`` → content.

    Returns an empty list on any fetch failure (non-fatal; the drafter simply
    gets less context).
    """
    try:
        pr_proc = subprocess.run(
            ["gh", "api", f"repos/{owner}/{repo}/pulls/{pr_number}"],
            capture_output=True, text=True, timeout=30,
        )
        if pr_proc.returncode != 0:
            return []
        pr_data = json.loads(pr_proc.stdout)
        parent_sha = pr_data.get("base", {}).get("sha")
        if not parent_sha:
            return []

        files_proc = subprocess.run(
            ["gh", "api", f"repos/{owner}/{repo}/pulls/{pr_number}/files"],
            capture_output=True, text=True, timeout=30,
        )
        if files_proc.returncode != 0:
            return []
        files_data = json.loads(files_proc.stdout)
    except (subprocess.SubprocessError, json.JSONDecodeError):
        return []

    selected = [
        f for f in files_data
        if any(f.get("filename", "").endswith(e) for e in _SOURCE_EXTS)
    ][:max_files]

    ref_label = f"PR #{pr_number}"
    out: list[UpstreamFile] = []
    for f in selected:
        path = f.get("filename", "")
        if not path:
            continue
        uf = _fetch_file_at_ref(owner, repo, path, parent_sha, ref_label)
        if uf is not None:
            out.append(uf)
    return out


def fetch_commit_files_at_parent(
    owner: str, repo: str, sha: str,
    max_files: int = _MAX_FILES_PER_REF,
) -> list[UpstreamFile]:
    """For a fix commit, fetch files modified AT THEIR PARENT (pre-fix) state.

    Steps:
      1. ``gh api repos/<o>/<r>/commits/<sha>`` → read ``parents[0].sha`` and
         the ``files`` list.
      2. For each source file (up to ``max_files``): fetch content at
         ``parents[0].sha``.
    """
    try:
        proc = subprocess.run(
            ["gh", "api", f"repos/{owner}/{repo}/commits/{sha}"],
            capture_output=True, text=True, timeout=30,
        )
        if proc.returncode != 0:
            return []
        data = json.loads(proc.stdout)
        parents = data.get("parents") or []
        if not parents:
            return []
        parent_sha = parents[0].get("sha")
        if not parent_sha:
            return []
        files_data = data.get("files") or []
    except (subprocess.SubprocessError, json.JSONDecodeError):
        return []

    selected = [
        f for f in files_data
        if any(f.get("filename", "").endswith(e) for e in _SOURCE_EXTS)
    ][:max_files]

    ref_label = f"commit {sha[:7]}"
    out: list[UpstreamFile] = []
    for f in selected:
        path = f.get("filename", "")
        if not path:
            continue
        uf = _fetch_file_at_ref(owner, repo, path, parent_sha, ref_label)
        if uf is not None:
            out.append(uf)
    return out


def enrich_context(
    thread_text: str,
    default_owner: str,
    default_repo: str,
    max_total_files: int = 8,
) -> list[UpstreamFile]:
    """Top-level entry point.  Extract refs from ``thread_text``, fetch files.

    Returns at most ``max_total_files`` across all refs combined.
    """
    refs = extract_refs(thread_text, default_owner, default_repo)
    out: list[UpstreamFile] = []
    for owner, repo, kind, ref_id in refs:
        if len(out) >= max_total_files:
            break
        budget = max_total_files - len(out)
        if kind == "pull":
            files = fetch_pr_files_at_parent(owner, repo, ref_id, max_files=budget)
        else:
            files = fetch_commit_files_at_parent(
                owner, repo, ref_id, max_files=budget,
            )
        out.extend(files)
    return out[:max_total_files]


def format_for_drafter(files: list[UpstreamFile]) -> str:
    """Format fetched files as a text block suitable for appending to the
    drafter's user message.

    Empty input returns the empty string (so callers can simply concatenate).
    """
    if not files:
        return ""
    parts = ["=== Upstream source (pre-fix state) ==="]
    for f in files:
        header = f"\n--- {f.path} (from {f.ref}) ---"
        if f.truncated:
            header += " [truncated]"
        parts.append(header)
        parts.append(f.content)
    return "\n".join(parts)
