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
