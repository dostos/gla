"""Per-scenario metadata sidecar (scenario.yaml).

Schema is documented in docs/superpowers/specs/2026-05-02-eval-scenario-taxonomy-layout-design.md.
"""
from __future__ import annotations

from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Iterator, Optional

import yaml


# Written into scenario.yaml as `schema_version: 1`. Bumped only when load_scenario_yaml needs migration logic.
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
    issue_id: int | str | None = None  # int (GH) | str (SO)


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


_MINING_RULES_PATH = Path(__file__).parent / "curation" / "mining_rules.yaml"


def _load_taxonomy_lists() -> tuple[frozenset[str], frozenset[str]]:
    """Read mining_rules.yaml; return (categories, frameworks) closed lists.

    The "synthetic" sentinel is pre-seeded into both sets so that hand-authored
    scenarios pass validation without appearing in mining_rules.yaml.
    """
    global _TAXONOMY_CACHE
    if _TAXONOMY_CACHE is not None:
        return _TAXONOMY_CACHE
    with open(_MINING_RULES_PATH) as f:
        data = yaml.safe_load(f)
    cats: set[str] = {"synthetic"}  # synthetic is a sentinel category
    fws: set[str] = {"synthetic"}   # synthetic is a sentinel framework
    for repo_map in (data.get("taxonomy", {}).get("framework_repos", {}),
                     data.get("taxonomy", {}).get("tag_frameworks", {})):
        for cat_fw in repo_map.values():
            if isinstance(cat_fw, list) and len(cat_fw) == 2:
                cats.add(cat_fw[0])
                fws.add(cat_fw[1])
    _TAXONOMY_CACHE = (frozenset(cats), frozenset(fws))
    return _TAXONOMY_CACHE


def validate_scenario(s: Scenario) -> list[str]:
    """Return a list of validation errors; empty list = valid."""
    errors: list[str] = []
    if s.source.type not in VALID_SOURCE_TYPES:
        errors.append(f"source.type={s.source.type!r} not in {sorted(VALID_SOURCE_TYPES)}")
    cats, fws = _load_taxonomy_lists()
    if s.taxonomy.category not in cats:
        errors.append(f"taxonomy.category={s.taxonomy.category!r} not in {sorted(cats)}")
    if s.taxonomy.framework not in fws:
        errors.append(f"taxonomy.framework={s.taxonomy.framework!r} not in {sorted(fws)}")
    if s.taxonomy.bug_class not in VALID_BUG_CLASSES:
        errors.append(f"taxonomy.bug_class={s.taxonomy.bug_class!r} not in {sorted(VALID_BUG_CLASSES)}")
    if s.backend.api not in VALID_BACKEND_API:
        errors.append(f"backend.api={s.backend.api!r} not in {sorted(VALID_BACKEND_API)}")
    if s.backend.status not in VALID_BACKEND_STATUS:
        errors.append(f"backend.status={s.backend.status!r} not in {sorted(VALID_BACKEND_STATUS)}")
    if s.status not in VALID_STATUS:
        errors.append(f"status={s.status!r} not in {sorted(VALID_STATUS)}")
    if not s.slug:
        errors.append("slug is required")
    if not s.round:
        errors.append("round is required")
    return errors


def dump_scenario_yaml(s: Scenario, path: Path) -> None:
    """Write scenario as YAML to the given path."""
    payload = {
        "schema_version": SCHEMA_VERSION,
        "slug": s.slug,
        "round": s.round,
        "mined_at": s.mined_at,
        "source": {k: v for k, v in asdict(s.source).items() if v is not None},
        "taxonomy": asdict(s.taxonomy),
        "backend": asdict(s.backend),
        "status": s.status,
        "tags": list(s.tags),
        "notes": s.notes,
    }
    with open(path, "w") as f:
        yaml.safe_dump(payload, f, sort_keys=False, default_flow_style=False)


def load_scenario_yaml(path: Path) -> Scenario:
    """Read a scenario.yaml and return a Scenario. Path is the yaml file path."""
    with open(path) as f:
        d = yaml.safe_load(f)
    if d.get("schema_version") != SCHEMA_VERSION:
        raise ValueError(f"unsupported schema_version {d.get('schema_version')!r}")
    return Scenario(
        path=path.parent,
        slug=d["slug"],
        round=d["round"],
        mined_at=d.get("mined_at", ""),
        source=Source(**d["source"]),
        taxonomy=Taxonomy(**d["taxonomy"]),
        backend=Backend(**d.get("backend", {})),
        status=d["status"],
        tags=list(d.get("tags") or []),
        notes=d.get("notes", "") or "",
    )


def iter_scenarios(root: Path) -> Iterator[Scenario]:
    """Yield Scenario for every leaf containing scenario.yaml under root."""
    for yaml_path in sorted(root.rglob("scenario.yaml")):
        yield load_scenario_yaml(yaml_path)


def validate_all(root: Path) -> list[str]:
    """Walk root, return a flat list of validation error strings."""
    errors: list[str] = []
    for yaml_path in sorted(root.rglob("scenario.yaml")):
        leaf = yaml_path.parent
        try:
            s = load_scenario_yaml(yaml_path)
        except Exception as e:
            errors.append(f"{leaf}: failed to load: {e}")
            continue
        if s.slug != leaf.name:
            errors.append(f"{leaf}: slug={s.slug!r} but folder name={leaf.name!r}")
        if not (leaf / "scenario.md").exists():
            errors.append(f"{leaf}: missing scenario.md")
        for e in validate_scenario(s):
            errors.append(f"{leaf}: {e}")
    return errors
