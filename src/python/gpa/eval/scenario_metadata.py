"""Per-scenario metadata sidecar (scenario.yaml).

Schema is documented in docs/superpowers/specs/2026-05-02-eval-scenario-taxonomy-layout-design.md.
"""
from __future__ import annotations

from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any, Iterator, Optional

import yaml


SCHEMA_VERSION = 1

VALID_SOURCE_TYPES = frozenset({
    "github_issue", "github_pull", "stackoverflow", "synthetic", "legacy",
})

# Loaded from mining_rules.yaml at runtime; see _load_taxonomy_lists().
_TAXONOMY_CACHE: Optional[tuple[frozenset[str], frozenset[str]]] = None

# Differs intentionally from scenario.py:_VALID_BUG_CLASSES: "legacy" is
# dropped here because it is a provenance status recorded in source.type,
# not a bug classification. "synthetic" is added for hand-authored scenarios
# where bug_class doesn't apply, and "unknown" for scenarios whose
# bug_class hasn't yet been resolved. See spec
# 2026-05-02-eval-scenario-taxonomy-layout-design.md § Non-Goals.
VALID_BUG_CLASSES = frozenset({
    "framework-internal", "consumer-misuse", "user-config",
    "synthetic", "unknown",
})

VALID_BACKEND_API = frozenset({
    "opengl", "vulkan", "webgl", "webgpu", "unknown",
})

VALID_BACKEND_STATUS = frozenset({
    "reproduced", "not-yet-reproduced", "non-runnable",
})

VALID_STATUS = frozenset({
    "triaged", "drafted", "running", "passing",
})


@dataclass
class Source:
    type: str
    url: Optional[str] = None
    repo: Optional[str] = None
    issue_id: Optional[Any] = None  # int (GH) | str (SO) | None


@dataclass
class Taxonomy:
    category: str
    framework: str
    bug_class: str = "unknown"


@dataclass
class Backend:
    api: str = "unknown"
    status: str = "not-yet-reproduced"


@dataclass
class Scenario:
    path: Path
    slug: str
    round: str
    mined_at: str
    source: Source
    taxonomy: Taxonomy
    backend: Backend
    status: str
    tags: list[str] = field(default_factory=list)
    notes: str = ""
