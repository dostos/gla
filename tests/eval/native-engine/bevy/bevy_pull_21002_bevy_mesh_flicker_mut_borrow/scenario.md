# R14: Bevy mesh flickers when getting a mutable borrow from the asset store

## User Report

I upgraded from Bevy 0.15 to 0.16. This worked without flicker before.

I wrote a clustered terrain generator for a strategy game. The terrain
can be changed during gameplay. After a cluster has been updated, I
retrieve the meshes of the adjacent terrain clusters to average the
normals at the borders between the clusters.

Starting with 0.16, just retrieving the mesh — independent of whether
I change the mesh or not — by

```rust
if let Some(other_mesh) = meshes.get_mut(other_mesh_handle) { ... }
```

creates a flickering mesh. It looks like another mesh is displayed for
a single frame, before the correct mesh is displayed again.

In the attached video I am **not** altering the adjacent meshes. I am
just retrieving a mutable borrow from the asset store. If I only
retrieve an immutable borrow the flicker disappears.

System info: NVIDIA RTX A2000 Laptop GPU, Vulkan backend.

## Expected Correct Output

The mesh that was rendered last frame should still be the mesh that
renders this frame, since its data has not changed. Calling `get_mut`
without writing should be a no-op for what's on screen.

## Actual Broken Output

For a single frame the displayed mesh is replaced with stale or
zeroed geometry — verts read from a previous version of the buffer
or from a wrong handle's buffer — and then the correct geometry
returns the next frame.

## Ground Truth

Per the fix PR ("Mark meshes as changed *after* AssetEvents are
processed"):

> When `get_mut` is called on an asset, the engine fires an
> `AssetEvent::Modified` and also bumps the asset's change tick. The
> render-world's mesh extraction was reading the change tick **before**
> the asset event handlers had run, so it would see the mesh as
> "changed", re-upload its GPU buffer from a possibly partial source,
> and then on the next frame the AssetEvent path would supply the
> correct buffer. Reordering the change-tick bump to fire **after**
> the events fixes the one-frame visual gap.

The fix changes the order in `crates/bevy_mesh/src/lib.rs` so the
"mark as changed" call comes after the asset event has been
processed.

## Fix
```yaml
fix_pr_url: https://github.com/bevyengine/bevy/pull/21002
fix_sha: 069fd874a4d93e2f921b494fb86d062451bc11dc
fix_parent_sha: 859d84910f745cd01b337a49859c6ee6da45d31d
bug_class: framework-internal
framework: bevy
framework_version: 0.16
files:
  - crates/bevy_mesh/src/lib.rs
change_summary: >
  The mesh asset bumped its change tick before the asset event was
  observed, so the render-world saw a "modified" mesh on the same
  frame the user merely read it. Re-uploading from the unfinished
  source created a one-frame flicker. The fix reorders the
  change-tick bump to fire after the asset event handler.
```

## Upstream Snapshot
- **Repo**: https://github.com/bevyengine/bevy
- **SHA**: 859d84910f745cd01b337a49859c6ee6da45d31d
- **Relevant Files**:
  - crates/bevy_mesh/src/lib.rs

## Flywheel Cell
primary: framework-maintenance.game-engine.code-navigation
secondary:
  - framework-maintenance.game-engine.captured-buffer-update-trace

## Difficulty Rating
4/5

## Adversarial Principles
- visual-symptom-only-user-report
- one-frame-defect-not-stable-state
- bug-lives-in-asset-system-not-renderer

## How OpenGPA Helps

A frame capture of the broken frame would show the mesh's vertex
buffer being re-uploaded (a `vkCmdCopyBuffer` / `vkCmdUpdateBuffer`
into the geometry's VBO) on the broken frame, while the buffer
contents are stale or zeroed. On adjacent frames the same buffer
shows complete data and **no upload command**. This pattern — "the
broken frame is the one with an unexpected buffer write" — points
the agent at the asset-event/change-tick interaction in
`bevy_mesh/src/lib.rs` rather than at the mesh extraction or
shader.

## Source
- **URL**: https://github.com/bevyengine/bevy/issues/19409
- **Type**: issue
- **Date**: 2025-05-28
- **Commit SHA**: 069fd874a4d93e2f921b494fb86d062451bc11dc
- **Attribution**: Reported by user against Bevy 0.16 (issue #19409); fix in PR #21002.

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
    - crates/bevy_mesh/src/lib.rs
  fix_commit: 069fd874a4d93e2f921b494fb86d062451bc11dc
```

## Predicted OpenGPA Helpfulness
- **Verdict**: yes
- **Reasoning**: The user's keyword trail ("flicker", "mutable
  borrow", "mesh") spans most of the engine — grep alone cannot
  isolate the asset-event ordering. A frame capture surfaces an
  anomalous buffer upload on the broken frame, narrowing the search
  to the asset/event side of the asset-system rather than to the
  renderer.

## Observed OpenGPA Helpfulness
- **Verdict**: ambiguous
- **Evidence**: validation pending — code_only baseline not yet run.
