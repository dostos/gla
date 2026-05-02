# Eval Scenario Taxonomy Layout — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Migrate `tests/eval/` from a flat 198-scenario directory into a 2-level taxonomy tree (`<category>/<framework>/<slug>/`) with parallel `synthetic/<topic>/<slug>/`, and move per-scenario provenance into a machine-readable `scenario.yaml`.

**Architecture:** New `scenario_metadata` module owns the schema + loader + validator. A migration tool (`migrate_layout.py`) walks the current tree, infers taxonomy/source/round, generates `scenario.yaml` plus per-leaf `BUILD.bazel`, and uses `git mv` for atomic moves. Forward-going mining pipeline (`gpa.eval.curation.draft`) is updated to emit directly into the new layout.

**Tech Stack:** Python 3.11 (Bazel-managed) / 3.10 (system pytest), PyYAML (already in `pyproject.toml`), Bazel, pytest. No new third-party deps; schema validation uses hand-rolled checks (closed lists are tiny).

**Spec:** `docs/superpowers/specs/2026-05-02-eval-scenario-taxonomy-layout-design.md`

---

## File Structure

### New files
- `src/python/gpa/eval/scenario_metadata.py` — `Scenario` dataclass, schema constants, `load_scenario`, `iter_scenarios`, `validate_all`. Pure data layer; no I/O beyond reading.
- `src/python/gpa/eval/migrate_layout.py` — migration CLI; orchestrates folder walk, taxonomy inference, slug build, conflict resolution, codegen, `git mv`.
- `src/python/gpa/eval/migration_overrides.yaml` — committed; small hand-edited mapping for scenarios where automatic taxonomy inference fails.
- `src/python/gpa/eval/index_cli.py` — read-only reporter (`gpa-eval index --by taxonomy`).
- `tests/unit/python/test_scenario_metadata.py` — schema/loader/validator tests.
- `tests/unit/python/test_migrate_layout.py` — migration tool tests using a synthetic mini-tree fixture.
- `tests/unit/python/test_index_cli.py` — index report tests.

### Modified files
- `tests/eval/BUILD.bazel` — replaced; new top-level glob `**/scenario.md` becomes purely informational (per-leaf `BUILD.bazel` files own the targets).
- `tests/eval/README.md` — rewritten to describe the new layout.
- `tests/eval/<every-scenario>/` — moved to new path; new `scenario.yaml` and per-leaf `BUILD.bazel` (where a `*.c` file exists).
- `src/python/gpa/eval/curation/draft.py` — emit new mined scenarios into `<category>/<framework>/<slug>/` with `scenario.yaml`.
- `src/python/gpa/eval/curation/run.py` — pass new path to draft; no other change.
- `src/python/gpa/eval/curation/journey.py` — wherever `tests/eval/<slug>/` is constructed, switch to taxonomy-aware path.
- `pyproject.toml` — add `gpa-eval = "gpa.eval.index_cli:main"` script entry.
- `scripts/run-eval-claude-code.sh` — update example path.
- `docs/gpa-trace-native-usage.md` — update binary path examples.
- `docs/eval-results.md` — update referenced scenario paths.
- `docs/superpowers/specs/2026-04-17-eval-set-real-world-design.md` — superseded pointer at top.
- `docs/superpowers/specs/2026-04-28-omnispace-gen-integration-design.md` — update `r37_joint_offset_smplx` reference.
- `CLAUDE.md` — update eval examples.

### Untouched
- `src/python/gpa/eval/scenario.py` — already exists; parses `scenario.md` frontmatter (the `## Fix` block). New `scenario_metadata.py` is a separate concern (sidecar yaml, not markdown frontmatter). Both modules coexist.

---

## Pre-Implementation Checks

- [ ] **Verify Python deps available**

```bash
PYTHONPATH=src/python python3 -c "import yaml; print(yaml.__version__)"
```
Expected: `6.x` or higher.

- [ ] **Verify Bazel build of current tree still works**

```bash
bazel build //tests/eval/... 2>&1 | tail -5
```
Expected: BUILD SUCCESSFUL or warnings only. If it fails on the current tree, fix or note before starting migration.

- [ ] **Snapshot current scenario count for post-migration check**

```bash
find tests/eval -name scenario.md | wc -l > /tmp/pre_migration_count.txt
cat /tmp/pre_migration_count.txt
```
Expected: `198` (or whatever the current count is). Save this number; the migration must preserve it.

---

## Task 1: Scenario metadata schema + dataclass

**Files:**
- Create: `src/python/gpa/eval/scenario_metadata.py`
- Test: `tests/unit/python/test_scenario_metadata.py`

The schema lives in code (not a separate JSON file) — tiny enough to embed, and avoids I/O on every load.

- [ ] **Step 1.1: Write the failing test for the dataclass**

```python
# tests/unit/python/test_scenario_metadata.py
from pathlib import Path
import pytest
from gpa.eval.scenario_metadata import Scenario, Source, Taxonomy, Backend


def test_scenario_dataclass_minimum():
    s = Scenario(
        path=Path("/tmp/x"),
        slug="godot_86493_world_environment_glow",
        round="r96fdc7",
        mined_at="2026-04-21",
        source=Source(type="github_issue", url="https://github.com/godotengine/godot/issues/86493",
                      repo="godotengine/godot", issue_id=86493),
        taxonomy=Taxonomy(category="native-engine", framework="godot",
                          bug_class="framework-internal"),
        backend=Backend(api="vulkan", status="not-yet-reproduced"),
        status="drafted",
        tags=[],
        notes="",
    )
    assert s.slug == "godot_86493_world_environment_glow"
```

- [ ] **Step 1.2: Run the test, confirm it fails**

```bash
PYTHONPATH=src/python python3 -m pytest tests/unit/python/test_scenario_metadata.py::test_scenario_dataclass_minimum -v
```
Expected: `ModuleNotFoundError: No module named 'gpa.eval.scenario_metadata'`.

- [ ] **Step 1.3: Implement the dataclasses + closed-list constants**

```python
# src/python/gpa/eval/scenario_metadata.py
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
```

- [ ] **Step 1.4: Run the test, confirm it passes**

```bash
PYTHONPATH=src/python python3 -m pytest tests/unit/python/test_scenario_metadata.py::test_scenario_dataclass_minimum -v
```
Expected: PASS.

- [ ] **Step 1.5: Commit**

```bash
git add src/python/gpa/eval/scenario_metadata.py tests/unit/python/test_scenario_metadata.py
git commit -m "feat(eval): add Scenario metadata dataclasses"
```

---

## Task 2: Schema validation + closed-list lookup

**Files:**
- Modify: `src/python/gpa/eval/scenario_metadata.py`
- Modify: `tests/unit/python/test_scenario_metadata.py`

The validator surfaces drift between `scenario.yaml` and `mining_rules.yaml` (e.g., a scenario claims `framework: nope` that isn't in the canon).

- [ ] **Step 2.1: Write the failing test for the validator**

```python
# tests/unit/python/test_scenario_metadata.py
def test_validate_unknown_category_rejected(tmp_path):
    from gpa.eval.scenario_metadata import validate_scenario, Scenario, Source, Taxonomy, Backend
    s = Scenario(
        path=tmp_path, slug="x", round="r1", mined_at="2026-01-01",
        source=Source(type="synthetic"),
        taxonomy=Taxonomy(category="not-a-real-category", framework="godot"),
        backend=Backend(),
        status="drafted",
    )
    errors = validate_scenario(s)
    assert any("category" in e for e in errors)


def test_validate_unknown_framework_rejected(tmp_path):
    from gpa.eval.scenario_metadata import validate_scenario, Scenario, Source, Taxonomy, Backend
    s = Scenario(
        path=tmp_path, slug="x", round="r1", mined_at="2026-01-01",
        source=Source(type="synthetic"),
        taxonomy=Taxonomy(category="native-engine", framework="not-a-framework"),
        backend=Backend(),
        status="drafted",
    )
    errors = validate_scenario(s)
    assert any("framework" in e for e in errors)


def test_validate_required_fields_complete(tmp_path):
    from gpa.eval.scenario_metadata import validate_scenario, Scenario, Source, Taxonomy, Backend
    s = Scenario(
        path=tmp_path, slug="godot_1_x", round="r1", mined_at="2026-01-01",
        source=Source(type="github_issue", url="https://github.com/x/y/issues/1",
                      repo="x/y", issue_id=1),
        taxonomy=Taxonomy(category="native-engine", framework="godot",
                          bug_class="framework-internal"),
        backend=Backend(api="vulkan", status="reproduced"),
        status="drafted",
    )
    errors = validate_scenario(s)
    assert errors == []
```

- [ ] **Step 2.2: Run, confirm fails**

```bash
PYTHONPATH=src/python python3 -m pytest tests/unit/python/test_scenario_metadata.py -k validate -v
```
Expected: 3 FAILS with `validate_scenario` not found.

- [ ] **Step 2.3: Implement `validate_scenario` and `_load_taxonomy_lists`**

```python
# Append to src/python/gpa/eval/scenario_metadata.py

_MINING_RULES_PATH = Path(__file__).parent / "curation" / "mining_rules.yaml"


def _load_taxonomy_lists() -> tuple[frozenset[str], frozenset[str]]:
    """Read mining_rules.yaml; return (categories, frameworks) closed lists."""
    global _TAXONOMY_CACHE
    if _TAXONOMY_CACHE is not None:
        return _TAXONOMY_CACHE
    with open(_MINING_RULES_PATH) as f:
        data = yaml.safe_load(f)
    cats: set[str] = set()
    fws: set[str] = {"synthetic"}  # synthetic is a sentinel framework
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
    if s.taxonomy.category not in cats and s.taxonomy.category != "synthetic":
        errors.append(f"taxonomy.category={s.taxonomy.category!r} not in {sorted(cats | {'synthetic'})}")
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
```

- [ ] **Step 2.4: Run, confirm passes**

```bash
PYTHONPATH=src/python python3 -m pytest tests/unit/python/test_scenario_metadata.py -k validate -v
```
Expected: all 3 PASS.

- [ ] **Step 2.5: Commit**

```bash
git add src/python/gpa/eval/scenario_metadata.py tests/unit/python/test_scenario_metadata.py
git commit -m "feat(eval): add scenario.yaml validator with closed-list checks"
```

---

## Task 3: scenario.yaml load/dump round-trip

**Files:**
- Modify: `src/python/gpa/eval/scenario_metadata.py`
- Modify: `tests/unit/python/test_scenario_metadata.py`

- [ ] **Step 3.1: Write failing test for round-trip**

```python
def test_scenario_yaml_round_trip(tmp_path):
    from gpa.eval.scenario_metadata import (
        Scenario, Source, Taxonomy, Backend,
        dump_scenario_yaml, load_scenario_yaml,
    )
    original = Scenario(
        path=tmp_path, slug="godot_1_x", round="r1", mined_at="2026-01-01",
        source=Source(type="github_issue", url="https://github.com/x/y/issues/1",
                      repo="x/y", issue_id=1),
        taxonomy=Taxonomy(category="native-engine", framework="godot",
                          bug_class="framework-internal"),
        backend=Backend(api="vulkan", status="reproduced"),
        status="drafted",
        tags=["postprocess"],
        notes="hello",
    )
    yaml_path = tmp_path / "scenario.yaml"
    dump_scenario_yaml(original, yaml_path)
    loaded = load_scenario_yaml(yaml_path)
    assert loaded.slug == original.slug
    assert loaded.source.url == original.source.url
    assert loaded.taxonomy.category == original.taxonomy.category
    assert loaded.tags == ["postprocess"]


def test_scenario_yaml_load_missing_file_raises(tmp_path):
    from gpa.eval.scenario_metadata import load_scenario_yaml
    import pytest
    with pytest.raises(FileNotFoundError):
        load_scenario_yaml(tmp_path / "nope.yaml")
```

- [ ] **Step 3.2: Run, confirm fails**

```bash
PYTHONPATH=src/python python3 -m pytest tests/unit/python/test_scenario_metadata.py -k yaml -v
```
Expected: 2 FAILS.

- [ ] **Step 3.3: Implement `dump_scenario_yaml` and `load_scenario_yaml`**

```python
# Append to src/python/gpa/eval/scenario_metadata.py

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
```

- [ ] **Step 3.4: Run, confirm passes**

```bash
PYTHONPATH=src/python python3 -m pytest tests/unit/python/test_scenario_metadata.py -v
```
Expected: all PASS.

- [ ] **Step 3.5: Commit**

```bash
git add src/python/gpa/eval/scenario_metadata.py tests/unit/python/test_scenario_metadata.py
git commit -m "feat(eval): add scenario.yaml load/dump"
```

---

## Task 4: Tree walker — `iter_scenarios` and `validate_all`

**Files:**
- Modify: `src/python/gpa/eval/scenario_metadata.py`
- Modify: `tests/unit/python/test_scenario_metadata.py`

- [ ] **Step 4.1: Write failing tests**

```python
def _make_scenario_at(dir_path, slug, category, framework):
    """Helper: write minimum scenario.md + scenario.yaml in dir_path."""
    from gpa.eval.scenario_metadata import (
        Scenario, Source, Taxonomy, Backend, dump_scenario_yaml,
    )
    dir_path.mkdir(parents=True)
    (dir_path / "scenario.md").write_text("# fixture\n")
    s = Scenario(
        path=dir_path, slug=slug, round="r1", mined_at="2026-01-01",
        source=Source(type="synthetic"),
        taxonomy=Taxonomy(category=category, framework=framework, bug_class="synthetic"),
        backend=Backend(),
        status="drafted",
    )
    dump_scenario_yaml(s, dir_path / "scenario.yaml")


def test_iter_scenarios_finds_all(tmp_path):
    from gpa.eval.scenario_metadata import iter_scenarios
    _make_scenario_at(tmp_path / "synthetic" / "uniform" / "e1_x", "e1_x", "synthetic", "synthetic")
    _make_scenario_at(tmp_path / "synthetic" / "depth" / "e2_y", "e2_y", "synthetic", "synthetic")
    found = list(iter_scenarios(tmp_path))
    assert len(found) == 2
    assert {s.slug for s in found} == {"e1_x", "e2_y"}


def test_validate_all_reports_slug_mismatch(tmp_path):
    from gpa.eval.scenario_metadata import validate_all
    _make_scenario_at(tmp_path / "synthetic" / "x" / "actually_named_this",
                      "but_yaml_says_this", "synthetic", "synthetic")
    errors = validate_all(tmp_path)
    assert any("slug" in e.lower() for e in errors)
```

- [ ] **Step 4.2: Run, confirm fails**

```bash
PYTHONPATH=src/python python3 -m pytest tests/unit/python/test_scenario_metadata.py -k 'iter_ or validate_all' -v
```
Expected: 2 FAILS.

- [ ] **Step 4.3: Implement `iter_scenarios` and `validate_all`**

```python
# Append to src/python/gpa/eval/scenario_metadata.py

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
```

- [ ] **Step 4.4: Run, confirm passes**

```bash
PYTHONPATH=src/python python3 -m pytest tests/unit/python/test_scenario_metadata.py -v
```
Expected: all PASS.

- [ ] **Step 4.5: Commit**

```bash
git add src/python/gpa/eval/scenario_metadata.py tests/unit/python/test_scenario_metadata.py
git commit -m "feat(eval): add iter_scenarios and validate_all walkers"
```

---

## Task 5: Migration tool — name parser

**Files:**
- Create: `src/python/gpa/eval/migrate_layout.py`
- Create: `tests/unit/python/test_migrate_layout.py`

The hardest inference is "given a current folder name, recover (round, category-hint, framework-hint, descriptive-suffix)". Three known formats:
- `e{N}_<slug>` — synthetic
- `r{N}_<slug>` — early mined (no taxonomy in name)
- `r{sha}_{category}_{framework}_<slug>` — recent mined (taxonomy in name)

Plus a fourth: `r{sha}_framework-maintenance_<category>_{framework}_<slug>` — the bug_class is also in the name.

- [ ] **Step 5.1: Write failing test for the parser**

```python
# tests/unit/python/test_migrate_layout.py
import pytest
from gpa.eval.migrate_layout import ParsedName, parse_existing_folder_name


def test_parse_synthetic():
    p = parse_existing_folder_name("e1_state_leak")
    assert p == ParsedName(round="e1", category_hint=None, framework_hint=None,
                           bug_class_hint=None, suffix="state_leak", kind="synthetic")


def test_parse_synthetic_long():
    p = parse_existing_folder_name("e25_gldepthrange_set_to_1_0_but_depth_test_is_gl_less_nothing_vi")
    assert p.kind == "synthetic"
    assert p.round == "e25"
    assert p.suffix == "gldepthrange_set_to_1_0_but_depth_test_is_gl_less_nothing_vi"


def test_parse_early_mined():
    p = parse_existing_folder_name("r14_bevy_child_text_invisible")
    assert p == ParsedName(round="r14", category_hint=None, framework_hint=None,
                           bug_class_hint=None, suffix="bevy_child_text_invisible",
                           kind="early-mined")


def test_parse_recent_mined_with_bug_class_and_taxonomy():
    p = parse_existing_folder_name(
        "r96fdc7_framework-maintenance_native-engine_godot_4_2_world_environment_glow_eff"
    )
    assert p.round == "r96fdc7"
    assert p.bug_class_hint == "framework-maintenance"
    assert p.category_hint == "native-engine"
    assert p.framework_hint == "godot"
    assert p.suffix == "4_2_world_environment_glow_eff"
    assert p.kind == "recent-mined"


def test_parse_recent_mined_web_map():
    p = parse_existing_folder_name(
        "rc2487a_framework-maintenance_web-map_mapbox-gl-js_symbol_icon_color_is_not_worki"
    )
    assert p.framework_hint == "mapbox-gl-js"
    assert p.category_hint == "web-map"


def test_parse_unknown_falls_back_to_legacy():
    p = parse_existing_folder_name("something_bizarre_with_no_prefix")
    assert p.kind == "unknown"
```

- [ ] **Step 5.2: Run, confirm fails**

```bash
PYTHONPATH=src/python python3 -m pytest tests/unit/python/test_migrate_layout.py -k parse -v
```

- [ ] **Step 5.3: Implement parser**

```python
# src/python/gpa/eval/migrate_layout.py
"""Migrate tests/eval/ from flat layout to taxonomy tree.

See docs/superpowers/specs/2026-05-02-eval-scenario-taxonomy-layout-design.md.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Optional


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
```

- [ ] **Step 5.4: Run, confirm passes**

```bash
PYTHONPATH=src/python python3 -m pytest tests/unit/python/test_migrate_layout.py -k parse -v
```
Expected: 6 PASS.

- [ ] **Step 5.5: Commit**

```bash
git add src/python/gpa/eval/migrate_layout.py tests/unit/python/test_migrate_layout.py
git commit -m "feat(eval): migrate_layout: parser for existing folder names"
```

---

## Task 6: Migration tool — source URL extractor

**Files:**
- Modify: `src/python/gpa/eval/migrate_layout.py`
- Modify: `tests/unit/python/test_migrate_layout.py`

- [ ] **Step 6.1: Write failing test**

```python
def test_extract_github_issue_url(tmp_path):
    from gpa.eval.migrate_layout import extract_source
    md = tmp_path / "scenario.md"
    md.write_text("Closes https://github.com/godotengine/godot/issues/86493 yay")
    src = extract_source(md)
    assert src.type == "github_issue"
    assert src.repo == "godotengine/godot"
    assert src.issue_id == 86493


def test_extract_github_pull(tmp_path):
    from gpa.eval.migrate_layout import extract_source
    md = tmp_path / "scenario.md"
    md.write_text("see https://github.com/godotengine/godot/pull/9857 fix")
    src = extract_source(md)
    assert src.type == "github_pull"
    assert src.issue_id == 9857


def test_extract_stackoverflow(tmp_path):
    from gpa.eval.migrate_layout import extract_source
    md = tmp_path / "scenario.md"
    md.write_text("see https://stackoverflow.com/questions/23460040/something")
    src = extract_source(md)
    assert src.type == "stackoverflow"
    assert src.issue_id == "23460040"


def test_extract_no_url_returns_legacy(tmp_path):
    from gpa.eval.migrate_layout import extract_source
    md = tmp_path / "scenario.md"
    md.write_text("plain text with no urls\n")
    src = extract_source(md)
    assert src.type == "legacy"
```

- [ ] **Step 6.2: Run, confirm fails**

```bash
PYTHONPATH=src/python python3 -m pytest tests/unit/python/test_migrate_layout.py -k extract -v
```

- [ ] **Step 6.3: Implement `extract_source`**

```python
# Append to src/python/gpa/eval/migrate_layout.py
from gpa.eval.scenario_metadata import Source

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
```

- [ ] **Step 6.4: Run, confirm passes**

```bash
PYTHONPATH=src/python python3 -m pytest tests/unit/python/test_migrate_layout.py -k extract -v
```
Expected: 4 PASS.

- [ ] **Step 6.5: Commit**

```bash
git add src/python/gpa/eval/migrate_layout.py tests/unit/python/test_migrate_layout.py
git commit -m "feat(eval): migrate_layout: source URL extraction"
```

---

## Task 7: Migration tool — taxonomy resolver

**Files:**
- Modify: `src/python/gpa/eval/migrate_layout.py`
- Modify: `tests/unit/python/test_migrate_layout.py`

Resolves `(category, framework)` from (parsed name, source). Order of precedence: overrides > parsed-name hints > repo lookup in `mining_rules.yaml` > unresolved.

- [ ] **Step 7.1: Write failing tests**

```python
def test_resolve_taxonomy_from_parsed_hints():
    from gpa.eval.migrate_layout import (
        ParsedName, resolve_taxonomy, ResolveContext,
    )
    from gpa.eval.scenario_metadata import Source
    p = ParsedName(round="r96fdc7", category_hint="native-engine",
                   framework_hint="godot", bug_class_hint="framework-maintenance",
                   suffix="x", kind="recent-mined")
    src = Source(type="github_issue", repo="godotengine/godot", issue_id=86493)
    ctx = ResolveContext(rules={}, overrides={})
    cat, fw, bc = resolve_taxonomy(p, src, ctx)
    assert cat == "native-engine"
    assert fw == "godot"
    assert bc == "framework-internal"  # framework-maintenance => framework-internal


def test_resolve_taxonomy_from_repo_lookup():
    from gpa.eval.migrate_layout import (
        ParsedName, resolve_taxonomy, ResolveContext,
    )
    from gpa.eval.scenario_metadata import Source
    p = ParsedName(round="r14", category_hint=None, framework_hint=None,
                   bug_class_hint=None, suffix="bevy_child_text_invisible",
                   kind="early-mined")
    src = Source(type="github_issue", repo="bevyengine/bevy", issue_id=14732)
    ctx = ResolveContext(
        rules={"bevyengine/bevy": ("native-engine", "bevy")},
        overrides={},
    )
    cat, fw, bc = resolve_taxonomy(p, src, ctx)
    assert cat == "native-engine"
    assert fw == "bevy"
    assert bc == "framework-internal"


def test_resolve_taxonomy_synthetic():
    from gpa.eval.migrate_layout import (
        ParsedName, resolve_taxonomy, ResolveContext,
    )
    from gpa.eval.scenario_metadata import Source
    p = ParsedName(round="e1", category_hint=None, framework_hint=None,
                   bug_class_hint=None, suffix="state_leak", kind="synthetic")
    src = Source(type="synthetic")
    ctx = ResolveContext(rules={}, overrides={})
    cat, fw, bc = resolve_taxonomy(p, src, ctx)
    assert cat == "synthetic"
    assert fw == "synthetic"
    assert bc == "synthetic"


def test_resolve_taxonomy_overrides_win():
    from gpa.eval.migrate_layout import (
        ParsedName, resolve_taxonomy, ResolveContext,
    )
    from gpa.eval.scenario_metadata import Source
    p = ParsedName(round="r2", category_hint=None, framework_hint=None,
                   bug_class_hint=None, suffix="weird_thing", kind="early-mined")
    src = Source(type="legacy")
    ctx = ResolveContext(
        rules={},
        overrides={"r2_weird_thing": {"category": "web-3d", "framework": "three.js",
                                       "bug_class": "consumer-misuse"}},
    )
    cat, fw, bc = resolve_taxonomy(p, src, ctx, original_name="r2_weird_thing")
    assert cat == "web-3d"
    assert fw == "three.js"
    assert bc == "consumer-misuse"


def test_resolve_taxonomy_unresolved():
    from gpa.eval.migrate_layout import (
        ParsedName, resolve_taxonomy, ResolveContext,
    )
    from gpa.eval.scenario_metadata import Source
    p = ParsedName(round="r3", category_hint=None, framework_hint=None,
                   bug_class_hint=None, suffix="nothing", kind="early-mined")
    src = Source(type="legacy")
    ctx = ResolveContext(rules={}, overrides={})
    cat, fw, bc = resolve_taxonomy(p, src, ctx, original_name="r3_nothing")
    assert cat is None
    assert fw is None
```

- [ ] **Step 7.2: Run, confirm fails**

```bash
PYTHONPATH=src/python python3 -m pytest tests/unit/python/test_migrate_layout.py -k resolve -v
```

- [ ] **Step 7.3: Implement `resolve_taxonomy` and `ResolveContext`**

```python
# Append to src/python/gpa/eval/migrate_layout.py

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
```

- [ ] **Step 7.4: Run, confirm passes**

```bash
PYTHONPATH=src/python python3 -m pytest tests/unit/python/test_migrate_layout.py -k resolve -v
```

- [ ] **Step 7.5: Commit**

```bash
git add src/python/gpa/eval/migrate_layout.py tests/unit/python/test_migrate_layout.py
git commit -m "feat(eval): migrate_layout: taxonomy resolver"
```

---

## Task 8: Migration tool — slug builder + topic bucketer

**Files:**
- Modify: `src/python/gpa/eval/migrate_layout.py`
- Modify: `tests/unit/python/test_migrate_layout.py`

- [ ] **Step 8.1: Write failing tests**

```python
def test_build_slug_github_issue():
    from gpa.eval.migrate_layout import build_slug, ParsedName
    from gpa.eval.scenario_metadata import Source
    p = ParsedName(round="r96fdc7", category_hint=None, framework_hint=None,
                   bug_class_hint=None, suffix="world_environment_glow_eff",
                   kind="recent-mined")
    src = Source(type="github_issue", repo="godotengine/godot", issue_id=86493)
    assert build_slug(p, src) == "godot_86493_world_environment_glow_eff"


def test_build_slug_normalizes_repo_name():
    from gpa.eval.migrate_layout import build_slug, ParsedName
    from gpa.eval.scenario_metadata import Source
    p = ParsedName(round="r1", category_hint=None, framework_hint=None,
                   bug_class_hint=None, suffix="x", kind="early-mined")
    src = Source(type="github_issue", repo="mrdoob/three.js", issue_id=29841)
    assert build_slug(p, src) == "threejs_29841_x"


def test_build_slug_pull():
    from gpa.eval.migrate_layout import build_slug, ParsedName
    from gpa.eval.scenario_metadata import Source
    p = ParsedName(round="r1", category_hint=None, framework_hint=None,
                   bug_class_hint=None, suffix="z", kind="early-mined")
    src = Source(type="github_pull", repo="google/filament", issue_id=9857)
    assert build_slug(p, src) == "filament_pull_9857_z"


def test_build_slug_stackoverflow():
    from gpa.eval.migrate_layout import build_slug, ParsedName
    from gpa.eval.scenario_metadata import Source
    p = ParsedName(round="r0", category_hint=None, framework_hint=None,
                   bug_class_hint=None, suffix="effectcomposer_resize",
                   kind="early-mined")
    src = Source(type="stackoverflow", repo=None, issue_id="23460040")
    assert build_slug(p, src) == "so_23460040_effectcomposer_resize"


def test_build_slug_synthetic():
    from gpa.eval.migrate_layout import build_slug, ParsedName
    from gpa.eval.scenario_metadata import Source
    p = ParsedName(round="e1", category_hint=None, framework_hint=None,
                   bug_class_hint=None, suffix="state_leak", kind="synthetic")
    src = Source(type="synthetic")
    assert build_slug(p, src) == "e1_state_leak"


def test_build_slug_legacy():
    from gpa.eval.migrate_layout import build_slug, ParsedName
    from gpa.eval.scenario_metadata import Source
    p = ParsedName(round="r3", category_hint=None, framework_hint=None,
                   bug_class_hint=None, suffix="black_screen", kind="early-mined")
    src = Source(type="legacy")
    assert build_slug(p, src) == "legacy_r3_black_screen"


def test_synthetic_topic_bucket():
    from gpa.eval.migrate_layout import synthetic_topic
    assert synthetic_topic("state_leak_xxx") == "state-leak"
    assert synthetic_topic("uniform_value_leaked") == "uniform"
    assert synthetic_topic("depth_test") == "depth"
    assert synthetic_topic("reversed_z_etc") == "depth"
    assert synthetic_topic("culling_x") == "culling"
    assert synthetic_topic("stencil_y") == "stencil"
    assert synthetic_topic("nan_propagation") == "nan"
    assert synthetic_topic("compensating_vp") == "misc"
    assert synthetic_topic("scissor_not_reset") == "misc"
```

- [ ] **Step 8.2: Run, confirm fails**

```bash
PYTHONPATH=src/python python3 -m pytest tests/unit/python/test_migrate_layout.py -k 'build_slug or synthetic_topic' -v
```

- [ ] **Step 8.3: Implement `build_slug` and `synthetic_topic`**

```python
# Append to src/python/gpa/eval/migrate_layout.py

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
```

- [ ] **Step 8.4: Run, confirm passes**

```bash
PYTHONPATH=src/python python3 -m pytest tests/unit/python/test_migrate_layout.py -v
```

- [ ] **Step 8.5: Commit**

```bash
git add src/python/gpa/eval/migrate_layout.py tests/unit/python/test_migrate_layout.py
git commit -m "feat(eval): migrate_layout: slug builder and synthetic topic bucketer"
```

---

## Task 9: Migration tool — plan builder + conflict resolution

**Files:**
- Modify: `src/python/gpa/eval/migrate_layout.py`
- Modify: `tests/unit/python/test_migrate_layout.py`

The "plan" is a pure-data list of (old_path, new_path, scenario_yaml_data) — no I/O.

- [ ] **Step 9.1: Write failing test**

```python
def test_plan_one_synthetic(tmp_path):
    from gpa.eval.migrate_layout import build_plan, ResolveContext
    (tmp_path / "e1_state_leak").mkdir()
    (tmp_path / "e1_state_leak" / "scenario.md").write_text("# x")
    (tmp_path / "e1_state_leak" / "main.c").write_text("int main(){}")
    ctx = ResolveContext(rules={}, overrides={})
    plan = build_plan(tmp_path, ctx)
    assert len(plan.entries) == 1
    e = plan.entries[0]
    assert e.new_relative == Path("synthetic/state-leak/e1_state_leak")
    assert e.scenario.taxonomy.category == "synthetic"


def test_plan_resolves_conflict_with_suffix(tmp_path):
    from gpa.eval.migrate_layout import build_plan, ResolveContext
    # Two early-mined that would collide on slug
    (tmp_path / "r10_polygon_xxx").mkdir()
    (tmp_path / "r10_polygon_xxx" / "scenario.md").write_text("https://github.com/x/y/issues/1")
    (tmp_path / "r12_polygon_xxx").mkdir()
    (tmp_path / "r12_polygon_xxx" / "scenario.md").write_text("https://github.com/x/y/issues/1")
    ctx = ResolveContext(rules={"x/y": ("web-3d", "three.js")}, overrides={})
    plan = build_plan(tmp_path, ctx)
    leaves = sorted(e.new_relative.name for e in plan.entries)
    # Both rooted under same fw; second one gets _02 appended
    assert leaves[0].startswith("y_1_polygon_xxx")
    assert leaves[1] == leaves[0] + "_02" or leaves[0].endswith("_02")


def test_plan_unresolved_emits_review(tmp_path):
    from gpa.eval.migrate_layout import build_plan, ResolveContext
    (tmp_path / "r99_mystery").mkdir()
    (tmp_path / "r99_mystery" / "scenario.md").write_text("no urls here")
    ctx = ResolveContext(rules={}, overrides={})
    plan = build_plan(tmp_path, ctx)
    assert len(plan.review_rows) == 1
    assert "r99_mystery" in plan.review_rows[0]["original_name"]
    # Unresolved scenarios still get a plan entry, under _legacy/
    assert any("_legacy" in str(e.new_relative) for e in plan.entries)
```

- [ ] **Step 9.2: Run, confirm fails**

```bash
PYTHONPATH=src/python python3 -m pytest tests/unit/python/test_migrate_layout.py -k plan -v
```

- [ ] **Step 9.3: Implement `build_plan` + `MigrationPlan`**

```python
# Append to src/python/gpa/eval/migrate_layout.py
from datetime import date
from gpa.eval.scenario_metadata import (
    Scenario, Source, Taxonomy, Backend,
)


@dataclass
class PlanEntry:
    old_path: Path
    new_relative: Path                  # relative to root
    scenario: Scenario


@dataclass
class MigrationPlan:
    entries: list[PlanEntry]
    review_rows: list[dict]
    conflicts: list[dict]


def build_plan(root: Path, ctx: ResolveContext) -> MigrationPlan:
    entries: list[PlanEntry] = []
    review: list[dict] = []
    conflicts: list[dict] = []
    seen_slugs: dict[str, Path] = {}    # slug -> first old_path that claimed it
    today = date.today().isoformat()

    for child in sorted(root.iterdir()):
        if not child.is_dir() or not (child / "scenario.md").exists():
            continue
        original_name = child.name
        parsed = parse_existing_folder_name(original_name)
        source = extract_source(child / "scenario.md")
        # Synthetic kind always overrides source type for older e* dirs that
        # don't link to issues.
        if parsed.kind == "synthetic":
            source = Source(type="synthetic")
        cat, fw, bc = resolve_taxonomy(parsed, source, ctx, original_name=original_name)

        slug = build_slug(parsed, source)
        # Conflict resolution: append _02, _03, ...
        if slug in seen_slugs:
            i = 2
            while f"{slug}_{i:02d}" in seen_slugs:
                i += 1
            new_slug = f"{slug}_{i:02d}"
            conflicts.append({
                "original_name": original_name,
                "first_claimed_by": str(seen_slugs[slug]),
                "resolved_to": new_slug,
            })
            slug = new_slug
        seen_slugs[slug] = child

        if cat is None or fw is None:
            review.append({
                "original_name": original_name,
                "kind": parsed.kind,
                "source_type": source.type,
                "repo": source.repo or "",
                "suggested_slug": f"legacy_{parsed.round}_{parsed.suffix}",
            })
            cat, fw = "synthetic", "synthetic"  # placeholder; real path is _legacy
            new_rel = Path("_legacy") / f"legacy_{parsed.round}_{parsed.suffix}"
            slug = new_rel.name
        elif cat == "synthetic":
            new_rel = Path("synthetic") / synthetic_topic(parsed.suffix) / slug
        else:
            new_rel = Path(cat) / fw / slug

        scenario = Scenario(
            path=root / new_rel,
            slug=slug,
            round=parsed.round,
            mined_at=today,
            source=source,
            taxonomy=Taxonomy(category=cat, framework=fw, bug_class=bc),
            backend=Backend(),
            status="drafted",
        )
        entries.append(PlanEntry(old_path=child, new_relative=new_rel, scenario=scenario))

    return MigrationPlan(entries=entries, review_rows=review, conflicts=conflicts)
```

- [ ] **Step 9.4: Run, confirm passes**

```bash
PYTHONPATH=src/python python3 -m pytest tests/unit/python/test_migrate_layout.py -k plan -v
```

- [ ] **Step 9.5: Commit**

```bash
git add src/python/gpa/eval/migrate_layout.py tests/unit/python/test_migrate_layout.py
git commit -m "feat(eval): migrate_layout: plan builder with conflict resolution"
```

---

## Task 10: Migration tool — apply (git mv + codegen) + CLI

**Files:**
- Modify: `src/python/gpa/eval/migrate_layout.py`
- Create: `src/python/gpa/eval/migration_overrides.yaml` (initially empty: `{}`)
- Modify: `tests/unit/python/test_migrate_layout.py`

- [ ] **Step 10.1: Write failing test for `apply_plan` (no git, just file moves)**

```python
def test_apply_plan_moves_files_and_writes_yaml(tmp_path, monkeypatch):
    from gpa.eval.migrate_layout import build_plan, apply_plan, ResolveContext
    (tmp_path / "e1_state_leak").mkdir()
    (tmp_path / "e1_state_leak" / "scenario.md").write_text("# x")
    (tmp_path / "e1_state_leak" / "main.c").write_text("int main(){}")
    ctx = ResolveContext(rules={}, overrides={})
    plan = build_plan(tmp_path, ctx)
    apply_plan(plan, tmp_path, use_git=False, write_build_files=True)
    new_dir = tmp_path / "synthetic" / "state-leak" / "e1_state_leak"
    assert (new_dir / "scenario.md").exists()
    assert (new_dir / "scenario.yaml").exists()
    assert (new_dir / "main.c").exists()
    assert (new_dir / "BUILD.bazel").exists()
    assert not (tmp_path / "e1_state_leak").exists()
    # BUILD content sanity check
    build_text = (new_dir / "BUILD.bazel").read_text()
    assert 'name = "e1_state_leak"' in build_text


def test_apply_plan_no_build_for_md_only(tmp_path):
    from gpa.eval.migrate_layout import build_plan, apply_plan, ResolveContext
    (tmp_path / "r96fdc7_framework-maintenance_native-engine_godot_x").mkdir()
    (tmp_path / "r96fdc7_framework-maintenance_native-engine_godot_x" / "scenario.md").write_text(
        "https://github.com/godotengine/godot/issues/1"
    )
    ctx = ResolveContext(rules={"godotengine/godot": ("native-engine", "godot")}, overrides={})
    plan = build_plan(tmp_path, ctx)
    apply_plan(plan, tmp_path, use_git=False, write_build_files=True)
    new_dir = tmp_path / "native-engine" / "godot" / "godot_1_x"
    assert (new_dir / "scenario.md").exists()
    assert (new_dir / "scenario.yaml").exists()
    assert not (new_dir / "BUILD.bazel").exists()
```

- [ ] **Step 10.2: Run, confirm fails**

```bash
PYTHONPATH=src/python python3 -m pytest tests/unit/python/test_migrate_layout.py -k apply -v
```

- [ ] **Step 10.3: Implement `apply_plan` + CLI entry point**

```python
# Append to src/python/gpa/eval/migrate_layout.py
import shutil
import subprocess
import argparse
import csv
import sys
from gpa.eval.scenario_metadata import dump_scenario_yaml


_BUILD_BAZEL_TEMPLATE = '''load("@rules_cc//cc:defs.bzl", "cc_binary")

cc_binary(
    name = "{name}",
    srcs = glob(["*.c"]),
    copts = [
        "-g",
        "-gdwarf-4",
        "-fno-omit-frame-pointer",
        "-O0",
    ],
    linkopts = ["-lGL", "-lX11", "-lm"],
    visibility = ["//visibility:public"],
)
'''


def apply_plan(
    plan: MigrationPlan,
    root: Path,
    use_git: bool = True,
    write_build_files: bool = True,
) -> None:
    """Move each scenario to its new location and write scenario.yaml.

    With use_git=True, runs `git mv` (preserves history). Otherwise uses
    shutil.move (used in tests).
    """
    for entry in plan.entries:
        new_path = root / entry.new_relative
        new_path.parent.mkdir(parents=True, exist_ok=True)
        if use_git:
            subprocess.run(
                ["git", "mv", str(entry.old_path), str(new_path)],
                check=True, cwd=root,
            )
        else:
            shutil.move(str(entry.old_path), str(new_path))
        # Write yaml + optional BUILD.bazel.
        dump_scenario_yaml(entry.scenario, new_path / "scenario.yaml")
        if write_build_files and any(new_path.glob("*.c")):
            (new_path / "BUILD.bazel").write_text(
                _BUILD_BAZEL_TEMPLATE.format(name=entry.scenario.slug)
            )


def write_review_csv(plan: MigrationPlan, path: Path) -> None:
    if not plan.review_rows:
        return
    with open(path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(plan.review_rows[0].keys()))
        w.writeheader()
        w.writerows(plan.review_rows)


def main(argv: Optional[list[str]] = None) -> int:
    p = argparse.ArgumentParser(prog="migrate_layout")
    p.add_argument("--root", type=Path, required=True,
                   help="Path to tests/eval/")
    p.add_argument("--rules", type=Path,
                   default=Path("src/python/gpa/eval/curation/mining_rules.yaml"))
    p.add_argument("--overrides", type=Path,
                   default=Path("src/python/gpa/eval/migration_overrides.yaml"))
    p.add_argument("--review-csv", type=Path, default=Path("/tmp/migration_review.csv"))
    p.add_argument("--apply", action="store_true",
                   help="Actually move files. Default is dry-run.")
    p.add_argument("--no-build-files", action="store_true",
                   help="Skip BUILD.bazel codegen (useful when staging in two commits)")
    args = p.parse_args(argv)

    ctx = load_resolve_context(args.rules, args.overrides)
    plan = build_plan(args.root, ctx)

    print(f"Planned moves: {len(plan.entries)}")
    print(f"Review rows:   {len(plan.review_rows)}")
    print(f"Conflicts:     {len(plan.conflicts)}")

    write_review_csv(plan, args.review_csv)
    print(f"Review CSV:    {args.review_csv}")

    if args.apply:
        apply_plan(plan, args.root, use_git=True,
                   write_build_files=not args.no_build_files)
        print("Applied.")
    else:
        for e in plan.entries[:10]:
            print(f"  {e.old_path.name} -> {e.new_relative}")
        if len(plan.entries) > 10:
            print(f"  ... ({len(plan.entries) - 10} more)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 10.4: Create empty overrides yaml**

```bash
echo "{}" > src/python/gpa/eval/migration_overrides.yaml
```

- [ ] **Step 10.5: Run tests**

```bash
PYTHONPATH=src/python python3 -m pytest tests/unit/python/test_migrate_layout.py -v
```

- [ ] **Step 10.6: Commit**

```bash
git add src/python/gpa/eval/migrate_layout.py src/python/gpa/eval/migration_overrides.yaml tests/unit/python/test_migrate_layout.py
git commit -m "feat(eval): migrate_layout: apply step + CLI"
```

---

## Task 11: Dry-run on real `tests/eval/` and author overrides

**Files:**
- Modify: `src/python/gpa/eval/migration_overrides.yaml`

This is the operator step. No code change beyond the overrides file.

- [ ] **Step 11.1: Run dry-run, capture output**

```bash
PYTHONPATH=src/python python3 -m gpa.eval.migrate_layout \
    --root tests/eval \
    --review-csv /tmp/migration_review.csv \
    > /tmp/dryrun.txt 2>&1
head -40 /tmp/dryrun.txt
echo "---"
cat /tmp/migration_review.csv | head -30
```

- [ ] **Step 11.2: Review unresolved scenarios**

For each row in `migration_review.csv`, look at the original folder's `scenario.md` content and decide the right `(category, framework, bug_class)`. Edit `src/python/gpa/eval/migration_overrides.yaml`:

```yaml
# Format: original_folder_name -> {category, framework, bug_class}
r4_3d_map_black_screen:
  category: web-map
  framework: cesium
  bug_class: consumer-misuse
# ... etc
```

- [ ] **Step 11.3: Re-run dry-run, confirm review_rows shrinks**

```bash
PYTHONPATH=src/python python3 -m gpa.eval.migrate_layout --root tests/eval | head -5
```
Expected: "Review rows: 0" (or operator-acceptable small number for true `_legacy/` cases).

- [ ] **Step 11.4: Verify counts**

```bash
PYTHONPATH=src/python python3 -m gpa.eval.migrate_layout --root tests/eval 2>&1 | grep "Planned moves"
cat /tmp/pre_migration_count.txt
```
Expected: "Planned moves" matches the pre-migration count (e.g., 198).

- [ ] **Step 11.5: Commit overrides**

```bash
git add src/python/gpa/eval/migration_overrides.yaml
git commit -m "chore(eval): author migration_overrides for unresolved legacy scenarios"
```

---

## Task 12: Apply migration — moves only (one commit)

**Files:**
- All `tests/eval/*/` (moved)

Per the spec, the move commit is `git mv`-only, no content edits. Run with `--no-build-files` so `BUILD.bazel`s are generated in the next commit.

- [ ] **Step 12.1: Confirm clean tree**

```bash
git status --short
```
Expected: only the spec/plan/overrides/migration_layout.py changes from earlier commits, no other dirty files.

- [ ] **Step 12.2: Apply moves (also writes scenario.yaml, but no BUILD.bazel)**

```bash
PYTHONPATH=src/python python3 -m gpa.eval.migrate_layout --root tests/eval --apply --no-build-files
```

- [ ] **Step 12.3: Verify counts and structure**

```bash
find tests/eval -name scenario.md | wc -l           # must equal pre_migration_count
find tests/eval -name scenario.yaml | wc -l         # same
ls tests/eval/                                       # should show category dirs
```
Expected: counts match, top-level only contains `BUILD.bazel`, `README.md`, `synthetic/`, `native-engine/`, `web-3d/`, `web-2d/`, `web-map/`, `scientific/`, possibly `_legacy/`.

- [ ] **Step 12.4: Verify `git log --follow` works on a sample**

```bash
git log --follow tests/eval/synthetic/state-leak/e1_state_leak/scenario.md | head -10
```
Expected: history extends back through the `git mv` to the original `tests/eval/e1_state_leak/scenario.md`.

- [ ] **Step 12.5: Run schema validation**

```bash
PYTHONPATH=src/python python3 -c "
from pathlib import Path
from gpa.eval.scenario_metadata import validate_all
errors = validate_all(Path('tests/eval'))
for e in errors:
    print(e)
print(f'Total errors: {len(errors)}')
"
```
Expected: 0 errors.

- [ ] **Step 12.6: Commit**

```bash
git add -A tests/eval
git commit -m "refactor(eval): migrate scenarios into taxonomy tree

Move all 198 scenarios from flat layout to <category>/<framework>/<slug>/
(synthetic/<topic>/<slug>/ for handcrafted). Adds scenario.yaml sidecar
with round/source/taxonomy/backend metadata. Per-leaf BUILD.bazel files
land in the next commit.

See docs/superpowers/specs/2026-05-02-eval-scenario-taxonomy-layout-design.md."
```

---

## Task 13: Add per-leaf BUILD.bazel + rewrite top-level BUILD.bazel + README.md

**Files:**
- Modify: `tests/eval/BUILD.bazel`
- Modify: `tests/eval/README.md`
- Create: `tests/eval/<every-leaf-with-c-files>/BUILD.bazel` (codegen)

- [ ] **Step 13.1: Run migrate_layout in `--build-files-only` mode**

Add a small wrapper to do this without re-moving:

```bash
PYTHONPATH=src/python python3 -c "
from pathlib import Path
from gpa.eval.scenario_metadata import iter_scenarios
TEMPLATE = '''load(\"@rules_cc//cc:defs.bzl\", \"cc_binary\")

cc_binary(
    name = \"{name}\",
    srcs = glob([\"*.c\"]),
    copts = [\"-g\", \"-gdwarf-4\", \"-fno-omit-frame-pointer\", \"-O0\"],
    linkopts = [\"-lGL\", \"-lX11\", \"-lm\"],
    visibility = [\"//visibility:public\"],
)
'''
root = Path('tests/eval')
n = 0
for s in iter_scenarios(root):
    if any(s.path.glob('*.c')):
        (s.path / 'BUILD.bazel').write_text(TEMPLATE.format(name=s.slug))
        n += 1
print(f'Wrote {n} BUILD.bazel files')
"
```

- [ ] **Step 13.2: Replace top-level `tests/eval/BUILD.bazel`**

Replace the file's contents with:

```python
# tests/eval/BUILD.bazel
# Eval scenarios live in subpackages organized by taxonomy:
#   synthetic/<topic>/<slug>/      (hand-authored scenarios)
#   <category>/<framework>/<slug>/ (mined real-world bugs)
#
# Each scenario subpackage has its own BUILD.bazel that declares a
# cc_binary named after the leaf slug (only when *.c files exist).
#
# Build all runnable scenarios:
#   bazel build //tests/eval/...
#
# See docs/superpowers/specs/2026-05-02-eval-scenario-taxonomy-layout-design.md
```

- [ ] **Step 13.3: Verify Bazel build**

```bash
bazel build //tests/eval/... 2>&1 | tail -20
```
Expected: BUILD SUCCESSFUL, with one cc_binary built per `.c`-bearing leaf.

- [ ] **Step 13.4: Rewrite `tests/eval/README.md`**

Replace contents with the new layout description (see spec section "Folder Layout" for source material). Include:
- The directory tree at a glance.
- Slug rules table.
- `scenario.yaml` schema summary with link to spec.
- How to add a new scenario.
- How to query the index.

- [ ] **Step 13.5: Run pytest validator end-to-end**

```bash
PYTHONPATH=src/python python3 -m pytest tests/unit/python/test_scenario_metadata.py -v
```
Expected: all PASS.

- [ ] **Step 13.6: Commit**

```bash
git add tests/eval
git commit -m "build(eval): per-leaf BUILD.bazel + new top-level README

Generates one cc_binary per scenario leaf (only when *.c files exist),
rewrites tests/eval/BUILD.bazel as documentation only, rewrites
tests/eval/README.md for the new layout."
```

---

## Task 14: Update consumer scripts and docs

**Files:**
- Modify: `scripts/run-eval-claude-code.sh`
- Modify: `docs/gpa-trace-native-usage.md`
- Modify: `docs/eval-results.md`
- Modify: `docs/superpowers/specs/2026-04-17-eval-set-real-world-design.md`
- Modify: `docs/superpowers/specs/2026-04-28-omnispace-gen-integration-design.md`
- Modify: `CLAUDE.md`

Each change is a one-line path rewrite. The new paths:

| Old | New |
|---|---|
| `tests/eval/e1_state_leak.c` | `tests/eval/synthetic/state-leak/e1_state_leak/main.c` |
| `bazel-bin/tests/eval/e5_uniform_collision` | `bazel-bin/tests/eval/synthetic/uniform/e5_uniform_collision/e5_uniform_collision` |
| `tests/eval/r15_*` (in eval-results.md) | check actual new path via `git log --follow` and update |
| `tests/eval/r37_joint_offset_smplx/` | `tests/eval/synthetic/misc/legacy_r37_joint_offset_smplx/` *(or whatever migrate_layout produced — confirm before rewriting)* |

- [ ] **Step 14.1: Find every old path reference**

```bash
grep -rE "tests/eval/[re][0-9]" docs/ scripts/ CLAUDE.md 2>/dev/null
```

- [ ] **Step 14.2: Rewrite each reference one file at a time, verify via git diff**

```bash
# example pattern
sed -i 's|tests/eval/e1_state_leak\.c|tests/eval/synthetic/state-leak/e1_state_leak/main.c|g' scripts/run-eval-claude-code.sh
git diff scripts/run-eval-claude-code.sh
```
*(Don't blanket sed; review each file because some are hard-coded paths in prose that may also need surrounding-text edits.)*

- [ ] **Step 14.3: Add "Superseded" pointer to old spec**

Edit `docs/superpowers/specs/2026-04-17-eval-set-real-world-design.md`. Insert after the title:

```markdown
> **Note (2026-05-02):** The folder-layout aspects of this spec are superseded
> by `docs/superpowers/specs/2026-05-02-eval-scenario-taxonomy-layout-design.md`.
> The mining/curation pipeline design here remains current.
```

- [ ] **Step 14.4: Update CLAUDE.md eval examples**

In CLAUDE.md, find the "Running the Eval" code block and update:
- `bazel-bin/tests/eval/SCENARIO_NAME` example with concrete new path.
- Any other path that the migration moved.

- [ ] **Step 14.5: Verify nothing references old paths**

```bash
grep -rE "tests/eval/[re][0-9]" docs/ scripts/ CLAUDE.md src/python/gpa/eval/ 2>/dev/null
```
Expected: no output (or only false positives in unmoved files like the spec itself).

- [ ] **Step 14.6: Commit**

```bash
git add -A docs/ scripts/ CLAUDE.md
git commit -m "docs(eval): rewrite scenario path references for new taxonomy layout"
```

---

## Task 15: Update mining pipeline to emit new layout

**Files:**
- Modify: `src/python/gpa/eval/curation/draft.py`
- Modify: `src/python/gpa/eval/curation/run.py`
- Modify: `src/python/gpa/eval/curation/journey.py`
- Test: `tests/unit/python/test_curation_draft_layout.py`

The `draft.DraftLib` is what actually writes new mined scenarios to disk. After migration, it must write to `<category>/<framework>/<slug>/` instead of `tests/eval/<r{round}_...>/`.

- [ ] **Step 15.1: Read current draft.py to find where it writes**

```bash
grep -n "scenario_id\|scenario_dir\|write\|files\[" src/python/gpa/eval/curation/draft.py | head -20
```

- [ ] **Step 15.2: Write failing test for the new path computation**

```python
# tests/unit/python/test_curation_draft_layout.py
import pytest
from pathlib import Path
from gpa.eval.curation.draft import compute_scenario_dir


def test_compute_scenario_dir_new_layout(tmp_path):
    out = compute_scenario_dir(
        eval_root=tmp_path / "tests" / "eval",
        category="native-engine",
        framework="godot",
        slug="godot_86493_world_environment_glow",
    )
    assert out == tmp_path / "tests" / "eval" / "native-engine" / "godot" / "godot_86493_world_environment_glow"


def test_compute_scenario_dir_synthetic(tmp_path):
    out = compute_scenario_dir(
        eval_root=tmp_path / "tests" / "eval",
        category="synthetic",
        framework="synthetic",
        slug="e34_new_synth",
    )
    assert "synthetic" in str(out)
```

- [ ] **Step 15.3: Run, confirm fails**

```bash
PYTHONPATH=src/python python3 -m pytest tests/unit/python/test_curation_draft_layout.py -v
```
Expected: `compute_scenario_dir` not found.

- [ ] **Step 15.4: Add `compute_scenario_dir` to draft.py**

```python
# Add to src/python/gpa/eval/curation/draft.py
def compute_scenario_dir(
    eval_root: Path,
    category: str,
    framework: str,
    slug: str,
) -> Path:
    """Compute the destination directory for a new mined scenario in the
    taxonomy-tree layout (see spec 2026-05-02-eval-scenario-taxonomy-layout)."""
    if category == "synthetic":
        # Synthetic scenarios are bucketed by topic; topic isn't known here,
        # so caller is responsible for inserting the topic segment. Default
        # to misc/ for forward-going synthetic emissions.
        from gpa.eval.migrate_layout import synthetic_topic
        suffix = slug.split("_", 1)[1] if "_" in slug else slug
        return eval_root / "synthetic" / synthetic_topic(suffix) / slug
    return eval_root / category / framework / slug
```

- [ ] **Step 15.5: Update `DraftLib` and call sites to use `compute_scenario_dir`**

Find every `tests/eval/<scenario_id>/` construction and replace with `compute_scenario_dir(...)`. The triage step already produces `(category, framework)` tuples (see `src/python/gpa/eval/curation/rules.py:infer_taxonomy`); pipe that through to `draft`.

- [ ] **Step 15.6: Run tests**

```bash
PYTHONPATH=src/python python3 -m pytest tests/unit/python/test_curation_draft_layout.py tests/unit/python/test_curation_*.py -v
```
Expected: all PASS.

- [ ] **Step 15.7: Commit**

```bash
git add src/python/gpa/eval/curation/draft.py src/python/gpa/eval/curation/run.py src/python/gpa/eval/curation/journey.py tests/unit/python/test_curation_draft_layout.py
git commit -m "feat(curation): emit new mined scenarios into taxonomy tree"
```

---

## Task 16: Index CLI

**Files:**
- Create: `src/python/gpa/eval/index_cli.py`
- Create: `tests/unit/python/test_index_cli.py`
- Modify: `pyproject.toml`

- [ ] **Step 16.1: Write failing test for the table renderer**

```python
def test_index_by_taxonomy_renders_counts(tmp_path):
    from gpa.eval.index_cli import build_taxonomy_table
    from gpa.eval.scenario_metadata import (
        Scenario, Source, Taxonomy, Backend, dump_scenario_yaml,
    )
    for cat, fw, slug in [
        ("native-engine", "godot", "x1"),
        ("native-engine", "godot", "x2"),
        ("web-3d", "three.js", "y1"),
    ]:
        d = tmp_path / cat / fw / slug
        d.mkdir(parents=True)
        (d / "scenario.md").write_text("x")
        s = Scenario(path=d, slug=slug, round="r1", mined_at="2026-01-01",
                     source=Source(type="synthetic"),
                     taxonomy=Taxonomy(category=cat, framework=fw, bug_class="synthetic"),
                     backend=Backend(), status="drafted")
        dump_scenario_yaml(s, d / "scenario.yaml")
    table = build_taxonomy_table(tmp_path)
    assert "native-engine" in table
    assert "godot" in table
    assert "2" in table  # 2 godot scenarios
```

- [ ] **Step 16.2: Run, confirm fails**

```bash
PYTHONPATH=src/python python3 -m pytest tests/unit/python/test_index_cli.py -v
```

- [ ] **Step 16.3: Implement `index_cli.py`**

```python
# src/python/gpa/eval/index_cli.py
"""Read-only reporter for the eval scenario index."""
from __future__ import annotations

import argparse
import sys
from collections import Counter
from pathlib import Path

from gpa.eval.scenario_metadata import iter_scenarios


def build_taxonomy_table(root: Path) -> str:
    counts: Counter = Counter()
    for s in iter_scenarios(root):
        counts[(s.taxonomy.category, s.taxonomy.framework)] += 1
    rows = sorted(counts.items())
    lines = ["| category | framework | count |", "|---|---|---|"]
    for (cat, fw), n in rows:
        lines.append(f"| {cat} | {fw} | {n} |")
    return "\n".join(lines)


def build_backend_table(root: Path) -> str:
    counts: Counter = Counter()
    for s in iter_scenarios(root):
        counts[(s.backend.api, s.backend.status)] += 1
    rows = sorted(counts.items())
    lines = ["| api | status | count |", "|---|---|---|"]
    for (api, st), n in rows:
        lines.append(f"| {api} | {st} | {n} |")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="gpa-eval")
    sub = p.add_subparsers(dest="cmd", required=True)
    px = sub.add_parser("index")
    px.add_argument("--by", choices=["taxonomy", "backend"], default="taxonomy")
    px.add_argument("--root", type=Path, default=Path("tests/eval"))
    args = p.parse_args(argv)
    if args.cmd == "index" and args.by == "taxonomy":
        print(build_taxonomy_table(args.root))
    elif args.cmd == "index" and args.by == "backend":
        print(build_backend_table(args.root))
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 16.4: Add script entry to pyproject.toml**

```toml
[project.scripts]
gpa-curate = "gpa.eval.curation.pipeline:main"
gpa = "gpa.cli.main:main"
gpa-eval = "gpa.eval.index_cli:main"
```

- [ ] **Step 16.5: Verify**

```bash
PYTHONPATH=src/python python3 -m pytest tests/unit/python/test_index_cli.py -v
PYTHONPATH=src/python python3 -m gpa.eval.index_cli index --by taxonomy --root tests/eval | head -10
```

- [ ] **Step 16.6: Commit**

```bash
git add src/python/gpa/eval/index_cli.py tests/unit/python/test_index_cli.py pyproject.toml
git commit -m "feat(eval): index CLI for taxonomy/backend reports"
```

---

## Task 17: Final verification

**Files:**
- None (verification only)

- [ ] **Step 17.1: Full test suite**

```bash
PYTHONPATH=src/python python3 -m pytest tests/unit/python/ -q
```
Expected: all PASS.

- [ ] **Step 17.2: Bazel build**

```bash
bazel build //tests/eval/... 2>&1 | tail -10
```
Expected: BUILD SUCCESSFUL.

- [ ] **Step 17.3: Bazel-built scenario runs**

Pick one synthetic scenario with a `.c` file and run it:

```bash
bazel build //tests/eval/synthetic/state-leak/e1_state_leak
ls bazel-bin/tests/eval/synthetic/state-leak/e1_state_leak/
```
Expected: binary exists at `bazel-bin/tests/eval/synthetic/state-leak/e1_state_leak/e1_state_leak`.

- [ ] **Step 17.4: Validation walks the whole tree**

```bash
PYTHONPATH=src/python python3 -c "
from pathlib import Path
from gpa.eval.scenario_metadata import validate_all
errs = validate_all(Path('tests/eval'))
print(f'errors: {len(errs)}')
for e in errs[:10]: print(' ', e)
"
```
Expected: `errors: 0`.

- [ ] **Step 17.5: Index renders**

```bash
PYTHONPATH=src/python python3 -m gpa.eval.index_cli index --by taxonomy --root tests/eval
```
Expected: a markdown table summarizing the 198 scenarios across categories.

- [ ] **Step 17.6: Counts match**

```bash
find tests/eval -name scenario.md | wc -l
cat /tmp/pre_migration_count.txt
```
Expected: equal.

---

## Plan Verification Checklist

Before considering implementation complete, confirm:

- [ ] Every leaf has both `scenario.md` and `scenario.yaml`.
- [ ] Every leaf with `*.c` files has a `BUILD.bazel`.
- [ ] `validate_all` returns zero errors.
- [ ] `bazel build //tests/eval/...` succeeds.
- [ ] `git log --follow` works on a sampled scenario.
- [ ] No file under `docs/`, `scripts/`, or `CLAUDE.md` references the old flat path layout.
- [ ] `gpa.eval.curation.draft.DraftLib` writes new mined scenarios into the new layout (driven by an integration test or a manual mining run).
- [ ] `pre_migration_count == post_migration_count`.

---

## References

- @superpowers:test-driven-development
- @superpowers:verification-before-completion
- @superpowers:subagent-driven-development
- Spec: `docs/superpowers/specs/2026-05-02-eval-scenario-taxonomy-layout-design.md`
