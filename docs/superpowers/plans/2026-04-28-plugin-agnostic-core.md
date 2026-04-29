# Plugin-agnostic GPA core (Phase 1) — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Remove four framework-specific couplings from GPA core (trace-ranker allowlist, two CLI/MCP help strings, scene-find plugin-name cite) so GPA core stays plugin-agnostic; defer the manifest contract to Phase 2.

**Architecture:** Pure deletion + neutral-rephrasing. The trace ranker drops signal #3 (regex allowlist) and runs on signals 1+2 (hop distance + value rarity) only. User-facing strings stop mentioning specific plugin names / file paths. No public API change; one new structural-neutrality regression test plus one rewritten test confirms behavior.

**Tech Stack:** Python 3.11, pytest. Touches `src/python/gpa/api/trace_ranking.py`, `src/python/gpa/cli/main.py`, `src/python/gpa/mcp/server.py`, `src/python/gpa/cli/commands/scene_find.py`, `tests/unit/python/test_trace_ranking.py`.

**Spec:** `docs/superpowers/specs/2026-04-28-plugin-agnostic-core-design.md`.

---

## File Structure

| File | Purpose | Change type |
|------|---------|-------------|
| `src/python/gpa/api/trace_ranking.py` | Confidence ranker for trace candidates | Modify — remove allowlist + 2 helpers; update docstring |
| `src/python/gpa/cli/main.py` | Top-level CLI parser config | Modify — neutral `gpa trace` help text |
| `src/python/gpa/mcp/server.py` | MCP tool registry | Modify — neutral `query_annotations` + `gpa_trace_value` descriptions |
| `src/python/gpa/cli/commands/scene_find.py` | `gpa scene-find` CLI command | Modify — drop plugin-name cite, point at spec doc |
| `tests/unit/python/test_trace_ranking.py` | Ranker unit tests | Modify — drop 5 tests, rewrite 1, update 1 comment, add 1 |

No new files; no file split needed (each touched file already has a single clear responsibility).

---

## Task 1: Drop framework-hint logic from the trace ranker

**Files:**
- Modify: `src/python/gpa/api/trace_ranking.py`
- Test: `tests/unit/python/test_trace_ranking.py`

This task removes the `FRAMEWORK_HINT_PATTERNS` regex allowlist + its two helpers (`_framework_bump`, `_apply_bump`) and updates the module docstring. Tests get reworked: 5 hint-specific tests deleted, 1 rewritten (`test_raw_confidence_preserved`), 1 comment-only update (`test_unique_rare_framework_path_beats_common_deep_path`), 1 new test added (`test_no_framework_specific_bump`), 1 import line removed.

The remaining ranking logic (hop count + rarity + sort) is untouched. Public API of `rank_candidates()` and `build_corpus_for_value()` is preserved.

- [ ] **Step 1: Write the new structural-neutrality test (failing)**

Add to `tests/unit/python/test_trace_ranking.py` (any place after the rarity tests, before the integration section is fine):

```python
def test_no_framework_specific_bump():
    """Three paths shaped like three.js / mapbox / unknown-framework patterns
    must end up with the same tier when they share raw confidence and hop
    distance — the ranker must not bump any of them on framework grounds."""
    cands = [
        {"path": "THREE.uniforms.uZoom.value", "confidence": "low"},
        {"path": "map._transform.zoom",       "confidence": "low"},
        {"path": "random.deep.value",         "confidence": "low"},
    ]
    out = rank_candidates(cands)
    tiers = {c["path"]: c["confidence"] for c in out}
    assert tiers["THREE.uniforms.uZoom.value"] == tiers["random.deep.value"]
    assert tiers["map._transform.zoom"]       == tiers["random.deep.value"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `PYTHONPATH=src/python python -m pytest tests/unit/python/test_trace_ranking.py::test_no_framework_specific_bump -v`

Expected: **FAIL** — the framework-shaped paths currently get bumped from "low" to "medium", so the equality assertion fails.

- [ ] **Step 3: Delete the framework-hint constants and helpers**

In `src/python/gpa/api/trace_ranking.py`, delete:

1. The `FRAMEWORK_HINT_PATTERNS` block (lines 27-47, the section header comment plus the constant definition).
2. The `_framework_bump` function (lines 70-75).
3. The `_apply_bump` function (lines 104-112).

Then in `rank_candidates` (currently around line 163) drop the line:

```python
        tier = _apply_bump(tier, _framework_bump(path))
```

The remaining body of the loop should look like:

```python
    enriched: List[Dict[str, Any]] = []
    for c in candidates:
        if not isinstance(c, dict) or "path" not in c:
            continue
        path = str(c["path"])
        raw_tier = str(c.get("confidence", "high")).lower()
        if raw_tier not in _TIER_ORDER:
            raw_tier = "high"
        tier = raw_tier
        if rarity_count is not None:
            tier = _apply_rarity(tier, rarity_count)
        entry = dict(c)
        entry["distance_hops"] = _hop_count(path)
        entry["confidence"] = tier
        entry["raw_confidence"] = raw_tier
        enriched.append(entry)
```

- [ ] **Step 4: Update the module docstring**

Replace lines 1-20 of `src/python/gpa/api/trace_ranking.py` with:

```python
"""Confidence ranking for ``gpa trace`` candidates (Phase 3).

The Phase-1 scanner writes candidates as ``{path, type, confidence}`` where
``confidence`` is a coarse "high" for non-trivial values and "low" for
trivial ones (0/1/""/true/false). This module re-scores and sorts
candidates at query time using two structural signals:

1. **Hop distance** — proxy for "closeness to the calling code". Counted
   as the number of ``.`` / ``[`` separators in the path minus one (the
   root itself is 0 hops). Fewer hops → stronger signal.
2. **Value rarity** — count how many distinct *paths* hold the observed
   value across the last N frames. Rare values (count == 1) upgrade to
   "high"; over-common values (count > 5) downgrade to "low".

Ranking order, stable sort: ``(confidence tier desc, hops asc, path_len asc)``.

Note: the ranker is intentionally framework-agnostic. Plugins that want
to elevate framework-specific paths should emit ``confidence: "high"``
from the scanner side; GPA core does not encode plugin-specific hints.
"""
```

- [ ] **Step 5: Drop the now-unused FRAMEWORK_HINT_PATTERNS import in tests**

Edit `tests/unit/python/test_trace_ranking.py:10-14`. Replace:

```python
from gpa.api.trace_ranking import (
    FRAMEWORK_HINT_PATTERNS,
    build_corpus_for_value,
    rank_candidates,
)
```

with:

```python
from gpa.api.trace_ranking import (
    build_corpus_for_value,
    rank_candidates,
)
```

- [ ] **Step 6: Delete five obsolete framework-hint tests**

Open `tests/unit/python/test_trace_ranking.py` and delete each of these test functions in full (find them by exact name; each is a small `def test_...` block plus a blank line separator):

- `test_framework_hint_boosts_low_to_medium` (around line 132)
- `test_framework_hint_boosts_medium_to_high` (around line 138)
- `test_framework_hint_preserves_high` (around line 144)
- `test_non_hint_path_gets_no_bump` (around line 150)
- `test_framework_hint_list_is_nonempty_and_documented` (around line 156)

You may also delete the section header comment block immediately above them (`# Framework-specific hints` block, around lines 127-130) since no remaining tests in that section.

- [ ] **Step 7: Rewrite `test_raw_confidence_preserved`**

Find the test (around line 161). Currently it asserts double promotion (rarity low→medium + hint medium→high). Rewrite to keep just the rarity half:

```python
def test_raw_confidence_preserved():
    cands = [{"path": "map._transform.zoom", "confidence": "low"}]
    out = rank_candidates(cands, corpus={"__count__": 1})
    # Single promotion: rarity (low → medium). No framework-hint bump exists.
    assert out[0]["raw_confidence"] == "low"
    assert out[0]["confidence"] == "medium"
```

- [ ] **Step 8: Update the integration test's inline comment**

Find `test_unique_rare_framework_path_beats_common_deep_path` (around line 174). The test body **does not change** — `map._transform._maxZoom` still wins on structural signals (shorter, fewer hops, unique under rarity). Only update the inline comment on line 182:

Before:
```python
    # Unique + high + framework hint + shallow → first.
```

After:
```python
    # Unique + high + shallow → first (no framework-specific bump anymore).
```

- [ ] **Step 9: Run the ranker test file**

Run: `PYTHONPATH=src/python python -m pytest tests/unit/python/test_trace_ranking.py -v`

Expected: all remaining tests **PASS**, including the new `test_no_framework_specific_bump` from Step 1. The five deleted tests should not appear in the report.

- [ ] **Step 10: Run the full Python test suite**

Run: `PYTHONPATH=src/python python -m pytest tests/unit/python/ -q`

Expected: green. Test count drops by 4 (deleted 5, added 1). Previous baseline was 1034; expect 1030 passing.

- [ ] **Step 11: Commit**

```bash
git add src/python/gpa/api/trace_ranking.py tests/unit/python/test_trace_ranking.py
git commit -m "$(cat <<'EOF'
refactor(api/trace): drop framework-hint allowlist from ranker (Phase 1)

GPA core no longer encodes regex prefixes for THREE.uniforms.*, map._transform.*, etc. The ranker now uses two structural signals only — hop distance + value rarity. Plugins that want to elevate framework-specific paths should emit confidence: "high" from the scanner side instead.

Tests: 5 hint-specific cases deleted, 1 rewritten to drop the bump assertion, 1 integration test gets a comment update (the framework path still wins on structural signals alone), 1 new structural-neutrality regression test added. FRAMEWORK_HINT_PATTERNS import dropped.

Refs: docs/superpowers/specs/2026-04-28-plugin-agnostic-core-design.md

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 2: Neutralize CLI `gpa trace` help text

**Files:**
- Modify: `src/python/gpa/cli/main.py:280-286`

The `gpa trace` parser's help string mentions only the WebGL shim, but the trace endpoints serve **both** native (DWARF) and WebGL scanners. This task makes the help string neutral.

- [ ] **Step 1: Apply the edit**

In `src/python/gpa/cli/main.py`, around line 280, replace:

```python
    p_trace = sub.add_parser(
        "trace",
        help=(
            "Reverse-lookup a captured value → app-level JS fields that hold it. "
            "Requires the WebGL shim (gpa-trace.js) to be enabled in the target."
        ),
    )
```

with:

```python
    p_trace = sub.add_parser(
        "trace",
        help=(
            "Reverse-lookup a captured value → app-level fields that hold it. "
            "Requires a value scanner (native DWARF symbols or WebGL Tier-3 "
            "SDK) to be active in the target."
        ),
    )
```

- [ ] **Step 2: Verify CLI help still renders**

Run: `PYTHONPATH=src/python python -m gpa trace --help 2>&1 | head -5`

Expected: First line of help shows `Reverse-lookup a captured value → app-level fields that hold it.` (no mention of "JS" or "gpa-trace.js"). Exit cleanly.

- [ ] **Step 3: Confirm the `--help` smoke tests still pass**

Run: `PYTHONPATH=src/python python -m pytest tests/unit/python/test_cli_examples_blocks.py -v`

Expected: all 16 cases **PASS**. No test references the old wording.

- [ ] **Step 4: Commit**

```bash
git add src/python/gpa/cli/main.py
git commit -m "$(cat <<'EOF'
docs(cli): neutralize gpa trace help — both native + WebGL backends supported

Refs: docs/superpowers/specs/2026-04-28-plugin-agnostic-core-design.md

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 3: Neutralize MCP `query_annotations` + `gpa_trace_value` descriptions

**Files:**
- Modify: `src/python/gpa/mcp/server.py` (two description blocks around lines 185-200 and 230-240)

Two MCP tool descriptions name specific frameworks ("mapbox tile cache") or hardcode WebGL-only assumptions. This task makes them backend/framework-neutral.

- [ ] **Step 1: Edit `query_annotations` description**

In `src/python/gpa/mcp/server.py`, around line 186-191, replace:

```python
        "description": (
            "Return free-form framework annotations for a frame (POSTed by a "
            "plugin as a JSON dict). Empty dict if nothing was posted. Useful "
            "for JS-layer state upstream of GL calls (e.g. mapbox tile cache, "
            "current zoom level)."
        ),
```

with:

```python
        "description": (
            "Return free-form framework annotations for a frame (POSTed by a "
            "Tier-3 plugin as a JSON dict). Empty dict if nothing was posted. "
            "Useful for app-level state (scene graph, materials, render config) "
            "upstream of the GL/WebGL/Vulkan call site."
        ),
```

- [ ] **Step 2: Edit `gpa_trace_value` description**

In `src/python/gpa/mcp/server.py`, around line 232-239, replace:

```python
        "description": (
            "Reverse-lookup app-level fields whose value matches a captured "
            "uniform / texture ID / literal. Answers 'where in the framework "
            "state did this value come from?' Useful when a uniform looks "
            "wrong and you need to find the deeper field that set it. "
            "Requires the WebGL gpa-trace shim to have been enabled in the "
            "target page."
        ),
```

with:

```python
        "description": (
            "Reverse-lookup app-level fields whose value matches a captured "
            "uniform / texture ID / literal. Answers 'where in the framework "
            "state did this value come from?' Useful when a uniform looks "
            "wrong and you need to find the deeper field that set it. "
            "Requires a value scanner (native DWARF symbols or WebGL Tier-3 "
            "SDK) to be active in the target."
        ),
```

- [ ] **Step 3: Run MCP server tests**

Run: `PYTHONPATH=src/python python -m pytest tests/unit/python/test_mcp_server.py -v`

Expected: all tests **PASS** (the descriptions aren't asserted on in unit tests, so behavior is unchanged).

- [ ] **Step 4: Run the full Python test suite**

Run: `PYTHONPATH=src/python python -m pytest tests/unit/python/ -q`

Expected: green. Same count as after Task 1.

- [ ] **Step 5: Commit**

```bash
git add src/python/gpa/mcp/server.py
git commit -m "$(cat <<'EOF'
docs(mcp): neutralize query_annotations + gpa_trace_value descriptions

Drops "JS-layer state … mapbox tile cache" and the WebGL-only requirement note from gpa_trace_value (native DWARF backend feeds the same endpoint).

Refs: docs/superpowers/specs/2026-04-28-plugin-agnostic-core-design.md

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 4: Drop plugin-name cite from `gpa scene-find`

**Files:**
- Modify: `src/python/gpa/cli/commands/scene_find.py:80-87` and `:178-186`

Two strings (Examples-block fallback message + error hint) name `src/python/gpa/framework/threejs_link_plugin.js` directly. After this task, both point at the spec doc instead.

- [ ] **Step 1: Edit the empty-result fallback message**

In `src/python/gpa/cli/commands/scene_find.py`, around line 80-84, replace:

```python
        if not payload.get("annotation_present"):
            lines.append(
                "(no scene-graph annotation found — install a Tier-3 plugin "
                "such as src/python/gpa/framework/threejs_link_plugin.js)"
            )
```

with:

```python
        if not payload.get("annotation_present"):
            lines.append(
                "(no scene-graph annotation found — install a Tier-3 plugin; "
                "see docs/superpowers/specs/"
                "2026-04-18-framework-integration-design.md)"
            )
```

- [ ] **Step 2: Edit the missing-annotation error hint**

In `src/python/gpa/cli/commands/scene_find.py`, around line 180-185, replace:

```python
        print(
            f"[gpa] no scene-graph annotation for frame {payload.get('frame_id')}"
            " — need a Tier-3 plugin. See "
            "src/python/gpa/framework/threejs_link_plugin.js for a sketch.",
            file=sys.stderr,
        )
```

with:

```python
        print(
            f"[gpa] no scene-graph annotation for frame {payload.get('frame_id')}"
            " — need a Tier-3 plugin. See "
            "docs/superpowers/specs/"
            "2026-04-18-framework-integration-design.md.",
            file=sys.stderr,
        )
```

- [ ] **Step 3: Confirm the spec doc the new strings reference exists**

Run: `ls docs/superpowers/specs/2026-04-18-framework-integration-design.md`

Expected: the file exists. (Recorded in `docs/flywheel-matrix.md` as the Tier-3 plan.)

- [ ] **Step 4: Run scene-find tests**

Run: `PYTHONPATH=src/python python -m pytest tests/unit/python/test_cli_scene_find.py tests/unit/python/test_api_scene_find.py -v 2>&1 | tail -15`

Expected: all tests **PASS**. (If a test hard-codes the old wording it will fail; in that case update the assertion to match the new neutral wording.)

- [ ] **Step 5: Run the full Python test suite**

Run: `PYTHONPATH=src/python python -m pytest tests/unit/python/ -q`

Expected: green.

- [ ] **Step 6: Commit**

```bash
git add src/python/gpa/cli/commands/scene_find.py
git commit -m "$(cat <<'EOF'
docs(cli/scene-find): point at Tier-3 spec instead of threejs_link_plugin.js

Two user-facing strings (empty-result fallback + missing-annotation error hint) named the three.js plugin file by path. They now point at the framework-integration spec, keeping the message useful without baking a specific plugin name into GPA core.

Refs: docs/superpowers/specs/2026-04-28-plugin-agnostic-core-design.md

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 5: Acceptance grep + final test sweep

**Files:** none modified (verification only).

Confirms the spec's acceptance criteria from `docs/superpowers/specs/2026-04-28-plugin-agnostic-core-design.md` § Acceptance hold post-implementation.

- [ ] **Step 1: Run the spec's precise acceptance grep**

Run:

```bash
git grep -E '\bgpa-trace\.js\b|\bthreejs_link_plugin\b|\bmapbox tile cache\b|\bTHREE\.uniforms\b|\bmap\._transform\b|\bapp\.stage\b' \
    -- 'src/python/gpa/cli/' 'src/python/gpa/mcp/' 'src/python/gpa/api/'
```

Expected: **zero output, exit code 1** (`git grep` returns 1 when no matches). If anything matches, that file still has a framework-specific reference and Task 1-4 missed it — go back and fix.

- [ ] **Step 2: Confirm full unit test suite is green**

Run: `PYTHONPATH=src/python python -m pytest tests/unit/python/ -q 2>&1 | tail -5`

Expected: green. Final pass count should be `1030 passed` (was 1034 pre-Task-1; -5 deleted, +1 added).

- [ ] **Step 3: No commit**

This task is verification-only.

---

## Done condition

- All five tasks checked off.
- Acceptance grep returns zero matches.
- Full Python test suite green.
- Five focused commits on the branch (one per task except the verification task), each referencing the spec.
