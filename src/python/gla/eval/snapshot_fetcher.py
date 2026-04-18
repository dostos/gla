"""Lazy, cached shallow-clones of upstream repositories at specific SHAs.

Used by the OpenGPA eval harness when a scenario references an upstream
repo snapshot (via `upstream_snapshot_repo` + `upstream_snapshot_sha`
fields in ScenarioMetadata).

The cache lives at `/data3/opengpa-snapshots/` by default (per the
project's convention that large data stays out of the repo). Each
snapshot is stored under `<cache>/<host>__<owner>__<repo>__<sha>/`
with a `.complete` sentinel file marking successful fetches.
"""
from __future__ import annotations

import hashlib
import os
import re
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

DEFAULT_CACHE_ROOT = Path("/data3/opengpa-snapshots")


class SnapshotError(Exception):
    """Raised when a snapshot cannot be fetched."""


@dataclass
class SnapshotRef:
    """Canonical identifier for an upstream snapshot."""
    repo_url: str      # e.g. "https://github.com/mrdoob/three.js"
    sha: str           # full or short hex SHA

    def cache_key(self) -> str:
        """Produce a filesystem-safe unique key.

        Format: <host>__<owner>__<repo>__<sha>
        - host: github.com becomes github_com (dots replaced)
        - owner/repo: lowercase, non-[a-z0-9_-] replaced with _
        - sha: lowercased, truncated to first 12 hex chars if longer
          (12 is enough for uniqueness within any practical repo)
        """
        m = re.match(r"https?://([^/]+)/([^/]+)/([^/]+?)(?:\.[a-z]+)?/?$", self.repo_url)
        if not m:
            # Fallback: hash the whole URL
            h = hashlib.sha1(self.repo_url.encode()).hexdigest()[:16]
            return f"url_{h}__{self._short_sha()}"
        host, owner, repo = m.group(1), m.group(2), m.group(3)
        host = re.sub(r"[^a-zA-Z0-9_-]", "_", host).lower()
        owner = re.sub(r"[^a-zA-Z0-9_-]", "_", owner).lower()
        repo = re.sub(r"[^a-zA-Z0-9_-]", "_", repo).lower()
        return f"{host}__{owner}__{repo}__{self._short_sha()}"

    def _short_sha(self) -> str:
        sha = self.sha.lower().strip()
        # Keep hex only; truncate to 12 chars
        hex_only = re.sub(r"[^a-f0-9]", "", sha)
        return hex_only[:12] or "unknown"


class SnapshotFetcher:
    """Lazy, cached, shallow clone of a git repo at a specific SHA.

    Usage:
        fetcher = SnapshotFetcher()
        path = fetcher.fetch(SnapshotRef("https://github.com/x/y", "abc123"))
        # path is a Path to the checked-out working tree; safe to read from

    The fetcher writes to `cache_root/<cache_key>/`. A `.complete` sentinel
    file inside that dir indicates the clone finished successfully. If the
    dir exists but is missing `.complete`, it's treated as stale (from a
    crashed prior fetch) and re-cloned fresh.
    """

    def __init__(self, cache_root: Optional[Path] = None,
                 git_bin: str = "git",
                 timeout: int = 600):
        self.cache_root = Path(cache_root) if cache_root else DEFAULT_CACHE_ROOT
        self._git = git_bin
        self._timeout = timeout

    def fetch(self, ref: SnapshotRef) -> Path:
        """Return a Path to a working tree checked out at the given SHA.

        If the cache already has a complete clone for this (repo, sha),
        return its path immediately. Otherwise clone into place.

        Raises SnapshotError if the clone fails.
        """
        target = self.cache_root / ref.cache_key()

        # Fast path: already complete
        if (target / ".complete").exists():
            return target

        # Stale path: partial clone from a previous crash. Remove and retry.
        if target.exists():
            try:
                shutil.rmtree(target)
            except OSError as e:
                raise SnapshotError(f"cannot remove stale cache dir {target}: {e}") from e

        # Ensure cache root exists
        target.parent.mkdir(parents=True, exist_ok=True)
        target.mkdir(parents=True)

        try:
            self._clone_at_sha(ref, target)
        except SnapshotError:
            # Leave no half-complete dir behind
            shutil.rmtree(target, ignore_errors=True)
            raise

        # Mark complete
        (target / ".complete").write_text("")
        return target

    def _clone_at_sha(self, ref: SnapshotRef, target: Path) -> None:
        """Fetch a single commit at ref.sha into target/ using the minimum
        bandwidth pattern:
          git init .
          git remote add origin <url>
          git fetch --depth 1 origin <sha>
          git reset --hard FETCH_HEAD

        This works for any SHA (including those not on any branch tip),
        unlike `git clone --branch <sha>`. Requires server to support
        uploadpack.allowReachableSHA1InWant = true; GitHub does.
        """
        def run(argv: list[str]) -> None:
            proc = subprocess.run(
                argv, cwd=str(target),
                capture_output=True, text=True,
                timeout=self._timeout,
            )
            if proc.returncode != 0:
                raise SnapshotError(
                    f"git command failed: {' '.join(argv)}\n"
                    f"stderr: {proc.stderr[:500]}"
                )

        run([self._git, "init", "-q"])
        run([self._git, "remote", "add", "origin", ref.repo_url])
        # Try to fetch the SHA directly (fast, minimal bandwidth).
        fetched = False
        try:
            run([self._git, "fetch", "--depth", "1", "origin", ref.sha])
            fetched = True
        except SnapshotError:
            pass

        if not fetched:
            # Fallback 1: fetch with enough depth to include merge commits.
            try:
                run([self._git, "fetch", "--depth", "500", "origin"])
                fetched = True
            except SnapshotError:
                pass

        if not fetched:
            # Fallback 2: full unshallow fetch. Slow but always works.
            run([self._git, "fetch", "--unshallow", "origin"])

        # Try reset to the target SHA. If it's a merge commit SHA,
        # it should be in the fetched history now.
        try:
            run([self._git, "reset", "--hard", ref.sha])
        except SnapshotError:
            # Last resort: fetch ALL refs and retry
            run([self._git, "fetch", "origin", "+refs/heads/*:refs/remotes/origin/*"])
            run([self._git, "reset", "--hard", ref.sha])

    def is_cached(self, ref: SnapshotRef) -> bool:
        """True iff the snapshot is already fully in the cache."""
        return (self.cache_root / ref.cache_key() / ".complete").exists()

    def cache_path(self, ref: SnapshotRef) -> Path:
        """Where this snapshot would live. May or may not exist."""
        return self.cache_root / ref.cache_key()

    def purge(self, ref: SnapshotRef) -> None:
        """Remove the snapshot from the cache (if present). No-op if absent."""
        p = self.cache_path(ref)
        if p.exists():
            shutil.rmtree(p)
