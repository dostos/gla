# R21_FIX_VERTICAL_AND_HORIZONTAL_ARTIFACTS_ON: tile seam artifacts on large maps

## User Report
Getting these rendering artifacts on OS X + Firefox with mapbox-gl-js v0.11.2:
horizontal and vertical lines along tile boundaries across the map. The code is
built on the examples from the docs — a dark vector style with boundary, water,
and label layers, zoom 6, center `[35, 32]`. A follow-up report (#2676) adds
more detail: "Create a large 4096x4096px map. Shouldn't see these tile boundary
lines. I'm seeing tile borders on both GeoJSON and `mapbox://styles/mapbox/streets-v8`.
I've tried a bunch of different values for buffer (starting with the minimum 0,
1, 16, 128, ending with the maximum 512 and not setting it) all it does is move
where the lines appear." Chromium does not always reproduce it; repros are also
seen on Windows 10 Chrome 51. The Mapbox Static Image API produces tiles with
the same seam lines, so whatever they use server-side seems affected too.

## Expected Correct Output
A continuous rendered map with no visible tile-boundary seams — tile content
stays cleanly inside its own tile, with neighboring tiles stitching together
without bleed-through.

## Actual Broken Output
Thin horizontal and vertical lines appear along tile boundaries across the map.
Geometry from one tile's draw pass appears inside an unrelated tile's region,
most visibly at large map sizes (e.g. 4096×4096).

## Ground Truth
Root cause: the stencil clipping-mask pass allocates only 5 bits per tile ID
(`stencilMask(0xF8)` plus `id << 3`), which caps unique tile IDs at 31. On
large maps with more than 31 visible tiles, the `(id << 3) & 0xF8` expression
wraps and two distinct tiles are assigned the *same* stencil value. The
subsequent content pass uses `stencilFunc(gl.EQUAL, id << 3, 0xF8)` to clip
drawing to a tile's own region, but with the collision the test passes in the
colliding tile's region as well, letting geometry bleed across the seam.

From PR #4636 ("Use 3 more bits for clipping mask ids"):

> Fixes #3517. Fixes #2676. Likely fixes #1679. Native already does this. Not
> sure how to add a regression test though — this only happens on large maps
> and I wouldn't want to add a 2000x1000 fixture to the render suite.

The pre-fix `_renderTileClippingMasks` in `src/render/painter.js` reads:

> // Only write clipping IDs to the last 5 bits. The first three are used for drawing fills.
> gl.stencilMask(0xF8);
> ...
> const id = this._tileClippingMaskIDs[coord.id] = (idNext++) << 3;
> gl.stencilFunc(gl.ALWAYS, id, 0xF8);

The fix widens the ID field (using 8 bits for the clip ID, matching the native
renderer), which pushes the collision point from 31 tiles to 255.

## Difficulty Rating
4/5

## Adversarial Principles
- ID-space overflow in a masked stencil buffer
- Silent alias between two draw calls' stencil reference values
- Bug only manifests with enough concurrent participants (>31 tiles) — small
  repros miss it
- Symptom (seam line) is spatially far from the cause (bit layout of the
  stencil mask)

## How OpenGPA Helps
Querying the stencil state and per-draw `stencilFunc`/`stencilMask` across
draw calls reveals that two tiles share the same masked reference value (both
resolve to stencil `0x08` after `& 0xF8`). The per-draw-call state dump shows
the ID shift and mask, making the 5-bit field and its collision point
self-evident without having to read the framework's source.

## Source
- **URL**: https://github.com/mapbox/mapbox-gl-js/issues/1679
- **Type**: issue
- **Date**: 2015-11-06
- **Commit SHA**: (n/a)
- **Attribution**: Reported by @yuvadm; fix PR #4636 by Mapbox contributors

## Tier
core

## API
opengl

## Framework
none

## Bug Signature
```yaml
type: unexpected_color
spec:
  region:
    x: 16
    y: 240
    width: 1
    height: 1
  forbidden_color: [255, 0, 0, 255]
  tolerance: 16
  note: >
    Pixel lies inside tile A's stencil region but outside tile A's content
    quad. With a correctly sized clip-ID field, tile B's red draw is gated
    out and the pixel stays at clear-color black. With the 5-bit ID
    collision (tile A id=1, tile B id=33 both resolve to stencil 0x08),
    tile B's fullscreen red quad passes the stencil test in tile A's
    region and the pixel turns red.
```

## Predicted OpenGPA Helpfulness
- **Verdict**: yes
- **Reasoning**: The bug is entirely encoded in GL state — the stencil
  reference value, the stencil mask, and the per-draw op. Tier 1 capture
  exposes all three per draw call. An agent comparing the clip-write pass
  against the content pass can observe the shared masked reference directly,
  without needing to read mapbox-gl's JavaScript.

## Observed OpenGPA Helpfulness
- **Verdict**: ambiguous
- **Evidence**: validation skipped (--no-validate)
