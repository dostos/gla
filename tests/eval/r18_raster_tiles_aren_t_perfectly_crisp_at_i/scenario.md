# R18: Raster tiles aren't perfectly crisp at integer zoom levels

## User Report
I noticed that raster tiles are somewhat blurry when rendered in Mapbox and
did some experimenting. When at a discrete zoom level (e.g. 14) it appears
as if the tiles are rendered slightly smaller than the original size in
which they were retrieved from the tile service. Am I correct in assuming
that a 256x256 tile is not rendered in 256x256 pixels when at a discrete
zoom level? Once you notice the blurriness of the raster images it is
rather annoying. I'm using version 0.34.0.

Multiple commenters confirm: at 100% page zoom, comparing the original
raster tile (inspected via WebGL Inspector, crisp) against the on-screen
rendering (blurry), the rendered image is visibly softer — "just look at
the MEMORIAL letters." It reproduces on v0.34.0 and on then-current
master, and on the official map-tiles example page. It is environment
sensitive: a devicePixelRatio of 2.25 looks crisp, but on a
devicePixelRatio of 1 device it's blurry; forcing @2x tiles on the dpr=1
device is still blurry. It happens with satellite too but is less
noticeable. A Leaflet slippy map of the same tiles renders crisply.

One guess from maintainers: browsers may apply high-quality upscaling for
2x-scaled images, while "OpenGL would do a low-quality bilinear
interpolation." A related PR (#4443, anisotropic filtering for raster
tiles) was tried but did not fix it.

## Expected Correct Output
The center scanline of the rendered framebuffer alternates between
fully-black (0) and fully-white (255) values — the single-pixel stripe
pattern in the source texture is reproduced 1:1 on screen, matching the
crispness of the original tile image.

## Actual Broken Output
The center scanline contains mostly mid-gray values in the 64..192 range
(alternating around ~94 and ~161). Every pixel registers as a blend of
two adjacent source texels rather than an exact texel read. `extreme`
count is near 0 and `mid` count is near the full sampled width.

## Ground Truth
PR #6026 ("Align projection matrix to pixel grids to draw crisp raster
tiles") fixes this by snapping the per-tile projection matrix to the
device-pixel grid. Quoting the PR:

> This changes our projection matrix to be aligned to the pixel grid to
> fix blurry raster tiles at integer zoom levels.

The root cause lives in `Transform.calculatePosMatrix`
(src/geo/transform.js), which composes the per-tile model-view-projection
from floating-point camera position, FOV/pitch, and a worldSize-based
scale without quantising the final translation to integer device pixels.
Even at a "discrete" zoom where `tileSize == 256` device pixels, the
accumulated translation ends up with a sub-pixel residue, so fragment
centres (at `x + 0.5`) sample the tile texture at non-integer texel
coordinates. With `GL_LINEAR` mag filtering (set in
`RasterTileSource.loadTile`), each screen pixel is a 2-tap blend of two
neighbouring texels — a uniform fractional-pixel blur that looks
identical to a Gaussian softening of the tile.

> A notable discovery is that pixel alignment of our map depends on
> whether the viewport has even or odd dimensions.

— confirming the sub-pixel residue comes from projection-matrix
arithmetic, not from a wrong filter choice or a wrong tile size.

The fix adds a pixel-snap path to `calculatePosMatrix` (enabled by a new
second argument) and calls it from `drawRaster`
(src/render/draw_raster.js, `transform.calculatePosMatrix(coord.toUnwrapped(), true)`),
so each raster tile's on-screen offset is rounded to whole device pixels
before it reaches the vertex shader.

## Fix
```yaml
fix_pr_url: https://github.com/mapbox/mapbox-gl-js/pull/6026
fix_sha: 579abbad9fc8b83a2a2c1de114b2a77472bee52d
fix_parent_sha: 579abbad9fc8b83a2a2c1de114b2a77472bee52d
bug_class: framework-internal
files:
  - src/geo/transform.js
  - src/render/draw_raster.js
change_summary: >
  Adds a pixel-aligned variant of Transform.calculatePosMatrix (opt-in via
  a new boolean argument) and invokes it from drawRaster so each tile's
  projected translation is snapped to whole device pixels before rendering.
  This eliminates the sub-pixel residue in the per-tile posMatrix that was
  causing GL_LINEAR mag filtering to blend every screen pixel across two
  source texels.
```

## Difficulty Rating
4/5

## Adversarial Principles
- subtle_visual_bug: no error, no missing draw call, no obviously-wrong
  color — the image just looks slightly soft, and soft vs. crisp is a
  judgment call until you compare scanlines to the source texture.
- correct_api_usage_wrong_math: every GL call in isolation is fine
  (LINEAR filter, repeat wrap, draw call issued). The defect is purely
  in the floating-point projection matrix the shim captures as a uniform.
- environment_sensitive: at devicePixelRatio 2x+ the residue shifts and
  the blur hides; anyone developing on a Retina display won't reproduce.
- filter_red_herring: commenters correctly identify bilinear sampling as
  the proximate cause, leading to an anisotropic-filtering PR (#4443)
  that does not fix the actual defect.

## How OpenGPA Helps
A single call to `get_draw_call(...)` and inspecting the `u_matrix`
uniform exposes the translation row of the per-tile projection matrix.
Comparing `m[12]*viewport_w/2` and `m[13]*viewport_h/2` against
`round(...)` reveals the non-integer residue. A
`color_histogram_in_region` query over a central band of the framebuffer
shows the mid-tone pile-up that is invisible to perceptual inspection at
small scales — the crisp-reference vs. blurred-actual comparison becomes
a single numeric test.

## Source
- **URL**: https://github.com/mapbox/mapbox-gl-js/issues/4552
- **Type**: issue
- **Date**: 2017-04-06
- **Commit SHA**: (n/a)
- **Attribution**: Reported by @jaapster; fix by @kkaefer (PR #6026)

## Upstream Snapshot
- **Repo**: https://github.com/mapbox/mapbox-gl-js
- **SHA**: 579abbad9fc8b83a2a2c1de114b2a77472bee52d
- **Relevant Files**:
  - src/geo/transform.js
  - src/render/draw_raster.js
  - src/render/painter.js
  - src/source/raster_tile_source.js

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
    x: 8
    y: 128
    width: 240
    height: 1
  expect:
    extreme_fraction_min: 0.95   # expected: nearly all pixels are 0 or 255
  actual:
    mid_fraction_min: 0.95       # actual: nearly all pixels in [64, 192]
  channel: r
  thresholds:
    extreme_low: 16
    extreme_high: 240
    mid_low: 64
    mid_high: 192
```

## Predicted OpenGPA Helpfulness
- **Verdict**: yes
- **Reasoning**: The bug lives entirely inside a single uniform value
  (`u_matrix`) that the Tier-1 GL shim already captures verbatim. An
  agent that reads the matrix and checks whether its pixel-space
  translation is integer-aligned can diagnose the defect without needing
  framework knowledge, whereas a purely screenshot-based agent has to
  reason about a half-pixel blur that is easily mistaken for expected
  bilinear behaviour.

## Observed OpenGPA Helpfulness
- **Verdict**: ambiguous
- **Evidence**: validation skipped (--no-validate)
