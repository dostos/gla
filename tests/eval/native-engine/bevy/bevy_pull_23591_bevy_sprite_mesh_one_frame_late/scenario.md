# R14: Bevy SpriteMesh flickers/disappears when newly spawned

## User Report

```rust
use bevy::prelude::*;

fn main() {
    App::new()
        .add_plugins(DefaultPlugins)
        .add_systems(Startup, setup)
        .add_systems(Update, update)
        .run();
}

#[derive(Resource)]
struct ImageHandle(Handle<Image>);

fn setup(mut commands: Commands, asset_server: Res<AssetServer>) {
    commands.spawn(Camera2d);
    commands.insert_resource(ImageHandle(asset_server.load("branding/icon.png")));
}

fn update(
    mut commands: Commands,
    image: Res<ImageHandle>,
    key: Res<ButtonInput<KeyCode>>,
    sprites: Query<Entity, Or<(With<Sprite>, With<SpriteMesh>)>>,
) {
    if key.pressed(KeyCode::KeyF) || key.just_pressed(KeyCode::KeyS) {
        for sprite in sprites { commands.entity(sprite).despawn(); }
        commands.spawn((
            SpriteMesh::from_image(image.0.clone()),
            Transform::from_xyz(300.0, 0.0, 0.0),
        ));
        commands.spawn((
            Sprite::from_image(image.0.clone()),
            Transform::from_xyz(-300.0, 0.0, 0.0),
        ));
    }
}
```

Run the above, tap **S** and wait for loading. Then tap **S** again,
or hold **F**.

Tapping **S** causes the right-hand image to flicker briefly.
Holding **F** causes the right-hand image to disappear entirely.

Neither symptom affects the left-hand image.

`SpriteMesh` is supposed to be a drop-in replacement for `Sprite`, so
it should not behave differently than `Sprite` does in this scenario.

(Original reporter trimmed: the issue body included a guess at the
suspected file. That guess has been removed for this scenario; the
agent should diagnose without that hint.)

## Expected Correct Output

When **S** is tapped, both the left and right image should reappear
on the same frame. When **F** is held, both should remain visible.
The two paths should produce identical visual behaviour because
`SpriteMesh::from_image` and `Sprite::from_image` are documented as
interchangeable.

## Actual Broken Output

On the spawn frame, the right-hand image is missing entirely. On
some frames it appears one frame later than the left-hand image,
producing a visible flicker on a single tap, or a fully missing
image when the spawn happens every frame.

## Ground Truth

Per the fix PR ("Update SpriteMesh in PostUpdate"):

The systems responsible for converting `SpriteMesh::from_image` into
the `Mesh2d` + `MeshMaterial2d` components were running in the
`Update` schedule. When the user spawned a new `SpriteMesh` *during
Update*, the conversion systems had already executed for that frame,
so on the same frame the entity had no `Mesh2d` — meaning the
extract phase (which runs after Update) skipped it, and nothing was
queued for rendering. The fix moves those conversion systems into
`PostUpdate` so they run after user spawns and before the extract
phase.

## Fix
```yaml
fix_pr_url: https://github.com/bevyengine/bevy/pull/23591
fix_sha: f70f75a0193d77c94d0bd4a8d19ef7b9b8183614
fix_parent_sha: 20407a3767b7828e54ab76356902dfaa7f96169f
bug_class: framework-internal
framework: bevy
framework_version: main@4bbd37d
files:
  - crates/bevy_sprite_render/src/sprite_mesh/mod.rs
change_summary: >
  SpriteMesh's component-conversion systems ran in Update, so an
  entity spawned during Update missed that frame's conversion and
  was extracted with no Mesh2d, producing a one-frame visual gap.
  The fix moves those systems to PostUpdate so they always run
  after spawns and before extract.
```

## Upstream Snapshot
- **Repo**: https://github.com/bevyengine/bevy
- **SHA**: 20407a3767b7828e54ab76356902dfaa7f96169f
- **Relevant Files**:
  - crates/bevy_sprite_render/src/sprite_mesh/mod.rs

## Flywheel Cell
primary: framework-maintenance.game-engine.code-navigation
secondary:
  - framework-maintenance.game-engine.captured-extract-phase-trace

## Difficulty Rating
3/5

## Adversarial Principles
- visual-symptom-only-user-report
- only-one-of-two-otherwise-identical-paths-fails
- bug-is-system-ordering-not-data

## How OpenGPA Helps

A frame capture of the broken frame shows that the right-hand image
contributed **zero draw calls**, while the left-hand image (the
`Sprite` path) contributed one. The agent can compare the captured
draw-call list across two frames (broken vs working) to see that
the new `SpriteMesh` entity was **not extracted** on the broken
frame — pointing at "the conversion happened too late in the
schedule" rather than at "the mesh data is wrong".

## Source
- **URL**: https://github.com/bevyengine/bevy/issues/23590
- **Type**: issue
- **Date**: 2026-04-15
- **Commit SHA**: f70f75a0193d77c94d0bd4a8d19ef7b9b8183614
- **Attribution**: Reported in issue #23590; fix in PR #23591.

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
    - crates/bevy_sprite_render/src/sprite_mesh/mod.rs
  fix_commit: f70f75a0193d77c94d0bd4a8d19ef7b9b8183614
```

## Predicted OpenGPA Helpfulness
- **Verdict**: yes
- **Reasoning**: With the file-pointer hint trimmed from the user
  report, the symptom alone ("only one of two near-identical paths
  flickers") could match many engine systems. The cross-frame
  draw-call diff confirms that the broken entity contributed zero
  draws — pointing the agent at extract/queue ordering for that
  specific component family rather than at material or mesh code.

## Observed OpenGPA Helpfulness
- **Verdict**: ambiguous
- **Evidence**: validation pending — code_only baseline not yet run.
