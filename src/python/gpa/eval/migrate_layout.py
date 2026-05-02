"""Migrate tests/eval/ from flat layout to taxonomy tree.

See docs/superpowers/specs/2026-05-02-eval-scenario-taxonomy-layout-design.md.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from gpa.eval.scenario_metadata import Source


# Known mining categories from mining_rules.yaml — used to detect taxonomy
# segments in recent-mined folder names.
_KNOWN_CATEGORIES = (
    "web-3d", "web-2d", "web-map", "native-engine", "scientific", "graphics-lib",
)
_KNOWN_BUG_CLASSES = (
    "framework-maintenance", "framework-app-dev", "graphics-lib-dev",
)
_RE_SYNTHETIC = re.compile(r"^(e\d+)_(.+)$")
_RE_EARLY_MINED = re.compile(r"^(r\d+)_(.+)$")
_RE_RECENT_MINED = re.compile(r"^(r[0-9a-f]{6,8})_(.+)$")


@dataclass(frozen=True)
class ParsedName:
    round: str                          # e.g. "e1", "r14", "r96fdc7"
    category_hint: Optional[str]        # one of _KNOWN_CATEGORIES if found
    framework_hint: Optional[str]       # whatever followed the category in the name
    bug_class_hint: Optional[str]       # one of _KNOWN_BUG_CLASSES if found
    suffix: str                         # remaining descriptive part
    kind: str                           # synthetic | early-mined | recent-mined | unknown


def parse_existing_folder_name(name: str) -> ParsedName:
    if (m := _RE_SYNTHETIC.match(name)):
        return ParsedName(round=m.group(1), category_hint=None, framework_hint=None,
                          bug_class_hint=None, suffix=m.group(2), kind="synthetic")
    if (m := _RE_RECENT_MINED.match(name)):
        round_id = m.group(1)
        rest = m.group(2)
        bug = None
        for bc in _KNOWN_BUG_CLASSES:
            if rest.startswith(bc + "_"):
                bug = bc
                rest = rest[len(bc) + 1:]
                break
        cat = None
        for c in _KNOWN_CATEGORIES:
            if rest.startswith(c + "_"):
                cat = c
                rest = rest[len(c) + 1:]
                break
        framework = None
        if cat and "_" in rest:
            framework, rest = rest.split("_", 1)
        return ParsedName(round=round_id, category_hint=cat, framework_hint=framework,
                          bug_class_hint=bug, suffix=rest, kind="recent-mined")
    if (m := _RE_EARLY_MINED.match(name)):
        return ParsedName(round=m.group(1), category_hint=None, framework_hint=None,
                          bug_class_hint=None, suffix=m.group(2), kind="early-mined")
    return ParsedName(round="", category_hint=None, framework_hint=None,
                      bug_class_hint=None, suffix=name, kind="unknown")


_RE_GH = re.compile(r"github\.com/([^/]+)/([^/]+)/(issues|pull)/(\d+)")
_RE_SO = re.compile(r"stackoverflow\.com/questions/(\d+)")


def extract_source(scenario_md_path: Path) -> Source:
    text = scenario_md_path.read_text(errors="replace")
    if (m := _RE_GH.search(text)):
        org, repo, kind, num = m.group(1), m.group(2), m.group(3), int(m.group(4))
        return Source(
            type="github_issue" if kind == "issues" else "github_pull",
            url=f"https://github.com/{org}/{repo}/{kind}/{num}",
            repo=f"{org}/{repo}",
            issue_id=num,
        )
    if (m := _RE_SO.search(text)):
        qid = m.group(1)
        return Source(
            type="stackoverflow",
            url=f"https://stackoverflow.com/questions/{qid}",
            repo=None,
            issue_id=qid,
        )
    return Source(type="legacy")


@dataclass
class ResolveContext:
    rules: dict           # repo (str) → (category, framework)
    overrides: dict       # original_folder_name → {category, framework, bug_class}


# Mining-side bug_class -> stored bug_class
_BUG_CLASS_MAP = {
    "framework-maintenance": "framework-internal",
    "framework-app-dev": "consumer-misuse",
    "graphics-lib-dev": "framework-internal",
}


def resolve_taxonomy(
    parsed: ParsedName,
    source: Source,
    ctx: ResolveContext,
    original_name: str = "",
) -> tuple[Optional[str], Optional[str], str]:
    """Return (category, framework, bug_class). Either of cat/fw may be None
    when unresolved; bug_class falls back to 'unknown'."""
    # 1. Override wins.
    if (override := ctx.overrides.get(original_name)) is not None:
        return (
            override.get("category"),
            override.get("framework"),
            override.get("bug_class", "unknown"),
        )
    # 2. Synthetic short-circuit.
    if parsed.kind == "synthetic" or source.type == "synthetic":
        return ("synthetic", "synthetic", "synthetic")
    # 3. Parsed-name hints (recent-mined).
    if parsed.category_hint and parsed.framework_hint:
        bc = _BUG_CLASS_MAP.get(parsed.bug_class_hint or "", "unknown")
        return (parsed.category_hint, parsed.framework_hint, bc)
    # 4. Repo lookup in mining_rules.
    if source.repo and source.repo in ctx.rules:
        cat, fw = ctx.rules[source.repo]
        return (cat, fw, "framework-internal" if "issue" in source.type else "unknown")
    # 5. Unresolved.
    return (None, None, "unknown")


def load_resolve_context(
    rules_yaml: Path, overrides_yaml: Optional[Path] = None,
) -> ResolveContext:
    import yaml as _yaml
    with open(rules_yaml) as f:
        d = _yaml.safe_load(f)
    rules: dict = {}
    repos = d.get("taxonomy", {}).get("framework_repos", {})
    for repo, cf in repos.items():
        if isinstance(cf, list) and len(cf) == 2:
            rules[repo] = (cf[0], cf[1])
    overrides: dict = {}
    if overrides_yaml and overrides_yaml.exists():
        with open(overrides_yaml) as f:
            overrides = _yaml.safe_load(f) or {}
    return ResolveContext(rules=rules, overrides=overrides)


_REPO_NORMALIZE_RE = re.compile(r"[^a-z0-9]+")


def _normalize_repo(repo_basename: str) -> str:
    """Lowercase + collapse non-alphanum to single underscore for Bazel target safety."""
    s = _REPO_NORMALIZE_RE.sub("_", repo_basename.lower()).strip("_")
    # Special-case: collapse three.js -> threejs, mapbox-gl-js -> mapbox_gl_js (already done).
    if s == "three_js":
        s = "threejs"
    return s


def build_slug(parsed: ParsedName, source: Source) -> str:
    if parsed.kind == "synthetic" or source.type == "synthetic":
        return f"{parsed.round}_{parsed.suffix}"
    if source.type == "legacy" or source.repo is None and source.type != "stackoverflow":
        return f"legacy_{parsed.round}_{parsed.suffix}"
    if source.type == "stackoverflow":
        return f"so_{source.issue_id}_{parsed.suffix}"
    repo_basename = source.repo.split("/", 1)[1] if "/" in source.repo else source.repo
    repo_norm = _normalize_repo(repo_basename)
    if source.type == "github_pull":
        return f"{repo_norm}_pull_{source.issue_id}_{parsed.suffix}"
    return f"{repo_norm}_{source.issue_id}_{parsed.suffix}"


_SYNTHETIC_BUCKETS = [
    ("state-leak", ("state_leak", "state-leak")),
    ("uniform", ("uniform_",)),
    ("depth", ("depth_", "reversed_z", "gldepthrange")),
    ("culling", ("culling_",)),
    ("stencil", ("stencil_",)),
    ("nan", ("nan_propagation",)),
]


def synthetic_topic(suffix: str) -> str:
    for topic, prefixes in _SYNTHETIC_BUCKETS:
        for p in prefixes:
            if suffix.startswith(p) or p in suffix.split("_"):
                return topic
    return "misc"
