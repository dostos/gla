# R13: Bevy wireframe pipeline rejected — depth bias on LineList topology

## User Report

Bevy `main` (commit `9040ceacac674be9efce780bb812a49a5cca7fd4`) on
Vulkan / NVIDIA GTX 1650 Ti / Windows 11.

Repro:

1. `cargo run --example 2d_shapes`
2. Toggle "show wireframes".

Expected: wireframes render.
Actual: nothing renders for the wireframe layer, and the renderer
logs the following validation errors:

```
ERROR bevy_render::error_handler: Caught rendering error: Validation Error
Caused by:
  In Device::create_render_pipeline, label = 'wireframe_2d_pipeline'
    Depth/stencil state is invalid
      Depth bias is not compatible with non-triangle topology LineList

ERROR bevy_render::error_handler: Caught rendering error: Validation Error
Caused by:
  In a CommandEncoder
    In a set_pipeline command
      RenderPipeline with 'wireframe_2d_pipeline' label is invalid

ERROR bevy_render::error_handler: Caught rendering error: Validation Error
Caused by:
  In Queue::submit
    In a set_pipeline command
      RenderPipeline with 'wireframe_2d_pipeline' label is invalid
```

The same defect affects the 3D wireframe plugin (`#23772`).

## Expected Correct Output

The wireframe pipeline successfully creates and binds, drawing the
mesh outlines on top of the 2D shapes.

## Actual Broken Output

`RenderPipeline::create_render_pipeline` fails because the pipeline
descriptor sets a non-zero depth-bias (`bias.is_enabled() == true`)
on a primitive with `topology = LineList`. The validation rejects
the pipeline; subsequent `cmdSetPipeline` / `vkCmdDraw` against the
invalid handle is dropped, and the user sees no wireframe.

The validation rule that fires (from wgpu):

```rust
if (ds.bias.is_enabled() || ds.bias.clamp != 0.0)
    && !desc.primitive.topology.is_triangles()
{
    return Err(...DepthBiasWithIncompatibleTopology(desc.primitive.topology));
}
```

## Ground Truth

Per the fix PR ("fix(wireframes): only set depth bias when topology
is triangles"):

> # Objective
> - Fixes #23772
> - Fixes #23774
>
> Fixes wireframe plugins. wgpu added some validation around
> `DepthBiasState`. `ds.bias.is_enabled()` returns true [for non-zero
> constant or slope_scale], so we should only set those when the
> topology is triangles.

The fix gates the depth-bias fields in `wireframe.rs` and
`wireframe2d.rs` on the primitive topology being a triangle variant.
For line topologies the bias is left at zero.

See https://github.com/bevyengine/bevy/pull/23782 (fixes #23772 + #23774).

## Fix
```yaml
fix_pr_url: https://github.com/bevyengine/bevy/pull/23782
fix_sha: 4329b04d78f00832f2c7a893e9c1ea9f49dcefb9
fix_parent_sha: 70c56c241b7888891902f74582f2df12b2dbb77d
bug_class: framework-internal
framework: bevy
framework_version: main@9040ceacac674be9efce780bb812a49a5cca7fd4
files:
  - crates/bevy_pbr/src/wireframe.rs
  - crates/bevy_sprite_render/src/mesh2d/wireframe2d.rs
change_summary: >
  The wireframe pipelines (2D and 3D) unconditionally populated
  `DepthBiasState` even when `primitive.topology = LineList`. wgpu's
  newer validation rejects bias-on-non-triangles, which makes pipeline
  creation fail and the wireframe draws never reach the device. The
  fix only sets depth bias when the topology is a triangle variant,
  leaving line topologies with `bias = 0` so pipeline creation
  succeeds.
```

## Upstream Snapshot
- **Repo**: https://github.com/bevyengine/bevy
- **SHA**: 70c56c241b7888891902f74582f2df12b2dbb77d
- **Relevant Files**:
  - crates/bevy_pbr/src/wireframe.rs
  - crates/bevy_sprite_render/src/mesh2d/wireframe2d.rs

## Flywheel Cell
primary: framework-maintenance.game-engine.code-navigation
secondary:
  - framework-maintenance.game-engine.captured-pipeline-state-breadcrumb

## Difficulty Rating
2/5

## Adversarial Principles
- bug-lives-inside-framework-not-user-code
- pipeline-creation-fails-silently-from-the-user-perspective-validation-is-only-in-logs
- topology-state-mismatch-with-rasterizer-feature

## How OpenGPA Helps

A frame capture would show **no draw calls bound to the
`wireframe_2d_pipeline`** at all — the pipeline never made it to a
valid handle, so `vkCmdBindPipeline(wireframe_2d_pipeline)` never
appears in the captured command stream. The agent can then ask
"why is wireframe_2d_pipeline missing from the binding history?" and
the captured-`debug_marker`/`vkCmdSetCheckpointNV`-equivalent named
breadcrumbs (or the engine log line wgpu emits) would point at the
pipeline-creation failure. Cross-referencing the pipeline's intended
layout (LineList topology) with the validation message
"Depth bias is not compatible with non-triangle topology LineList"
points the agent at `wireframe.rs` / `wireframe2d.rs`.

## Source
- **URL**: https://github.com/bevyengine/bevy/issues/23774
- **Type**: issue
- **Date**: 2026-04-12
- **Commit SHA**: 4329b04d78f00832f2c7a893e9c1ea9f49dcefb9
- **Attribution**: Reported by @lmikoc in bevy#23774 and #23772; fix in PR #23782.

## Tier
maintainer-framing

## API
vulkan

## Framework
bevy

## Bug Signature
```yaml
type: code_location
spec:
  expected_files:
    - crates/bevy_pbr/src/wireframe.rs
    - crates/bevy_sprite_render/src/mesh2d/wireframe2d.rs
  fix_commit: 4329b04d78f00832f2c7a893e9c1ea9f49dcefb9
```

## Predicted OpenGPA Helpfulness
- **Verdict**: yes
- **Reasoning**: The captured frame shows no `vkCmdBindPipeline`
  for the wireframe pipeline whatsoever. Combined with the wgpu
  validation log line ("Depth bias is not compatible with
  non-triangle topology LineList"), the agent is pointed at the
  exact pipeline descriptor and the exact field (`DepthBiasState`)
  that violates the constraint. The two source files in the fix
  are the only places `wireframe_2d_pipeline` /
  `wireframe_pipeline` are constructed.

## Observed OpenGPA Helpfulness
- **Verdict**: no
- **Evidence**: code_only baseline scored 1.0 on file-level identification (Claude Code Explore subagent against the bevy snapshot at fix_parent_sha, ~20 file reads, ~30s wall time). The user-report keywords map directly onto the bug-bearing file path, leaving no headroom for runtime capture to add value. See docs/superpowers/eval/round13/bevy-code-only-results.md.
