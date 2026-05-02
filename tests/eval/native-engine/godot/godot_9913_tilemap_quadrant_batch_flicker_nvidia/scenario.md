# R19_TILEMAP_QUADRANT_BATCH_FLICKER_NVIDIA: TileMap quadrant-batch flicker on Nvidia drivers (Godot)

## User Report
**Operating system or device - Godot version:**
Windows 10, godot3.0alpha1

**Issue description:**
I made a kinematicbody2D and a tilemap, moving the kinematic body around worked as normal however occasionally one of the tiles on the tilemap would vanish faster than any screen recording software could capture. sometimes 2 would vanish, they would get redrawn however

**Steps to reproduce:**
Make a tilemap, load some tiles in, make a kinematic body
move the body around the game, keep your eyes open, dont blink, watch as some tiles vanish from rendering and quickly come back

## Expected Correct Output
A 4-tile quadrant rendered as a row of four green squares at y≈16, evenly spaced horizontally, all fully on-screen.

## Actual Broken Output
Three of the four tiles render correctly; one tile (the third) is displaced to an off-screen position because its per-instance transform in the batch VBO was left over from a previous quadrant upload, so the quadrant appears to have a missing / "flickered" tile in the visible region.

## Ground Truth
In Godot 3 (alpha through stable), a `TileMap` with `Cell Quadrant Size > 1` renders with random, intermittent flickering on Nvidia GPUs: tiles briefly vanish or render at wrong locations, and individual glyphs of large `Label` nodes do the same (font-atlas subrects rendered at wrong positions). The same project runs cleanly in Godot 2.1 and on Intel iGPUs.

The thread contains no maintainer-authored root-cause fix, but multiple users independently reduce the trigger to Godot's 2D quadrant-batching path. The empirically observed rule is that it only occurs when per-quadrant transforms are batched (quadrant size > 1):

> It looks like if the Quadrant Size is set to 1 the problem disappears

and from a later comment after further testing:

> Seems to only happen with `TileMap`s with a cell quadrant size > 1 and, sometimes, text. […] The only thing I can think of is some transform not being set correctly at random...

The YSort workaround corroborates this, because (per the thread):

> Note that Ysort forces ~~(Cell)~ Quadrant Size = 1.

Taken together, the thread's evidence localises the defect to Godot 3's rewritten batched canvas-item renderer, specifically the path that streams per-tile transforms into a shared VBO/UBO for a whole quadrant and issues one instanced/indexed draw. On Nvidia drivers, stale transform data from previously uploaded quadrants is occasionally read by the draw call (a classic uninitialised-or-unsynchronised instance-attribute region problem), producing the observed per-instance displacement. Label flicker shares the code path because Godot 3 batches glyph quads the same way. Quadrant size = 1 and YSort both defeat the bug by forcing one-tile-per-draw, eliminating the batched transform upload entirely. No fix is referenced in this issue.

## Difficulty Rating
4/5

## Adversarial Principles
- Driver-specific intermittent (Nvidia-only, non-deterministic timing)
- Shared/batched per-instance buffer with stale residual data
- Workaround exists but root cause not upstreamed

## How OpenGPA Helps
Querying the per-draw snapshot for the batched quadrant draw call exposes the full per-instance transform array in the VBO region being read: an agent can spot that instance[2]'s translate is far outside the viewport while its color is still the correct tile color, pointing immediately at a stale transform in the instance buffer rather than a shader or texture bug.

## Source
- **URL**: https://github.com/godotengine/godot/issues/9913
- **Type**: issue
- **Date**: 2017-07-30
- **Commit SHA**: (n/a)
- **Attribution**: Reported by @Remixful; corroborated by @akien-mga, @securas, and others in thread

## Tier
core

## API
opengl

## Framework
none

## Bug Signature
```yaml
type: color_histogram_in_region
spec:
  region:
    x: 208
    y: 16
    width: 64
    height: 64
  expected_dominant_color: [51, 204, 51]
  min_fraction: 0.9
```

## Upstream Snapshot
- **Repo**: https://github.com/godotengine/godot
- **SHA**: 786e55738e0b26c810a8a11bd75dfa2f43468566
- **Relevant Files**:
  - drivers/gles3/rasterizer_canvas_gles3.cpp  # base of Nvidia workaround PR #38517 (3.x branch)
  - drivers/gles2/rasterizer_canvas_gles2.cpp
  - scene/2d/tile_map.cpp

## Predicted OpenGPA Helpfulness
- **Verdict**: yes
- **Reasoning**: The root cause is a stale per-instance transform inside a batched draw call. OpenGPA's draw-call snapshot surfaces the raw instance attribute buffer contents, letting an agent directly compare intended vs. actual per-instance transforms — exactly the data the Godot thread lacked and which a screenshot alone cannot show.

## Observed OpenGPA Helpfulness
- **Verdict**: ambiguous
- **Evidence**: validation skipped (--no-validate)
