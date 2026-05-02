# Eval Scenario Taxonomy Layout — Design

**Status**: Draft
**Date**: 2026-05-02
**Author**: jingyu
**Supersedes (partial)**: `2026-04-17-eval-set-real-world-design.md` (layout sections only)

## Problem

`tests/eval/` holds 198 scenarios spanning three naming generations:

- `e1..e33` — synthetic, hand-authored, with `main.c` + `scenario.md`.
- `r1..r24_<slug>` — early mined real-world bugs (only `scenario.md`).
- `r{sha}_{category}_{framework}_{slug}` — recent mined (`r96fdc7`, `rc2487a`,
  `ra21d3d`); the taxonomy is encoded in the folder name.

The flat folder is hard to navigate, the round-prefix names mix provenance
metadata with structural metadata, and there is no machine-readable index that
covers all scenarios. Consumers (mining pipeline, eval harness, docs, scripts)
each invent their own path conventions.

## Goals

1. Browse scenarios by taxonomy (category/framework) without grepping names.
2. Move provenance/round info into per-scenario metadata so the folder name
   only carries identity.
3. Make taxonomy + backend + status machine-queryable for index reports.
4. Atomic migration: one commit moves all 198 scenarios; downstream consumers
   are updated in the same PR.

## Non-Goals

1. Re-classifying or re-curating existing scenarios. Migration uses whatever
   taxonomy the existing folder name or scenario text already implies.
2. Adding new mining sources or rewriting `mining_rules.yaml`.
3. Defining a new bug_class taxonomy. The existing values
   (`framework-internal | consumer-misuse | user-config`) carry over unchanged.
4. Reproducing scenarios that have only `scenario.md` (no `.c`).

## Folder Layout

```
tests/eval/
├── BUILD.bazel                       # rewritten: globs **/scenario.md, leaf targets
├── README.md                          # rewritten for new layout
├── synthetic/                         # hand-authored scenarios (e1..e33)
│   ├── state-leak/
│   │   └── e1_state_leak/
│   │       ├── BUILD.bazel
│   │       ├── scenario.md
│   │       ├── scenario.yaml
│   │       └── main.c
│   ├── uniform/...
│   ├── depth/...
│   ├── culling/...
│   ├── stencil/...
│   ├── nan/...
│   └── misc/...
├── native-engine/
│   ├── godot/
│   │   └── godot_86493_world_environment_glow/
│   │       ├── scenario.md
│   │       └── scenario.yaml
│   └── bevy/...
├── web-3d/
│   ├── three.js/
│   │   ├── threejs_29841_<slug>/
│   │   └── so_23460040_effectcomposer_resize/    # StackOverflow source
│   ├── babylon.js/...
│   ├── playcanvas/...
│   ├── react-three-fiber/...
│   └── postprocessing/...
├── web-2d/
│   ├── pixijs/...
│   └── konva/...
├── web-map/
│   ├── mapbox-gl-js/...
│   ├── maplibre-gl-js/...
│   ├── deck.gl/...
│   └── cesium/...
├── scientific/
│   ├── vtk-js/...
│   └── gltf-sample-viewer/...
└── _legacy/                           # only when source url cannot be recovered
    └── legacy_r{N}_<slug>/...
```

### Why two-level for mined / parallel `synthetic/<topic>/`

- 2-level (`<category>/<framework>/`) matches the existing
  `mining_rules.yaml` taxonomy 1:1, so the mining pipeline already has the
  data it needs.
- `bug_class` lives in `scenario.yaml`, not the folder tree. It is fuzzy
  (auto-classified, gets revised) and does not deserve a directory layer.
- Synthetic scenarios are not bound to a framework; they target capture
  failure modes. Their natural axis is topic (`state-leak`, `uniform`,
  `depth`, ...), already implicit in `e*` names.

### Slug rules

| Source | Slug form |
|---|---|
| GitHub issue | `<repo>_<issue-num>_<slug>` (e.g., `godot_86493_world_environment_glow`) |
| GitHub PR | `<repo>_pull_<num>_<slug>` |
| StackOverflow | `so_<question-id>_<slug>` |
| Synthetic | `e{N}_<slug>` (preserves existing `e1..e33` continuity) |
| Legacy fallback | `legacy_r{N}_<slug>` (under `_legacy/`, flat) |

`<repo>` is the repo basename, normalized for Bazel target rules: lowercase,
non-alphanumerics → `_` (e.g., `three.js` → `threejs`, `mapbox-gl-js` →
`mapbox_gl_js`). The same normalization applies wherever the slug is used as
a Bazel target name.

Conflicts: when two scenarios produce the same slug, the migration script
appends `_02`, `_03`, etc. The conflict list goes into the migration report
for review.

## `scenario.yaml` Schema

Every scenario directory contains both `scenario.md` (prose) and
`scenario.yaml` (metadata). Schema lives at
`src/python/gpa/eval/scenario_schema.json`.

```yaml
schema_version: 1
slug: godot_86493_world_environment_glow   # must match leaf folder name
round: r96fdc7                              # mining round id
mined_at: 2026-04-21                        # ISO date scenario was committed

source:
  type: github_issue                        # github_issue | github_pull |
                                            # stackoverflow | synthetic | legacy
  url: https://github.com/godotengine/godot/issues/86493
  repo: godotengine/godot                   # null for synthetic/stackoverflow/legacy
  issue_id: 86493                           # int (GH) | string (SO) | null

taxonomy:
  category: native-engine                   # closed list from mining_rules.yaml
  framework: godot                          # closed list from mining_rules.yaml
  bug_class: framework-internal             # framework-internal | consumer-misuse |
                                            # user-config | synthetic | unknown

backend:
  api: vulkan                               # opengl | vulkan | webgl | webgpu | unknown
  status: not-yet-reproduced                # reproduced | not-yet-reproduced | non-runnable

status: drafted                             # triaged | drafted | running | passing
tags: []
notes: ""
```

**Required**: `schema_version, slug, round, source.type, taxonomy.category,
taxonomy.framework, status`.

**Closed lists** (drift-resistant): `taxonomy.category` and
`taxonomy.framework` are validated against
`src/python/gpa/eval/curation/mining_rules.yaml` at load time. Adding a new
framework requires editing `mining_rules.yaml` first; the validator surfaces
the drift on the next CI run.

## Validation

New module `src/python/gpa/eval/scenario_metadata.py`:

```python
@dataclass
class Scenario:
    path: Path
    slug: str
    round: str
    source: Source
    taxonomy: Taxonomy
    backend: Backend
    status: str
    tags: list[str]
    notes: str

def load_scenario(path: Path) -> Scenario: ...
def iter_scenarios(root: Path) -> Iterator[Scenario]: ...
def validate_all(root: Path) -> list[ValidationError]: ...
```

Pytest test in `tests/unit/python/test_scenario_metadata.py` walks
`tests/eval/`, asserts every leaf has both files, schema validates, and
`slug` matches its parent folder name.

## Indexes

CLI subcommands (in a new `src/python/gpa/eval/index_cli.py`):

```
gpa-eval index --by taxonomy   # table: <category> × <framework>, count
gpa-eval index --by backend    # table: api × status
gpa-eval index --by round      # legacy view: scenarios per mining round
gpa-eval index --filter taxonomy.framework=godot,backend.api=vulkan
```

These render Markdown tables for piping into docs and JSON for tooling. They
are not committed to the repo (computed on demand).

## Migration Tool

New file `src/python/gpa/eval/migrate_layout.py`:

```
Inputs:
  --root tests/eval
  --rules src/python/gpa/eval/curation/mining_rules.yaml
  --overrides migration_overrides.yaml   # operator-edited
  --dry-run / --apply
  --report /tmp/migration.json

Pipeline (deterministic, idempotent):
  1. Walk tests/eval/, identify each leaf scenario dir.
  2. For each scenario, infer:
     - source.url:
         regex github\.com/([^/]+)/([^/]+)/(issues|pull)/(\d+)
         fallback regex stackoverflow\.com/questions/(\d+)
         fallback: source.type=legacy
     - taxonomy:
         (a) parse old folder name where r96fdc7_/rc2487a_ already encodes it
         (b) look up repo in mining_rules.yaml taxonomy.framework_repos
         (c) for e* scenarios: source.type=synthetic + topic prefix → bucket
         (d) operator override (migration_overrides.yaml) wins over (a)–(c)
     - round:  r{N} or r{sha} prefix from old folder name
     - slug:   per slug rules
  3. Conflict resolution:
     - Same slug twice → append _02, _03, ...
     - Unknown taxonomy → emit to migration_review.csv;
       operator fills overrides.yaml; re-run.
  4. Generate scenario.yaml (jinja template) and per-leaf BUILD.bazel
     (only when *.c files exist).
  5. git mv for moves (preserves blame). One commit.
  6. Post-checks:
     - File counts match (pre-move == post-move).
     - schema_validates_all() == [].
     - bazel query //tests/eval/... resolves.
     - git log --follow on a sample shows preserved history.
```

### Synthetic topic buckets

Derived from existing `e*` slug prefixes:

| Prefix in name | Bucket |
|---|---|
| `state_leak` / `state-leak` | `state-leak/` |
| `uniform_*` | `uniform/` |
| `depth_*`, `reversed_z`, `gldepthrange` | `depth/` |
| `culling_*` | `culling/` |
| `stencil_*` | `stencil/` |
| `nan_propagation` | `nan/` |
| Everything else (`compensating_vp`, `index_buffer_obo`, `double_negation_cull`, `shader_include_order`, `race_texture_upload`, `scissor_not_reset`) | `misc/` |

The mapping lives in `migrate_layout.py` as a small dict and is editable; new
synthetic topics added in the future register there before migration runs.

## BUILD.bazel Strategy

`tests/eval/BUILD.bazel` becomes a stub (or is deleted). Per-leaf
`BUILD.bazel` only exists when the leaf has at least one `.c` file:

```python
load("@rules_cc//cc:defs.bzl", "cc_binary")

cc_binary(
    name = "<leaf-slug>",
    srcs = glob(["*.c"]),
    copts = ["-g", "-gdwarf-4", "-fno-omit-frame-pointer", "-O0"],
    linkopts = ["-lGL", "-lX11", "-lm"],
    visibility = ["//visibility:public"],
)
```

Build invocation:

```
bazel build //tests/eval/synthetic/uniform/e5_uniform_collision
# or with explicit target:
bazel build //tests/eval/synthetic/uniform/e5_uniform_collision:e5_uniform_collision
```

Output binary lands at
`bazel-bin/tests/eval/synthetic/uniform/e5_uniform_collision/e5_uniform_collision`.

## Consumer Updates

The migration PR includes a separate commit per consumer:

| File | Change |
|---|---|
| `tests/eval/README.md` | Rewrite for new layout; describe `scenario.yaml`; explain topic buckets. |
| `scripts/run-eval-claude-code.sh` | Update example path. |
| `docs/gpa-trace-native-usage.md` | Update `bazel-bin/tests/eval/<name>` references. |
| `docs/eval-results.md` | Update `tests/eval/r15_*` references. |
| `docs/superpowers/specs/2026-04-17-eval-set-real-world-design.md` | "Superseded by this spec" pointer at top. |
| `docs/superpowers/specs/2026-04-28-omnispace-gen-integration-design.md` | Update `tests/eval/r37_joint_offset_smplx/` reference. |
| `src/python/gpa/eval/curation/draft.py` and `run.py` | New mined scenarios go to `<category>/<framework>/<slug>/` with `scenario.yaml`. |
| `src/python/gpa/eval/curation/journey.py` | Path constructions updated. |
| `CLAUDE.md` | Eval examples use new paths. |

## Forward-Going Mining Pipeline

Once the migration lands, `gpa.eval.curation.draft.DraftLib` writes new
scenarios directly to the new layout:

1. Triage already produces `(category, framework)` tuples.
2. `draft.py` constructs the slug from `(repo, issue_id, brief_slug)`.
3. Output path = `tests/eval/<category>/<framework>/<slug>/`.
4. Generates `scenario.md` (existing) + `scenario.yaml` (new) +
   `BUILD.bazel` (only if a `.c` is committed in the same draft).

The migration tool and the forward-going pipeline share the same slug + yaml
codegen helpers (in `scenario_metadata.py`).

## Risks

- **Bazel target name collisions**. Mitigated by leaf-name uniqueness check
  in the migration script (the slug includes a repo+issue_id discriminator
  for mined and `e{N}` for synthetic).
- **Lost blame on `git mv`** if the move is combined with edits. Mitigated:
  the migration commit is `git mv`-only (no content edits); a second commit
  adds `scenario.yaml` and `BUILD.bazel` files.
- **Stale references in third-party docs / external links**. Mitigated by
  keeping `_legacy/` paths stable for the small recoverable subset and
  surfacing the rename mapping in the migration report.
- **Mining pipeline regression** if `draft.py` is updated incorrectly.
  Mitigated by an integration test that drives a single mined scenario
  end-to-end into the new layout.

## Rollout Plan (commit sequence within one PR)

1. Add `scenario_metadata.py`, `scenario_schema.json`, and unit tests
   (validates against the *current* layout — passes with synthetic schemas
   inferred from folder names).
2. Add `migrate_layout.py` and dry-run report.
3. Operator reviews `migration_review.csv`, edits
   `migration_overrides.yaml`.
4. Run `migrate_layout.py --apply` (commits the moves only).
5. Add `scenario.yaml` + per-leaf `BUILD.bazel` files (one commit).
6. Rewrite `tests/eval/BUILD.bazel` and `tests/eval/README.md`.
7. Update each consumer file/script in its own commit.
8. Update `gpa.eval.curation.draft` to emit to the new layout.
9. CI gate: `bazel test //tests/...` and `pytest tests/unit/python/`.

## Open Questions

None at design time. All design choices were resolved in the brainstorming
session on 2026-05-02:

- Primary axis: taxonomy (category → framework).
- Tree depth: 2-level for mined, parallel `synthetic/<topic>/`.
- Metadata: separate `scenario.yaml`.
- Leaf slug: source-id-prefixed (`<repo>_<issue>_<slug>`,
  `so_<id>_<slug>`, `e{N}_<slug>`, `legacy_r{N}_<slug>`).
- Bazel: leaf-name target in per-leaf BUILD.bazel.
- Migration: big-bang automated migration in one PR.
