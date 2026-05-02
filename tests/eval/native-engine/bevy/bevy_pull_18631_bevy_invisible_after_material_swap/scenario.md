# R14: Bevy objects turn invisible when their material is replaced in a hook

## User Report

Behavior works as expected in 0.15. Broken in 0.16.0-rc.2 onwards.

When replacing a default material with a custom material from inside
an `OnAdd` observer or hook, the object turns invisible. This is not
true if you wait a few frames before replacing. Replacing a default
material with another default material works as expected — only the
swap to a custom material breaks.

```rust
fn on_add_hook_material_replacement(
    mut world: DeferredWorld,
    HookContext { entity, .. }: HookContext,
) {
    let new_material = world
        .resource_mut::<Assets<CustomMaterial>>()
        .add(CustomMaterial {});

    world.commands().entity(entity)
        .remove::<MeshMaterial3d<StandardMaterial>>()
        .insert(MeshMaterial3d(new_material));
}
```

I have a small repro that spawns 5 cubes; with the hook above, all
5 cubes are missing from the rendered frame. Without the hook the 5
cubes render correctly with their default material.

System info: Apple M1 Max, Metal backend.

## Expected Correct Output

After the hook runs, each cube should render with the custom
material — the swap should be visually identical to spawning the
cube with the custom material in the first place.

## Actual Broken Output

After the hook runs, none of the cubes appear in the frame. The
clear-color background is the only thing visible. If the hook is
replaced with a no-op or with a swap to another default material,
the cubes render normally.

## Ground Truth

Per the fix PR ("Fix mesh extraction for meshes without associated
material."):

The render-world's mesh-extraction system collects all entities
that have both a mesh component and a material component. When the
hook removed the old material and inserted the new one in the same
frame, the extraction system saw — for one extract pass — an
entity with a mesh but no material attached, and silently skipped
it. The render-world cached that "no material" decision until the
next change, so the entity was *never* re-queued for rendering
even though the new material was already attached. The fix detects
the late-attached material and re-queues the entity.

## Fix
```yaml
fix_pr_url: https://github.com/bevyengine/bevy/pull/18631
fix_sha: 17e3efac12fb0291f823ed4d381b14fad1ffffdd
fix_parent_sha: 95b9117eac346fb7c513f87ab1e8edab4ab2af8f
bug_class: framework-internal
framework: bevy
framework_version: 0.16.0-rc.2
files:
  - crates/bevy_pbr/src/meshlet/instance_manager.rs
  - crates/bevy_pbr/src/render/mesh.rs
change_summary: >
  Mesh extraction silently dropped entities that were briefly
  observed with a mesh but no material (during a remove+insert
  hook), and never re-added them once the material was attached.
  The fix re-queues those entities when their material handle
  becomes valid again.
```

## Upstream Snapshot
- **Repo**: https://github.com/bevyengine/bevy
- **SHA**: 95b9117eac346fb7c513f87ab1e8edab4ab2af8f
- **Relevant Files**:
  - crates/bevy_pbr/src/meshlet/instance_manager.rs
  - crates/bevy_pbr/src/render/mesh.rs

## Flywheel Cell
primary: framework-maintenance.game-engine.code-navigation
secondary:
  - framework-maintenance.game-engine.captured-extract-trace

## Difficulty Rating
4/5

## Adversarial Principles
- visual-symptom-only-user-report
- bug-only-fires-during-an-instant-remove-then-insert-window
- bug-leaves-entity-permanently-skipped-no-self-recovery

## How OpenGPA Helps

A frame capture shows zero draw calls for the cubes' mesh, even
though the entity exists in the world and has a valid pipeline.
Cross-checking the captured pipeline IDs against the bound mesh
buffers shows that the cube's pipeline was *never bound* on any
frame after the hook ran. That diagnostic — "the pipeline never
bound" — directly points the agent at the extract / queue side of
the renderer rather than at hooks, observers, or material code.

## Source
- **URL**: https://github.com/bevyengine/bevy/issues/18608
- **Type**: issue
- **Date**: 2025-03-30
- **Commit SHA**: 17e3efac12fb0291f823ed4d381b14fad1ffffdd
- **Attribution**: Reported in issue #18608; fix in PR #18631.

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
    - crates/bevy_pbr/src/render/mesh.rs
  fix_commit: 17e3efac12fb0291f823ed4d381b14fad1ffffdd
```

## Predicted OpenGPA Helpfulness
- **Verdict**: yes
- **Reasoning**: Grep on "hook" or "observer" leads to the ECS
  side; grep on "invisible" returns nothing useful. The bug is
  in mesh extraction, several layers away from anything the user
  named. A frame capture confirms the cube is never queued for
  rendering, focusing the search on `bevy_pbr/src/render/mesh.rs`
  rather than on `bevy_ecs`.

## Observed OpenGPA Helpfulness
- **Verdict**: ambiguous
- **Evidence**: validation pending — code_only baseline not yet run.
