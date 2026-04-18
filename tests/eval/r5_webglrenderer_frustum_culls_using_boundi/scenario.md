# R5_WEBGLRENDERER_FRUSTUM_CULLS_USING_BOUNDI: Transparent depth sort uses object origin instead of bounding-sphere center

## Bug
The renderer sorts transparent draw calls by each object's origin
(`matrixWorld` translation) rather than by the world-space center of its
bounding sphere. When modelers "apply" or "freeze" transforms, the origin
no longer reflects where the geometry actually lives, so two overlapping
transparent objects can be drawn in the wrong back-to-front order,
producing incorrectly blended pixels.

## Expected Correct Output
With the two transparent quads blended back-to-front by their bounding-
sphere centers (B at world z=-1 first, then A at world z=+1), the central
overlap region ends up red-dominant — roughly `(R≈0.50, G≈0.00, B≈0.25)`.

## Actual Broken Output
With the buggy origin-based sort (A origin z=-2 drawn first, B origin z=+2
drawn last), the central overlap region is instead blue-dominant —
roughly `(R≈0.25, G≈0.00, B≈0.50)`. Red and blue channels are swapped
relative to the correct result.

## Ground Truth Diagnosis
The reporter observes that the renderer *culls* by bounding sphere but
*sorts* by origin, citing the relevant line in `WebGLRenderer.js`:

> Wouldn't it be more consistent to also sort by bounding-sphere-center?
> Then transparent objects don't all need to be centered around their
> origin.

PR #25913 ("WebGLRenderer: Sort on bounding sphere center, not origin")
confirms the root cause in its description:

> It's common practice for modelers to "apply" or "freeze" transforms,
> setting object origins to zero, which creates a problem for our default
> sort. By sorting on the center of an object's bounding sphere, rather
> than its origin, we may improve the odds of drawing triangles in the
> intended order.

The companion PR #25974 ("WebGLRenderer: Use correct bounding volume for
depth sorting") generalizes the fix. Both landed in the `dev` branch and
resolve this issue along with #25820 and #25960.

## Difficulty Rating
3/5

## Adversarial Principles
- transform_origin_divorced_from_geometry_center
- transparent_sort_correctness
- blend_order_dependent_output

## How OpenGPA Helps
An agent can enumerate transparent draw calls in issue order via
`list_draw_calls` and cross-check each one's model-space bounding-sphere
center against its model-matrix translation. When these disagree on view-
space Z ordering for two overlapping draws, the frame-capture backend
exposes both the emission order and the per-draw transforms, making the
sort-key mismatch directly observable instead of inferred from the final
pixel.

## Source
- **URL**: https://github.com/mrdoob/three.js/issues/13857
- **Type**: issue
- **Date**: 2018-04-03
- **Commit SHA**: (n/a)
- **Attribution**: Reported on three.js issue tracker; fixed by PRs #25913 and #25974.

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
  region: { x: 224, y: 224, w: 64, h: 64 }
  expected:
    r_range: [0.40, 0.60]
    g_range: [0.00, 0.05]
    b_range: [0.20, 0.30]
  actual:
    r_range: [0.20, 0.30]
    g_range: [0.00, 0.05]
    b_range: [0.40, 0.60]
  note: >
    Two transparent quads with equal 50% alpha overlap at the center of a
    512x512 framebuffer. Correct back-to-front sort yields a red-dominant
    blend; the buggy origin-based sort yields a blue-dominant blend.
```

## Predicted OpenGPA Helpfulness
- **Verdict**: yes
- **Reasoning**: The bug is purely about the order of two transparent
  draw calls. Inspecting the GL command stream (draw-call enumeration +
  per-draw model matrix and bound vertex extents) exposes the mismatch
  between origin-based ordering and geometry-center ordering without
  requiring any higher-level scene-graph knowledge.

## Observed OpenGPA Helpfulness
- **Verdict**: ambiguous
- **Evidence**: validation skipped (--no-validate)
