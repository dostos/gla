from __future__ import annotations
import json
import re
import subprocess
from dataclasses import dataclass, field
from typing import Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from gla.eval.curation.coverage_log import CoverageLog


DEFAULT_QUERIES: dict[str, list[str]] = {
    "issue": [
        # === Framework bugs (original) ===
        'repo:mrdoob/three.js is:issue is:closed reason:completed "z-fighting" OR "winding" OR "culling"',
        'repo:mrdoob/three.js is:issue is:closed reason:completed "shader" "uniform"',
        'repo:mrdoob/three.js is:issue is:closed reason:completed "NaN" OR "Inf" texture',
        'repo:godotengine/godot is:issue is:closed reason:completed label:"topic:rendering" shader',
        'repo:godotengine/godot is:issue is:closed reason:completed label:"topic:rendering" "z-fighting" OR "depth"',
        'repo:BabylonJS/Babylon.js is:issue is:closed reason:completed label:"bug" shader precision',

        # === User project bugs (projects USING the frameworks) ===
        # Three.js user projects — rendering issues from misusing the API
        '"three.js" "rendering" "wrong color" OR "invisible" OR "black screen" is:issue is:closed -repo:mrdoob/three.js',
        '"three.js" "texture" "not showing" OR "flickering" OR "missing" is:issue is:closed -repo:mrdoob/three.js',
        '"three.js" "depth" OR "z-fighting" OR "transparent" "bug" is:issue is:closed -repo:mrdoob/three.js',
        # Godot user projects
        '"godot" "rendering" "wrong" OR "broken" OR "glitch" is:issue is:closed -repo:godotengine/godot',
        '"godot" "shader" "not working" OR "visual bug" is:issue is:closed -repo:godotengine/godot',
        # Open3D user projects
        'repo:isl-org/Open3D is:issue is:closed "rendering" "wrong" OR "broken" OR "black"',
        '"open3d" "visualization" "not rendering" OR "wrong color" OR "missing" is:issue is:closed',
        # Babylon.js user projects
        '"babylon.js" "rendering" "wrong" OR "glitch" OR "artifact" is:issue is:closed -repo:BabylonJS/Babylon.js',
        # p5.js / Processing user projects
        '"p5.js" "webgl" "rendering" "bug" OR "wrong" OR "broken" is:issue is:closed -repo:processing/p5.js',
        # General WebGL/OpenGL user issues
        '"webgl" "state" "leak" OR "not reset" OR "wrong texture" is:issue is:closed',
        '"opengl" "rendering" "bug" "uniform" OR "texture" OR "blend" is:issue is:closed',
    ],
    "commit": [
        'repo:mrdoob/three.js "fix:" "z-fighting" OR "culling" OR "precision"',
        'repo:godotengine/godot "fix:" "shader" OR "depth buffer"',
    ],
    # SO queries are lists of tags combined AND-wise (SO search restricts
    # to questions tagged with ALL provided tags).
    "stackoverflow": [
        # Framework consumers — rendering bugs from misusing APIs
        ["three.js", "rendering"],
        ["three.js", "texture"],
        ["three.js", "transparency"],
        ["three.js", "shader-material"],
        ["webgl", "glsl"],
        ["webgl", "framebuffer"],
        ["webgl", "depth-buffer"],
        ["webgl", "blending"],
        ["godot", "shader"],
        ["godot", "rendering"],
        ["godot4", "visual-shader"],
        ["babylon.js", "rendering"],
        ["babylon.js", "shader"],
        ["open3d", "visualization"],
        ["opengl", "debug"],
        ["opengl", "texture"],
        ["opengl", "framebuffer-object"],
        ["opengl", "depth-testing"],
        ["opengl", "face-culling"],
        ["vulkan", "rendering"],
        ["vulkan", "descriptor-set"],
        ["p5.js", "webgl"],
        ["unity3d", "shader"],
        ["unity3d", "rendering"],
        ["unreal-engine4", "rendering"],
    ],
}


# Title/label patterns that strongly suggest the issue is NOT a visual rendering bug.
# Matched case-insensitively against candidate.title and (lowercased) label names.
_NON_RENDERING_KEYWORDS = [
    # Type system / API surface
    r"\btypescript\b", r"\btype\s+def", r"\btype\s+error",
    r"\bd\.ts\b", r"\btyping\b",
    # Docs / examples / tutorials
    r"\bdocs?\b", r"\bdocumentation\b", r"\bexample\b", r"\btutorial\b",
    r"\breadme\b", r"\bfaq\b",
    # Build / packaging / ci
    r"\bbuild\s+error\b", r"\bnpm\b", r"\byarn\b", r"\bpnpm\b",
    r"\bbundle\b", r"\bbundler\b", r"\brollup\b", r"\bvite\b",
    r"\bpackage\.json\b", r"\bci\b", r"\bgithub\s+actions\b",
    # Editor / dev tools
    r"\beditor\b", r"\binspector\b", r"\beslint\b", r"\btslint\b",
    r"\bvscode\b", r"\bnode\s+material\s+editor\b", r"\bNME\b",
    # API surface (non-visual)
    r"\bapi\s+change\b", r"\bdeprecation\b", r"\brefactor\b",
    # Input / UI / DOM
    r"\bdom\b", r"\bkeyboard\b", r"\bpointer\s+event\b",
    r"\bfocus\b", r"\btouch\s+event\b", r"\binput\s+focus\b",
    # Support / question
    r"\bquestion\b", r"\bhow\s+to\b", r"\bplease\s+help\b",
]

_NON_RENDERING_LABELS = {
    "documentation", "docs", "typescript", "types", "editor",
    "tooling", "build", "ci", "duplicate", "question",
    "needs-info", "needs info", "workflow", "examples",
}

_NON_RENDERING_RE = re.compile("|".join(_NON_RENDERING_KEYWORDS), re.IGNORECASE)


def _is_obviously_non_rendering_so(q) -> bool:
    """SO-specific pre-filter — mirrors _is_obviously_non_rendering but
    checks tags (not labels) and uses the title heuristic."""
    if _NON_RENDERING_RE.search(getattr(q, "title", "") or ""):
        return True
    tag_set = {t.lower().strip() for t in (getattr(q, "tags", None) or [])}
    return bool(tag_set & _NON_RENDERING_LABELS)


def _is_obviously_non_rendering(cand: "DiscoveryCandidate") -> bool:
    """Cheap pre-triage filter.

    Returns True when the title or any label strongly suggests the issue is NOT
    a visual rendering bug — so we can skip the LLM triage call entirely.

    Conservative: false negatives (letting through non-rendering bugs) are fine,
    triage will catch them; false positives (rejecting real rendering bugs) are
    what we want to avoid, so the patterns only match terms that are
    overwhelmingly non-visual in our source repos.
    """
    if _NON_RENDERING_RE.search(cand.title or ""):
        return True
    label_set = {l.lower().strip() for l in (cand.labels or [])}
    if label_set & _NON_RENDERING_LABELS:
        return True
    return False


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


class StackExchangeSearch:
    """Thin wrapper over ``stackoverflow.search_questions`` for injection
    symmetry with :class:`GitHubSearch`."""

    def search_questions(self, tags: list[str], per_page: int = 30):
        from gla.eval.curation.stackoverflow import search_questions
        return search_questions(tags, per_page=per_page)


class Discoverer:
    def __init__(self, search, coverage_log: "CoverageLog",
                 queries: dict, batch_quota: int = 20,
                 so_search=None):
        self._search = search
        self._so_search = so_search
        self._log = coverage_log
        self._queries = queries
        self._quota = batch_quota

    def run(self) -> list[DiscoveryCandidate]:
        seen: set[str] = set()
        out: list[DiscoveryCandidate] = []

        for q in self._queries.get("issue", []):
            if len(out) >= self._quota:
                break
            for cand in self._search.search_issues(q):
                if len(out) >= self._quota:
                    break
                if cand.url in seen:
                    continue
                if self._log.contains_url(cand.url):
                    continue
                if _is_obviously_non_rendering(cand):
                    # Record as rejected at discovery so we still get the denominator
                    # and don't re-check on next batch.
                    self._log_discovery_rejection(cand, reason="out_of_scope_not_rendering_bug")
                    seen.add(cand.url)
                    continue
                seen.add(cand.url)
                out.append(cand)

        for q in self._queries.get("commit", []):
            if len(out) >= self._quota:
                break
            for cand in self._search.search_commits(q):
                if len(out) >= self._quota:
                    break
                if cand.url in seen:
                    continue
                if self._log.contains_url(cand.url):
                    continue
                if _is_obviously_non_rendering(cand):
                    self._log_discovery_rejection(cand, reason="out_of_scope_not_rendering_bug")
                    seen.add(cand.url)
                    continue
                seen.add(cand.url)
                out.append(cand)

        # Stack Overflow queries (only if SO search was injected).
        if self._so_search is not None:
            for tags in self._queries.get("stackoverflow", []):
                if len(out) >= self._quota:
                    break
                for q in self._so_search.search_questions(tags):
                    if len(out) >= self._quota:
                        break
                    if q.url in seen:
                        continue
                    if self._log.contains_url(q.url):
                        continue
                    if _is_obviously_non_rendering_so(q):
                        rej = DiscoveryCandidate(
                            url=q.url, source_type="stackoverflow",
                            title=q.title, labels=list(q.tags or []),
                        )
                        self._log_discovery_rejection(
                            rej, reason="out_of_scope_not_rendering_bug"
                        )
                        seen.add(q.url)
                        continue
                    seen.add(q.url)
                    out.append(DiscoveryCandidate(
                        url=q.url,
                        source_type="stackoverflow",
                        title=q.title,
                        labels=list(q.tags or []),
                        created_at=q.creation_date,
                        metadata={"accepted_answer_id": q.accepted_answer_id},
                    ))

        return out

    def _log_discovery_rejection(self, cand: "DiscoveryCandidate",
                                  reason: str) -> None:
        """Log a pre-triage rejection to the coverage log.

        Mirrors the shape that `log_rejection` in commit.py produces, but written
        directly here to avoid a circular import from commit.py -> discover.py.
        """
        from gla.eval.curation.coverage_log import CoverageEntry
        from datetime import datetime, timezone
        self._log.append(CoverageEntry(
            issue_url=cand.url,
            reviewed_at=datetime.now(timezone.utc).isoformat(),
            source_type=cand.source_type,
            triage_verdict="out_of_scope",
            root_cause_fingerprint=None,
            outcome="rejected",
            scenario_id=None,
            tier=None,
            rejection_reason=reason,
            predicted_helps=None,
            observed_helps=None,
            failure_mode=None,
            eval_summary=None,
        ))
