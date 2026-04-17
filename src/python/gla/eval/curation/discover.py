from __future__ import annotations
import json
import subprocess
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class DiscoveryCandidate:
    url: str
    source_type: str                     # "issue" | "fix_commit" | "stackoverflow"
    title: str
    labels: list[str] = field(default_factory=list)
    created_at: Optional[str] = None
    metadata: dict = field(default_factory=dict)


class GitHubSearch:
    """Runs GitHub Search queries via the `gh api` CLI."""

    def search_issues(self, query: str, per_page: int = 30) -> list[DiscoveryCandidate]:
        proc = subprocess.run(
            ["gh", "api", "-X", "GET", "search/issues",
             "-f", f"q={query}", "-f", f"per_page={per_page}"],
            capture_output=True, text=True, check=True,
        )
        data = json.loads(proc.stdout)
        out: list[DiscoveryCandidate] = []
        for item in data.get("items", []):
            out.append(DiscoveryCandidate(
                url=item["html_url"],
                source_type="issue",
                title=item.get("title", ""),
                labels=[l["name"] for l in item.get("labels", [])],
                created_at=item.get("created_at"),
                metadata={"number": item.get("number")},
            ))
        return out

    def search_commits(self, query: str, per_page: int = 30) -> list[DiscoveryCandidate]:
        proc = subprocess.run(
            ["gh", "api", "-X", "GET", "search/commits",
             "-f", f"q={query}", "-f", f"per_page={per_page}",
             "-H", "Accept: application/vnd.github.cloak-preview+json"],
            capture_output=True, text=True, check=True,
        )
        data = json.loads(proc.stdout)
        out: list[DiscoveryCandidate] = []
        for item in data.get("items", []):
            out.append(DiscoveryCandidate(
                url=item["html_url"],
                source_type="fix_commit",
                title=item.get("commit", {}).get("message", "").split("\n")[0][:120],
                created_at=item.get("commit", {}).get("author", {}).get("date"),
                metadata={"sha": item.get("sha")},
            ))
        return out
