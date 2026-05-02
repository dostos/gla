# R14: Godot 2D sprites flicker a 1-pixel white line above them when moving

## User Report

The reporter has a couple of `Sprite2D` / `AnimatedSprite2D` nodes
scrolling through a 2D scene. As the sprites move, a thin white
line briefly appears **only above** each sprite — never on the
left, right, or below. The line is one pixel high, flickers in
and out across single frames, and appears on both sprites at
once even though they're independent nodes.

The reporter notes:
- this didn't happen in Godot 3.x, started in Godot 4
- it happens regardless of whether the import option commonly
  used to fix edge bleed is on or off
- "it only bleeds above the sprites, and not in the other 3
  directions"
- catching the artifact in a video is hard because each
  appearance lasts a single frame

Repro: move any 2D sprite around at a non-integer velocity and
watch its top edge.

## Expected Correct Output

A 2D sprite's edges should be sharp and stable while the sprite
moves smoothly across the screen. The pixels just above (or
below or beside) the sprite's bounding box belong to whatever is
behind the sprite, never to a 1-pixel sliver of the texture.

## Actual Broken Output

For one frame at a time, while the sprite is between integer
pixel positions, a 1-pixel-tall white strip appears immediately
above the sprite. The strip's location follows the sprite's
on-screen position; the bottom, left, and right edges remain
correct.

## Ground Truth

Per the fix PR ("Calculate pixel snap in canvas space instead of
world space"):

> This ensures that you are actually snapping to pixels in the
> viewport and not an arbitrary amount.
>
> During the 4.0 rewrite, we added the concept of a world matrix.
> In Godot 3, we didn't transform into world space ever. The
> modelview matrix transformed directly from model space into
> canvas space. In Godot 4 we do that transform in 2 stages and
> pixel snap was mistakenly done _before_ the transformation to
> canvas space.

The pixel-snap step in the canvas vertex shader was being applied
to model-space vertex positions, then a second matrix transform
mapped those snapped positions into canvas space — so the snap
landed somewhere fractionally off "actual viewport pixels". The
1-pixel error happens to manifest visually as a top-edge bleed
because of how the rasterization tie-breaking rule rounds down.
The fix moves the snap to after the canvas-space transform.

See https://github.com/godotengine/godot/pull/97260 (fixes
#67164).

## Fix
```yaml
fix_pr_url: https://github.com/godotengine/godot/pull/97260
fix_sha: 5f5c6904815a5a0ae8690fff1409303a60f02680
fix_parent_sha: 621cadcf651b93757d5dbf8969023ae62a16f1a4
bug_class: framework-internal
framework: godot
framework_version: 4.0+
files:
  - drivers/gles3/shaders/canvas.glsl
  - servers/rendering/renderer_rd/shaders/canvas.glsl
change_summary: >
  In Godot 4, the canvas vertex shader pipeline performs two matrix
  multiplies (model -> world, then world -> canvas), but the
  pixel-snap rounding step was happening between those multiplies
  in model/world coordinates, so the snap quantum was not aligned
  with viewport pixels. Sub-pixel motion produced 1-pixel edge
  bleed, particularly at the top edge due to the rasterizer's
  fill-rule. The fix performs the snap after the final
  transformation, so it always rounds to true on-screen pixel
  centers.
```

## Upstream Snapshot
- **Repo**: https://github.com/godotengine/godot
- **SHA**: 621cadcf651b93757d5dbf8969023ae62a16f1a4
- **Relevant Files**:
  - drivers/gles3/shaders/canvas.glsl
  - servers/rendering/renderer_rd/shaders/canvas.glsl

## Flywheel Cell
primary: framework-maintenance.game-engine.code-navigation
secondary:
  - framework-maintenance.game-engine.captured-vertex-position-quantization

## Difficulty Rating
4/5

## Adversarial Principles
- one-pixel-bleed-only-on-one-of-four-edges
- bug-only-visible-mid-motion-not-static
- root-cause-is-an-order-of-operations-error-in-shader

## How OpenGPA Helps

A capture taken on a frame where the bleed is visible records the
final clip-space vertex positions of the sprite quad. Comparing
those across consecutive frames, the agent can see that the
quad's top-edge Y position is sometimes a fractional value like
N+0.49 and sometimes N+0.50, where the rasterizer's fill rule
flips between including the row above and not including it. The
fact that snapping happened at all (positions land near .5) but
not perfectly tells the agent the snap is being computed in the
wrong space — directly pointing at the canvas vertex shader.

## Source
- **URL**: https://github.com/godotengine/godot/issues/67164
- **Type**: issue
- **Date**: 2024-09-21
- **Commit SHA**: 5f5c6904815a5a0ae8690fff1409303a60f02680
- **Attribution**: Reported in godot#67164; fix in PR #97260.

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
    - drivers/gles3/shaders/canvas.glsl
    - servers/rendering/renderer_rd/shaders/canvas.glsl
  fix_commit: 5f5c6904815a5a0ae8690fff1409303a60f02680
```

## Predicted OpenGPA Helpfulness
- **Verdict**: yes
- **Reasoning**: The user's report uses zero engine vocabulary —
  "white line above sprite, only when moving". A code_only agent
  has nothing to grep for that lands in the right file; "sprite
  bleed" matches dozens of files. With OpenGPA, capturing the
  sprite-quad vertex positions across two adjacent frames
  directly exposes the sub-pixel snap drift, narrowing the
  search to "where do canvas vertices get snapped".

## Observed OpenGPA Helpfulness
- **Verdict**: ambiguous
- **Evidence**: validation pending — code_only baseline not yet run.
