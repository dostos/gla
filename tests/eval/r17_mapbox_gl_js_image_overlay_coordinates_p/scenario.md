# R17_MAPBOX_GL_JS_IMAGE_OVERLAY_COORDINATES_P: Image overlay distorted on non-rectangular corners

## User Report
I'm facing a precision issue with Mapbox GL JS when placing an image overlay
on the map with 4 corner coordinates — there is a shift from the expected
position by 50–250 m. To reach this conclusion I compared the projection of
the image to Leaflet and QGIS; both of them show the same position of the
image, but Mapbox GL JS shows a shift.

I'm using Mapbox GL JS 1.4.0 in Chrome 79.

Steps:
1. Add an image overlay using `addSource({type: "image", url: ..., coordinates: [[lon,lat] x4]})` and a raster layer.
2. Geo-reference the same image via GDAL/QGIS at the same four corners.
3. Overlay the same image with Leaflet.DistortableImage.
4. Compare — only Mapbox shows a shift, mostly on the y axis.

The shift can be up to ~250 m for an image with a 3 km swath, and is not
consistent between images. After more digging I noticed the four corners
themselves match Leaflet and QGIS — so the issue is not corner placement.
Something is wrong with the way the image is **warped** to fit those
corners. Toggling between Leaflet and Mapbox screenshots, the corners line
up but the image content does not.

I tried to debug GL JS source and everything looks normal up to the
`VertexBuffer` created from the raster `boundsArray`. I'm not very
experienced with WebGL, but my guess is some truncation is happening when
the buffer is processed on the GPU.

## Expected Correct Output
With four arbitrary geographic corners, the image content should be warped
to match a true projective view of the source image — the way QGIS,
Leaflet.DistortableImage and any other projective image viewer renders it.
Straight lines in the source image should remain straight after warping.

## Actual Broken Output
The image content is split along the diagonal of the underlying two-triangle
mesh and each half is mapped with its own affine (linear) UV transform.
Straight lines in the source image become piecewise-linear with a visible
kink along the diagonal, and texture coordinates inside the quad are off
from the projective answer — producing the apparent "shift" of features by
tens to hundreds of metres.

## Ground Truth
The corner geo-coordinates are correct. The bug is in how the raster layer
maps a texture onto a four-corner quad: image, canvas and video sources are
drawn as two triangles with simple per-triangle linear interpolation of UVs,
which is only correct when the quad is an axis-aligned rectangle (or close
to one). For arbitrary quadrilaterals, perspective-correct texture mapping
is required.

The fix author confirms this directly in the issue thread:

> This turned out to be a very interesting issue. The coordinate precision
> is correct in GL JS; the problem is with the way we do texture mapping
> between corners. … We need to overlay the image as if it were looked at
> an angle in 3D space — a perspective transformation. Instead, we're
> doing a simple linear interpolation for the texture over two triangles,
> which leads to distortion.

The Wikipedia "Affine texture mapping" section linked in that comment shows
the exact failure mode: two triangles meeting at a diagonal each get their
own affine UV map, producing a discontinuity in the texture derivatives
along the diagonal.

The merged fix (PR #11292, "Add perspective correction for image, canvas
and video sources") computes a 3×3 projective transform from the four
corner coordinates and uses it to derive a per-vertex `w` weight, which is
passed into the raster vertex shader so WebGL's standard perspective
division performs perspective-correct UV interpolation. From the PR body:

> This PR introduces perspective correction, calculating a perspective
> transform matrix given the four coordinates … and then passing a part of
> it as a uniform to the raster vertex shader so that it can properly
> calculate the `w` component (used by WebGL for texture mapping
> correction) for each of the four vertices.

## Fix
```yaml
fix_pr_url: https://github.com/mapbox/mapbox-gl-js/pull/11292
fix_sha: e7964dc867dd098dfc77619f01a8d5e0bf902e5f
fix_parent_sha: bd72c7685db8093133912462c9ccffc7267bd28b
bug_class: framework-internal
files:
  - src/render/draw_raster.js
  - src/render/program/raster_program.js
  - src/shaders/raster.vertex.glsl
  - src/source/canvas_source.js
  - src/source/image_source.js
  - src/source/video_source.js
  - debug/image-perspective.html
change_summary: >
  Adds perspective correction for image, canvas and video raster sources by
  computing a 3×3 projective transform from the four corner coordinates and
  passing the bottom row as a uniform to the raster vertex shader. The
  shader uses it to derive a per-vertex `w`, so WebGL's standard
  perspective division produces perspective-correct UV interpolation
  instead of two independent affine triangles.
```

## Difficulty Rating
4/5

## Adversarial Principles
- raw-gl-correct-but-rendering-wrong
- math-bug-not-state-bug
- two-triangle-quad-diagonal-discontinuity
- shader-uniform-missing

## How OpenGPA Helps
The shader source dump and per-draw vertex-attribute trace reveal a `vec2`
UV varying with no `w`/reciprocal companion and a 4-vertex non-rectangular
quad rendered as two triangles. Sampling pixels along the shared diagonal
versus inside each triangle shows a derivative discontinuity, which points
the agent at affine vs. perspective-correct texture mapping rather than at
GL state.

## Source
- **URL**: https://github.com/mapbox/mapbox-gl-js/issues/9158
- **Type**: issue
- **Date**: 2020-01-07
- **Commit SHA**: (n/a)
- **Attribution**: Reported by @LaithAlzyoud; diagnosis and fix by @mourner in PR #11292.

## Upstream Snapshot
- **Repo**: https://github.com/mapbox/mapbox-gl-js
- **SHA**: bd72c7685db8093133912462c9ccffc7267bd28b
- **Relevant Files**:
  - src/render/draw_raster.js
  - src/render/program/raster_program.js
  - src/shaders/raster.vertex.glsl
  - src/source/image_source.js
  - src/source/canvas_source.js
  - src/source/video_source.js

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
  region: diagonal_of_quad
  description: >
    Sample pixels along the shared diagonal of the two-triangle quad and
    compare against the texture value predicted by a projective
    (perspective-correct) UV map computed from the four corner positions.
    A mismatch beyond a small tolerance, especially with a derivative
    discontinuity across the diagonal, indicates affine-only interpolation.
  probe_points:
    - [128, 128]
    - [256, 256]
    - [384, 384]
```

## Predicted OpenGPA Helpfulness
- **Verdict**: yes
- **Reasoning**: OpenGPA exposes the exact attributes (vec2 UV, no `w`
  companion), shader source (no perspective-correction term in the
  vertex shader), and per-pixel reads — which together let the agent
  identify a missing perspective-correct texturing setup that pure JS-side
  inspection of `boundsArray` cannot.

## Observed OpenGPA Helpfulness
- **Verdict**: ambiguous
- **Evidence**: validation skipped (--no-validate)
