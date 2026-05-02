# R14: Bevy child text fails to render after toggling between menus

## User Report

Bevy 0.16.0-rc.2, Windows 11, NVIDIA RTX 3060, Vulkan.

I have two menus, A and B. Each menu is spawned as a UI tree under a
common menu root. A button toggles between them by despawning one
subtree and spawning the other.

Click "Menu A" and "Menu B" repeatedly to add and remove the entities
and observe that the text in Menu B sometimes fails to render.

The buttons themselves are visible — only the text labels inside the
B menu's children disappear. The same code path that works on the
first navigation breaks on subsequent navigations.

This was as minimal as I could get it; the full app shows the same
problem.

## Expected Correct Output

When clicking back to a menu state that was previously visible, the
text content should re-render with the same appearance and layout
as the first time it was shown.

## Actual Broken Output

After enough toggles, the text glyphs no longer appear inside the
B-menu's panel. The panel itself is still drawn (and is the right
colour and size); the text quads inside it are missing. The bug is
intermittent — it does not fire on every toggle, but it fires
reliably eventually.

## Ground Truth

Per the fix PR ("Remove the `visited` local system param from
`update_ui_context_system`."):

The UI tree update system uses a depth-first traversal to assign
each UI node a "context" handle (which window/camera it belongs
to). The traversal cached visited entities in a `Local` system
param to avoid re-walking the same node twice. When an entity was
despawned and a new entity reused the same `Entity` index, the
`visited` set still contained the old entry, so the new entity
was treated as already-visited and its context was never
assigned. Without a context, the text glyph extraction skipped
those entities entirely.

The fix removes the `visited` local cache, so every traversal
starts from a clean state and reused `Entity` indices are no
longer mistaken for already-visited entities.

## Fix
```yaml
fix_pr_url: https://github.com/bevyengine/bevy/pull/18664
fix_sha: 17435c711846b43119b3f00e382d4c3daf38c818
fix_parent_sha: 9daf4e7c8b69b6f65dde755975074aa5755cc72d
bug_class: framework-internal
framework: bevy
framework_version: 0.16.0-rc.2
files:
  - crates/bevy_ui/src/update.rs
change_summary: >
  The UI context-assignment traversal cached visited entity IDs in
  a Local, which retained entries from despawned entities. When
  Entity indices were reused, the new entity was wrongly skipped,
  leaving its UI context unassigned and its text glyphs unextracted.
  Removing the cache makes the traversal idempotent and correct
  under entity reuse.
```

## Upstream Snapshot
- **Repo**: https://github.com/bevyengine/bevy
- **SHA**: 9daf4e7c8b69b6f65dde755975074aa5755cc72d
- **Relevant Files**:
  - crates/bevy_ui/src/update.rs

## Flywheel Cell
primary: framework-maintenance.game-engine.code-navigation
secondary:
  - framework-maintenance.game-engine.captured-text-glyph-trace

## Difficulty Rating
4/5

## Adversarial Principles
- visual-symptom-only-user-report
- intermittent-bug-tied-to-entity-id-reuse
- bug-is-stale-state-in-system-local-not-in-the-data

## How OpenGPA Helps

A frame capture on a broken navigation shows zero text-glyph quads
for Menu B's children, while the panel rectangle still draws. The
captured glyph atlas is loaded but no draw call samples it for the
B-menu's content. That isolation — "the text glyph atlas exists
and is bound, but no draw call reads from it for the affected
entities" — points at extract/queue logic for those particular
entities, narrowing the search to UI traversal.

## Source
- **URL**: https://github.com/bevyengine/bevy/issues/18616
- **Type**: issue
- **Date**: 2025-03-30
- **Commit SHA**: 17435c711846b43119b3f00e382d4c3daf38c818
- **Attribution**: Reported in issue #18616; fix in PR #18664.

## Tier
visual-only

## API
vulkan

## Framework
bevy

## Bug Signature
```yaml
type: code_location
spec:
  expected_files:
    - crates/bevy_ui/src/update.rs
  fix_commit: 17435c711846b43119b3f00e382d4c3daf38c818
```

## Predicted OpenGPA Helpfulness
- **Verdict**: yes
- **Reasoning**: The user report names "menu" and "text" but not
  any UI subsystem. Grep on "text" returns dozens of files;
  "menu" returns user examples. The bug is in UI traversal —
  three folders away. Capture-driven evidence ("text quads not
  drawn for these entities even though the atlas is bound") is
  necessary to localize the bug to UI traversal rather than to
  text rendering or font handling.

## Observed OpenGPA Helpfulness
- **Verdict**: ambiguous
- **Evidence**: validation pending — code_only baseline not yet run.
