# Eval Lessons — Mining Pipeline (codex round, 2026-05-04)

**TL;DR.** The 14 codex-mined scenarios were mis-classified because `bug_class` is decided by a brittle regex (`infer_bug_class` in `rules.py`) — not by the LLM `Triage` class, which `run.py` never calls. `fix.files` is the raw `gh api .../pulls/N/files` list with only test/docs basename filtering, so it inherits the entire PR file set including refactor collateral, header pairs, and Cesium's `Spec.js` test files (filter only catches `.spec.js`, not `Spec.js`). Fixes below land in `rules.py`, `extract_draft.py`, and `mining_rules.yaml`.

## Mis-classification root cause

Decision lives in `src/python/gpa/eval/curation/rules.py:313–343` (`infer_bug_class`):

```python
if source_type == "stackoverflow" or app_side:
    return "user-config" if config else "consumer-misuse"
...
if category == "framework-maintenance":
    if "reason:not_planned" in str(url) and app_side:
        return "consumer-misuse"
    return "framework-internal"
```

Where `app_side` is `re.search(app_resolution_re, text, IGNORECASE)`. The pattern is in `mining_rules.yaml:89`:

```yaml
app_resolution: "\\baccepted answer|use |set |enable |disable |configure |workaround|not a bug|works as expected|by design\\b"
```

The literals `use `, `set `, `enable `, `disable `, `configure ` (with trailing space, no word-boundary on the right) match almost any English issue body. Concrete failures from the 14 scenarios:

- godot `4_2_world_environment_glow_eff` — body says "**Enable** Glow", "you just had to add the World Environment **change** Background to Canvas". Hits `enable `. Result: `bug_class=user-config`. Actual fix: 13 files in `servers/rendering/renderer_rd/...` (framework-internal).
- maplibre `3d_terrain_with_partially_tran` — body says "**Use** a custom 3D terrain source", "**Use** a custom raster background". Hits `use `. Result: `bug_class=consumer-misuse`. Actual fix: `src/render/draw_fill.ts`, `src/render/draw_line.ts`, `src/render/painter.ts` (framework-internal).

`run.py:624` wires this guess straight through (`draft.extras["bug_class"] = rec.bug_class_guess`) and `_draft_to_files` (`run.py:416`) writes it to `scenario.md` with no override. The LLM `Triage` class in `triage.py` (which has a strong rule-of-thumb for framework repos at `prompts/triage_system.md:25`) is **never invoked** by the orchestrator — `run.py` has no `Triage(...)` instantiation. So all "the triager classifies bug_class" prompt logic is dead code on this path.

## Bloated `fix.files` root cause

Population is two-step. `_fetch_fix_pr_metadata` at `run.py:340–344` runs:

```python
gh api repos/{owner}/{repo}/pulls/{num}/files
```

and stores the raw list under `fix_pr["files_changed"]`. Then `extract_draft.py:107–165` (`_filter_source_files`) runs a basename + path-segment filter:

- Excludes path segments: `tests`, `test`, `__tests__`, `docs`, `examples`, `example`, `fixtures`, `fixture`.
- Excludes basenames: `package.json`, lock files.
- Excludes basenames where `stem.endswith("_test")`, `stem.startswith("test_")`, `.test.` in base, `.spec.` in base.

Two gaps explain the bloat in this round:

1. **Cesium uses `Specs/` (capitalized) and `BufferSpec.js` naming** — Jasmine convention, not Vitest. The filter checks `.spec.` (lowercase, with leading dot) but the file's lowercased basename is `bufferspec.js`. No `tests/` segment either. Result: `packages/engine/Specs/Renderer/BufferSpec.js`, `ContextSpec.js`, `SyncSpec.js`, `PickingSpec.js`, `SceneSpec.js` all kept (extract_draft.py:158–162).
2. **No "core fix file" detection.** Godot PRs touch header+impl pairs (`render_forward_mobile.h`, `.cpp`), shader includes (`*_inc.glsl`), and unrelated callsites swept up by a refactor. The filter is only test/docs — there is no signal for "which file actually contains the bugfix diff". For the world_environment_glow scenario, `expected_files` ends up with 13 entries.

Result: `expected_files` mirrors the PR file list, gt cardinality blows up to 13–22 for godot, and any code-location scorer dividing matches/total tanks recall.

## Recommendations (P0/P1/P2 priority)

### P0 — Re-route bug_class through the LLM triager

`run.py:_run_produce` should invoke the existing `Triage` class on the `IssueThread` and use its `bug_class` (overriding `rec.bug_class_guess`). The LLM triager already has the right rule of thumb (`prompts/triage_system.md:25`: "if the issue URL is `github.com/<framework-org>/<framework-repo>/issues/N`, the default classification is `framework-internal`"). Concretely add after `run.py:622`:

```python
triage = self._triage.triage(thread)  # already exists in deleted path
if triage.bug_class:
    draft.extras["bug_class"] = triage.bug_class
else:
    draft.extras["bug_class"] = rec.bug_class_guess
```

This fixes the 14 mis-labels at the cost of one LLM call per drafted candidate.

### P0 — Default framework-repo issues to `framework-internal`, not regex

In `rules.py:313`, replace the order so URL-based framework detection wins over the `app_side` regex:

```python
def infer_bug_class(category, source_type, text, url, rules):
    if category == "graphics-lib-dev":
        return "graphics-lib-dev"
    # NEW: framework-repo URLs default to framework-internal regardless
    # of body keywords. Override only via a hard signal (see P1).
    if category == "framework-maintenance":
        if "reason:not_planned" in str(url):
            return "consumer-misuse"
        return "framework-internal"
    # SO + framework-app-dev paths keep the existing app/config split.
    ...
```

Removes the false positives from `app_resolution`/`config_terms` matching innocent words like "Use" and "Enable".

### P1 — Tighten `app_resolution` regex

`mining_rules.yaml:89` has bare `use `, `set `, `enable ` etc. that match prose. Replace with anchored maintainer-resolution phrasing:

```yaml
app_resolution: "(?i)\\b(accepted answer|works as designed|works as expected|not a bug|by design|won.?t fix|wontfix|user error|use the (\\w+) (api|prop|option) instead|you should (use|set|enable|disable|configure)|please (use|set|enable|disable|configure))\\b"
```

Requires the keyword to appear in maintainer-response phrasing, not random user-report prose. Keeps the `consumer-misuse` signal where it's real.

### P1 — Filter `fix.files` to bug-touching files via diff inspection

`extract_draft.py:_filter_source_files` only sees filenames. Switch to using the diff stats already returned by the GitHub PR-files endpoint (`additions`, `deletions`, `patch`) and prefer files with substantive diffs. In `run.py:357` change:

```python
"files_changed": [f.get("filename") for f in files if f.get("filename")],
```

to keep the full file objects, and in `extract_draft.py` rank by `additions+deletions` and **cap at 5 unless the PR itself has ≤3 files**. This drops Godot's collateral (header pairs, ancillary `*_inc.glsl` includes) without needing a new ML model.

### P1 — Add `Spec.js`/`Specs/` filters

`extract_draft.py:123–162`. Add `"specs"` to `excluded_segments` and add a regex `re.search(r"spec\.(js|ts)$", base)` (case-insensitive) so `BufferSpec.js`, `ContextSpec.js` are dropped. One-liner:

```python
if re.search(r"(?i)spec\.(js|ts|tsx)$", base):
    continue
```

### P2 — Sanity-check `bug_class` against `fix.files` paths

After draft assembly, re-classify: if every entry in `fix.files` lives under the framework's repo source root (not under `examples/`, `docs/`, `tests/`, `Specs/`), force `bug_class=framework-internal`. Add to `_draft_to_files` (`run.py:416`):

```python
if all(_is_framework_source_path(f) for f in draft.expected_files):
    bug_class = "framework-internal"
```

Belt-and-suspenders against any remaining triager mistakes; ground truth from the diff overrides body-text heuristics.

---

**Files referenced.** `src/python/gpa/eval/curation/rules.py:313` (infer_bug_class), `src/python/gpa/eval/curation/run.py:277,340,416,624` (fetch + bug_class wiring), `src/python/gpa/eval/curation/extract_draft.py:107–165` (file filter), `src/python/gpa/eval/curation/mining_rules.yaml:89-91` (regex patterns), `src/python/gpa/eval/curation/triage.py:164–211` (LLM Triage class, currently uncalled by run.py), `src/python/gpa/eval/curation/prompts/triage_system.md:19–26` (bug_class rubric).
