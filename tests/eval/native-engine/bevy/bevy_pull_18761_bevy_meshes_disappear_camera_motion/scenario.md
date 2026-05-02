# R14: Bevy meshes appear and disappear as the camera moves

## User Report

After updating to 0.16-rc.1, some meshes from glTF models began to
intermittently appear and disappear. In my full game the missing
meshes seem to respond to camera motion: they will be present when
the camera is in one position and absent when it is in another.
Changing the window size also seems to trigger the flicker. In the
attached minimal example there is no camera motion but the missing
meshes are repeatably missing.

In my full game I have seen this issue when running directly on
wayland and also under xwayland; in the minimal example I have only
gotten it to reproduce when running directly in wayland.

System info: Intel UHD Graphics 620, Mesa 25.0.2, Vulkan backend.

(See attached screenshot — about half the parts of a glTF model are
just missing from the rendered frame.)

## Expected Correct Output

Every mesh that the camera frustum intersects should be drawn. The
set of visible meshes should change only when the camera or the
mesh actually moves into or out of the frustum, not when the camera
moves a few pixels.

## Actual Broken Output

A subset of the meshes is silently dropped from each frame. Which
subset is missing depends on the camera position and on window size.
The same scene rendered with the same camera at frame N may show
mesh A but not mesh B, while frame N+1 shows B but not A.

## Ground Truth

Per the fix PR ("Fix unbatchable meshes."):

The render-phase pipeline tries to combine many entities into a
single indirect-draw batch. Some entities (those with non-default
transforms or material flags) cannot be batched and must be drawn
individually. The dispatch code computed the batch size from the
total queued count instead of from the *batchable* queued count,
so when an unbatchable entity sat in the middle of the queue, the
batch boundary was off-by-one and one entity at the boundary was
silently skipped from the indirect-draw call. Camera motion changed
sort order, so different entities ended up at the boundary on
different frames — making it look as if random meshes were missing.

## Fix
```yaml
fix_pr_url: https://github.com/bevyengine/bevy/pull/18761
fix_sha: e8fd750274a04b0211c41dac0215af4e8c52a787
fix_parent_sha: dc7c8f228faa64ebdde59379af00f79e5750a0de
bug_class: framework-internal
framework: bevy
framework_version: 0.16-rc.1
files:
  - crates/bevy_render/src/render_phase/mod.rs
change_summary: >
  The render-phase batching computed batch boundaries from the full
  draw queue instead of from the batchable subset, so an
  unbatchable entity in the middle of the queue caused one entity
  at the boundary to be silently dropped from the indirect-draw
  dispatch. Recomputing the boundary from the batchable subset
  fixes the missing-mesh symptom.
```

## Upstream Snapshot
- **Repo**: https://github.com/bevyengine/bevy
- **SHA**: dc7c8f228faa64ebdde59379af00f79e5750a0de
- **Relevant Files**:
  - crates/bevy_render/src/render_phase/mod.rs

## Flywheel Cell
primary: framework-maintenance.game-engine.code-navigation
secondary:
  - framework-maintenance.game-engine.captured-draw-count-trace

## Difficulty Rating
4/5

## Adversarial Principles
- visual-symptom-only-user-report
- different-mesh-missing-on-different-frames-no-stable-signal
- bug-is-off-by-one-in-batching-not-in-mesh-data

## How OpenGPA Helps

A frame capture's draw-call list contains exactly N-1 calls when
the user expects N (one mesh missing). The capture also exposes
indirect-draw counts as recorded by the GPU. With both numbers in
hand, the agent sees that the indirect-draw count (`drawCount`
parameter to `vkCmdDrawIndexedIndirectCount` or equivalent) is one
less than the number of queued entities. That immediately points
at the dispatch / batch-bookkeeping code in `render_phase`, rather
than at frustum culling or visibility — the directions a static
analysis would take from the user report.

## Source
- **URL**: https://github.com/bevyengine/bevy/issues/18550
- **Type**: issue
- **Date**: 2025-03-25
- **Commit SHA**: e8fd750274a04b0211c41dac0215af4e8c52a787
- **Attribution**: Reported in issue #18550; fix in PR #18761.

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
    - crates/bevy_render/src/render_phase/mod.rs
  fix_commit: e8fd750274a04b0211c41dac0215af4e8c52a787
```

## Predicted OpenGPA Helpfulness
- **Verdict**: yes
- **Reasoning**: The user report ("camera motion makes meshes
  disappear") is a textbook case for runtime capture. Code_only
  has many plausible suspects: visibility, frustum culling,
  occlusion, render layers, asset extraction. A captured
  draw-count showing N-1 instead of N goes straight to "the
  dispatch code is off by one", which is a much smaller search.

## Observed OpenGPA Helpfulness
- **Verdict**: ambiguous
- **Evidence**: validation pending — code_only baseline not yet run.
