# R14: Godot CanvasGroup goes completely black when its container is tiny

## User Report

A `CanvasGroup` with a `Sprite2D` (or `ColorRect`) child renders
correctly when its containing `SubViewport` is at normal size,
but goes **completely black** as soon as the parent viewport's
width or height drops to 40 pixels or less. At 41 pixels the
group renders normally. At 40 it's a solid black rectangle.

Repro:
1. Add a `SubViewportContainer` with a child `SubViewport`.
2. Inside the viewport, add a `CanvasGroup` with a visible
   child node (Sprite2D, ColorRect, etc.).
3. Set the viewport size to 40 px or smaller in either
   dimension. The CanvasGroup turns black.
4. Set it to 41 px or larger. The CanvasGroup renders normally.

## Expected Correct Output

Whatever is inside the `CanvasGroup` should render at any
non-zero viewport size. A 1×1 viewport should still produce a
1×1 image of the group's contents, not a black square.

## Actual Broken Output

At any viewport dimension <= 40 pixels, the entire CanvasGroup
contents render as solid black. The threshold is sharp and
position-independent.

## Ground Truth

Per the fix PR ("Remove Compatibility RenderTarget backbuffer
size limit"):

> The Compatibility Renders Texture Storage imposes a size limit
> of 41x41 when creating the back buffer for a RenderTarget.
> ... this is intended to ensure no mipmaps are generated for
> these small buffers, however the base level is also not
> generated.

`CanvasGroup` requires a back buffer to composite its children.
The texture-storage code refused to allocate the back buffer
when either dimension was below 41, on the grounds that
mipmaps couldn't be generated for very small textures.
Unfortunately the same code path also refused to allocate the
*base* mip level, so the back buffer never existed at all,
and the canvas-group composite read from an empty texture —
producing solid black.

The fix removes the size limit; the function already had
correct logic for "no mipmaps, just base level" so no further
guarding is needed.

See https://github.com/godotengine/godot/pull/114957 (fixes
#114899).

## Fix
```yaml
fix_pr_url: https://github.com/godotengine/godot/pull/114957
fix_sha: 04e3d906f9f9a81f4078ac6bce4e73b9a7470581
fix_parent_sha: c4a893e988935aa8401a9ab4d3dd29b96db4fa1a
bug_class: framework-internal
framework: godot
framework_version: 4.5.1.stable
files:
  - drivers/gles3/storage/texture_storage.cpp
change_summary: >
  Texture storage refused to create the render-target back buffer
  when either dimension was 40 or less, intended to skip mipmap
  generation but accidentally skipping base-level allocation as
  well. CanvasGroup composites read from this missing back buffer
  and produced solid black. The fix drops the conditional; the
  surrounding code already handles "size too small for mipmaps"
  correctly by only generating the base level.
```

## Upstream Snapshot
- **Repo**: https://github.com/godotengine/godot
- **SHA**: c4a893e988935aa8401a9ab4d3dd29b96db4fa1a
- **Relevant Files**:
  - drivers/gles3/storage/texture_storage.cpp

## Flywheel Cell
primary: framework-maintenance.game-engine.code-navigation
secondary:
  - framework-maintenance.game-engine.captured-missing-attachment

## Difficulty Rating
3/5

## Adversarial Principles
- bug-only-fires-below-an-arbitrary-pixel-threshold
- root-cause-is-a-too-aggressive-defensive-skip
- broken-output-is-solid-black-not-corrupted

## How OpenGPA Helps

A frame capture of the broken case would show the canvas-group
composite draw call sampling from a render-target whose backing
texture either has no allocated storage or is reported as 0×0.
The diff against the working (41px) case is direct: the working
case has a populated back-buffer texture, the broken case has
an empty/missing one. That fact lands the agent in
`texture_storage.cpp` rather than `canvas_group.cpp` or
`canvas_render_*.cpp`.

## Source
- **URL**: https://github.com/godotengine/godot/issues/114899
- **Type**: issue
- **Date**: 2026-04-23
- **Commit SHA**: 04e3d906f9f9a81f4078ac6bce4e73b9a7470581
- **Attribution**: Reported in godot#114899; fix in PR #114957.

## Tier
end-user-framing

## API
opengl

## Framework
godot

## Bug Signature
```yaml
type: code_location
spec:
  expected_files:
    - drivers/gles3/storage/texture_storage.cpp
  fix_commit: 04e3d906f9f9a81f4078ac6bce4e73b9a7470581
```

## Predicted OpenGPA Helpfulness
- **Verdict**: yes
- **Reasoning**: The user-visible symptom is "small CanvasGroup
  goes black". A code_only agent grepping for "CanvasGroup"
  would reach the canvas-group composite logic, not the
  texture-storage allocation guard that's the actual cause. A
  capture comparing the broken (40px) and working (41px) cases
  surfaces "the back-buffer texture is missing/empty in the
  broken case" — a fact the user couldn't have known to mention,
  pointing past the canvas-group class into texture allocation.

## Observed OpenGPA Helpfulness
- **Verdict**: ambiguous
- **Evidence**: validation pending — code_only baseline not yet run.
