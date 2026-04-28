# Plugin-agnostic GPA core (Phase 1)

*Spec for round 13. 2026-04-28.*

## Motivation

A surface audit of the recently-shipped CLI / MCP / REST / ranker code
revealed four code-level couplings between **GPA core** and **specific
framework plugins** (three.js / mapbox / PIXI / WebGL). The user-facing
principle behind this round:

> "We should not make commands specific to certain backend/plugin (e.g.,
> JS..)."

Today GPA cleanly separates:

- **Backends** (capture sources): `FrameProvider` ABC abstracts native /
  renderdoc / future Vulkan layer.
- **Plugins** (Tier-3 framework metadata sources): plugins POST scene
  graph + render config to `/frames/{id}/annotations`, namespaced by
  plugin name.

But GPA core code has accreted framework-specific knowledge **outside**
those boundaries:

| # | Site | Coupling |
|---|------|----------|
| 1 | `src/python/gpa/api/trace_ranking.py:35-47` | `FRAMEWORK_HINT_PATTERNS` regex allowlist (`THREE.uniforms.*`, `map._transform.*`, `app.stage.*`) bumps confidence tier on framework-shaped paths |
| 2 | `src/python/gpa/cli/main.py:283-284` | `gpa trace value` help text: *"Requires the WebGL shim (gpa-trace.js)"* — implies WebGL-only when native DWARF backend also feeds the same endpoint |
| 3 | `src/python/gpa/mcp/server.py:189, 237` | MCP `gpa_trace_value` description mirrors the WebGL-only claim and gives JS-specific examples (mapbox tile cache) |
| 4 | `src/python/gpa/cli/commands/scene_find.py:83, 183` | CLI Examples block + error hint cite `src/python/gpa/framework/threejs_link_plugin.js` by name |

Phase 1 (this spec) removes the four couplings. Phase 2 (deferred) will
design a formal plugin manifest contract — but only after ≥ 2 plugin
reference implementations exist (currently only `threejs_link_plugin.js`
is shipped, so the manifest would over-fit to three.js idioms).

## Scope

In scope:

1. Drop `FRAMEWORK_HINT_PATTERNS` allowlist + the helpers that consume
   it (`_framework_bump`, `_apply_bump`).
2. Rewrite four user-facing strings (CLI help, MCP description × 2,
   scene-find Examples + error hint) to be backend/plugin-neutral.
3. Replace 5 obsolete framework-hint tests in `test_trace_ranking.py`
   with one structural-neutrality regression test.

Out of scope (Phase 2 / future rounds):

- Plugin manifest schema (`framework_id`, `app_visible_paths`,
  `noisy_paths`, etc.).
- Reintroducing ranker hints sourced from manifest.
- Backend abstraction extension for non-GL APIs (Vulkan, WebGPU, Metal).
- Plugin discovery / registration endpoint.

## Design

### 1. Trace ranker — drop the framework allowlist

Today `rank_candidates()` applies three signals in order:

1. **Hop distance** — fewer dots in the path → shorter sort key.
2. **Value rarity** — count of distinct paths holding the value across
   recent frames; rare → upgrade tier, common → downgrade.
3. **Framework hints** — regex match against `FRAMEWORK_HINT_PATTERNS`
   → tier bump.

After Phase 1, signal #3 is removed. The ranker uses signals 1 + 2 only
— purely structural, framework-agnostic.

**Code changes** in `src/python/gpa/api/trace_ranking.py`:

- Delete constant `FRAMEWORK_HINT_PATTERNS` (lines 35-47).
- Delete helper `_framework_bump(path)` (lines 70-75).
- Delete helper `_apply_bump(tier, bump)` (lines 104-112).
- Drop `tier = _apply_bump(tier, _framework_bump(path))` in
  `rank_candidates` (line 163).
- Update module docstring (lines 1-20): replace "three signals" with
  "two signals"; remove signal #3 paragraph.

**Behavioral impact.** Paths matching the deleted patterns previously
got a +1 tier bump; they now keep their raw tier. All other behavior
(tier ordering, rarity, sort key) is unchanged.

**Eval evidence the precision loss is acceptable.** Across R10v2+R11,
trace was invoked 2/33 times (haiku-only), and the one successful
trace-driven solve (R9 r53) succeeded via path-name `query=intensity`,
not via a `THREE.` regex match. Real-world cost ≈ 0.

### 2. CLI / MCP help text — neutral framing

| Site | Before | After |
|------|--------|-------|
| `cli/main.py:283-284` | "Requires the WebGL shim (gpa-trace.js) to be enabled in the target." | "Requires a value scanner (native DWARF symbols or WebGL Tier-3 SDK) to be active in the target." |
| `mcp/server.py:189` | "for JS-layer state upstream of GL calls (e.g. mapbox tile cache, …)" | "for app-level state upstream of the GL/WebGL/Vulkan call site." |
| `mcp/server.py:237` | "Requires the WebGL gpa-trace shim to have been enabled in the …" | "Requires a value scanner (native DWARF symbols or WebGL Tier-3 SDK) to be active in the target." |

### 3. Scene-find — drop plugin-name cite

Both `cli/commands/scene_find.py:83` (Examples block) and `:183` (error
hint) currently cite `src/python/gpa/framework/threejs_link_plugin.js`
by name. After Phase 1, both point at the spec doc instead:

> See `docs/superpowers/specs/2026-04-18-framework-integration-design.md`
> for the Tier-3 plugin contract.

This keeps the Examples block useful (an agent can follow the link) but
doesn't bake the three.js plugin name into the CLI surface.

### 4. Tests

`tests/unit/python/test_trace_ranking.py` currently has six tests
covering the now-deleted framework-hint logic:

| Test | Disposition |
|------|-------------|
| `test_framework_hint_boosts_low_to_medium` | Delete |
| `test_framework_hint_boosts_medium_to_high` | Delete |
| `test_framework_hint_preserves_high` | Delete |
| `test_non_hint_path_gets_no_bump` | Delete (no longer meaningful — *every* path gets no bump) |
| `test_framework_hint_list_is_nonempty_and_documented` | Delete (asserts the allowlist exists) |
| `test_raw_confidence_preserved` | Rewrite — remove the framework-hint half of the assertion; keep the rarity half |

Add one new test: `test_no_framework_specific_bump` — feed three paths
shaped like `THREE.uniforms.x.value`, `map._transform.x`, and
`random.path.x` to `rank_candidates()` with identical raw confidence
and verify all three end up with the **same** tier (no framework path
gets a structural bump).

## Migration

No public-API break. `rank_candidates()` signature, return shape, and
field names (`confidence`, `raw_confidence`, `distance_hops`) stay
stable. Only the tier values for framework-shaped paths shift downward
by one.

## Acceptance

- All five fixes land in a single PR.
- `tests/unit/python/test_trace_ranking.py` passes with the new test
  set.
- Full Python unit test suite (`pytest tests/unit/python/`) is green.
- `git grep -i "three\|threejs\|mapbox\|babylon\|webgl"` over
  `src/python/gpa/cli/`, `src/python/gpa/mcp/`, `src/python/gpa/api/`
  surfaces no remaining framework references in user-facing strings or
  ranking logic. (Code comments referring to specific frameworks as
  illustrative examples are allowed; they're explanatory, not
  load-bearing.)

## Net diff estimate

~50 LoC removed, ~15 LoC added (one replacement test + neutral text).
5 source files + 1 test file touched.

## References

- Audit findings: conversation context, this round.
- `src/python/gpa/api/trace_ranking.py` — current ranker logic.
- `tests/unit/python/test_trace_ranking.py` — existing test coverage.
- `docs/superpowers/specs/2026-04-18-framework-integration-design.md` —
  Tier-3 plugin contract (current).
- `docs/superpowers/specs/2026-04-20-gpa-trace-design.md` — trace
  endpoint design.
