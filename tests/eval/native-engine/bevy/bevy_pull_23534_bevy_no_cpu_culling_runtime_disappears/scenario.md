# R13: Bevy `NoCpuCulling` added at runtime makes the mesh disappear

## User Report

Bevy `main` (`cc172dfc3c8d50fb86dad77496e7010229c7a53e`), Windows 11,
NVIDIA RTX 4080.

Repro (verbatim from issue):

```rust
use bevy::{camera::visibility::NoCpuCulling, prelude::*};

fn main() {
    App::new()
        .add_plugins(DefaultPlugins)
        .add_systems(Startup, setup)
        .add_systems(Update, toggle_no_cpu_culling)
        .run();
}

fn setup(
    mut commands: Commands,
    mut meshes: ResMut<Assets<Mesh>>,
    mut materials: ResMut<Assets<StandardMaterial>>,
) {
    commands.spawn((Mesh3d(meshes.add(Cuboid::new(1.0, 1.0, 1.0))),
                    MeshMaterial3d(materials.add(Color::srgb_u8(124, 144, 255))),
                    Transform::from_xyz(0.0, 0.5, 0.0)));
    /* ... + camera + light */
}

fn toggle_no_cpu_culling(
    mut commands: Commands,
    input: Res<ButtonInput<KeyCode>>,
    meshes: Query<(Entity, Has<NoCpuCulling>), With<Mesh3d>>,
) {
    if input.just_pressed(KeyCode::Space) {
        for (entity, has_no_cpu_culling) in &meshes {
            if has_no_cpu_culling {
                commands.entity(entity).remove::<NoCpuCulling>();
            } else {
                commands.entity(entity).insert(NoCpuCulling);
            }
        }
    }
}
```

Expected: pressing **Space** toggles whether the mesh participates
in CPU culling, but the mesh remains visible in either state.
Actual: pressing **Space** to add `NoCpuCulling` to a previously-spawned
mesh makes the mesh disappear from the rendered output.

## Expected Correct Output

The cube renders every frame. `NoCpuCulling` only affects which
culling system (CPU vs. GPU) the entity participates in — the
rendered draw call should still be issued.

## Actual Broken Output

After `NoCpuCulling` is inserted on a frame **after** the entity was
spawned, the mesh stops being submitted to either the CPU or the GPU
culling bucket, and `vkCmdDraw` for that mesh stops being recorded.

The PR description explains the underlying invariant violation:

> Currently, adding `NoCpuCulling` to a mesh on a frame after that
> mesh was spawned causes that mesh to disappear. This is due to two
> bugs:
>
> 1. Meshes are unconditionally, and incorrectly, added to
>    `RenderGpuCulledEntities`, even if they are subject to CPU
>    culling. Entities are only added to the GPU culling bucket if
>    they (1) don't participate in CPU culling, (2) are in
>    `RenderGpuCulledEntities` *now*, and (3) weren't in
>    `RenderGpuCulledEntities` *before*. Right now, since entities
>    are always in `RenderGpuCullingEntities`, these conditions are
>    never met when adding `NoCpuCulling` to an existing entity, so
>    the entity is never added to the GPU culling bucket.

## Ground Truth

Fix landed as PR #23534 ("Fix the behavior of `NoCpuCulling` when
toggled at runtime."). The fix corrects the `RenderGpuCulledEntities`
membership logic in `crates/bevy_pbr/src/render/mesh.rs` so meshes
are only added to the GPU bucket when they actually meet all three
conditions — and so toggling `NoCpuCulling` on a previously-spawned
entity correctly migrates it.

See https://github.com/bevyengine/bevy/pull/23534 (fixes #23473).

## Fix
```yaml
fix_pr_url: https://github.com/bevyengine/bevy/pull/23534
fix_sha: 96e4074109adc588a8f5366dafe6d6d4edf4662a
fix_parent_sha: c34a27cefc9ce297c586d03e5cc361da9e8a2b81
bug_class: framework-internal
framework: bevy
framework_version: main@cc172dfc3c8d50fb86dad77496e7010229c7a53e
files:
  - crates/bevy_pbr/src/render/mesh.rs
change_summary: >
  Toggling `NoCpuCulling` at runtime relied on a tracked-membership
  invariant in `RenderGpuCulledEntities` that was always false in
  practice — meshes were being unconditionally added to the GPU
  culling bucket even when subject to CPU culling, so the
  "wasn't there before, is there now" predicate never fired when the
  user later inserted `NoCpuCulling`. The mesh ended up in neither
  bucket and `vkCmdDraw` was not recorded for it. The fix tightens
  the GPU-bucket membership predicate so the runtime toggle migrates
  the entity correctly.
```

## Upstream Snapshot
- **Repo**: https://github.com/bevyengine/bevy
- **SHA**: c34a27cefc9ce297c586d03e5cc361da9e8a2b81
- **Relevant Files**:
  - crates/bevy_pbr/src/render/mesh.rs

## Flywheel Cell
primary: framework-maintenance.game-engine.code-navigation
secondary:
  - framework-maintenance.game-engine.captured-draw-call-absent-breadcrumb

## Difficulty Rating
4/5

## Adversarial Principles
- bug-lives-inside-framework-not-user-code
- ecs-state-tracking-invariant-violation-not-a-render-state-bug
- mesh-is-still-in-the-scene-but-no-vkCmdDraw-is-issued-for-it

## How OpenGPA Helps

A captured frame **before** pressing Space contains a `vkCmdDraw`
for the cube mesh. A captured frame **after** pressing Space does
**not** — the same entity is in the scene graph but has dropped out
of the captured command stream. `gpa frame-diff` between the two
frames identifies the missing draw as the primary delta. The agent
can then ask "which Bevy system decides whether this mesh's draw is
recorded?" and follow the trail through the visibility/culling
plugins to `mesh.rs`. The CPU-culling vs. GPU-culling bucket
distinction is internal Bevy state, not GL/Vulkan state, so the
capture is necessary to confirm "the mesh is gone from the actual
device draw stream" and not "the mesh is invisible because of
shader/material/transform". That elimination is the core OpenGPA
contribution here.

## Source
- **URL**: https://github.com/bevyengine/bevy/issues/23473
- **Type**: issue
- **Date**: 2026-03-22
- **Commit SHA**: 96e4074109adc588a8f5366dafe6d6d4edf4662a
- **Attribution**: Reported by @IceSentry in bevy#23473; fix in PR #23534.

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
    - crates/bevy_pbr/src/render/mesh.rs
  fix_commit: 96e4074109adc588a8f5366dafe6d6d4edf4662a
```

## Predicted OpenGPA Helpfulness
- **Verdict**: yes
- **Reasoning**: This bug looks like a typical "shader bug" or a
  "transform bug" from the user's vantage — the mesh is in the scene
  but isn't drawn. Without a frame capture, the most natural
  hypotheses are (a) the material is wrong, (b) the transform is
  off-screen, (c) the shader returns alpha=0. A captured-frame
  draw-call list **immediately** falsifies all three by showing the
  mesh's draw is simply absent from the command stream — which forces
  the investigation into "why didn't the renderer record a draw for
  this entity", which is exactly the right question. That redirection
  is the core OpenGPA value here.

## Observed OpenGPA Helpfulness
- **Verdict**: no
- **Evidence**: code_only baseline scored 1.0 on file-level identification (Claude Code Explore subagent against the bevy snapshot at fix_parent_sha, ~20 file reads, ~30s wall time). The user-report keywords map directly onto the bug-bearing file path, leaving no headroom for runtime capture to add value. See docs/superpowers/eval/round13/bevy-code-only-results.md.
