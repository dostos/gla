# R14_USING_QUADMESH_WITH_A_CUSTOM_VERTEXNODE_: Custom vertex positions emitted in clockwise order get culled

## Bug
The program defines a triangle with positions `(-1,-1,0)`, `(0,1,0)`, `(1,-1,0)` —
the exact same sequence the upstream user supplied to their custom `vertexNode`.
Viewed from the default +Z camera, this sequence is clockwise. Backface culling
is enabled with the default CCW front-face convention, so the (only) triangle is
classified as back-facing and discarded. The resulting frame is blank.

## Expected Correct Output
A solid red triangle covering most of the 256x256 framebuffer, since the
fragment shader unconditionally writes `vec4(1,0,0,1)`.

## Actual Broken Output
An entirely black framebuffer — the draw call executes but the triangle is
culled before rasterization, so no fragments are shaded.

## Ground Truth Diagnosis
The upstream user's custom vertex positions are emitted in clockwise order
relative to the camera, which collides with the renderer's CCW-front-face /
back-face-cull default. The maintainer confirms this directly:

> The winding order of your vertices is wrong. Try it with:
> https://jsfiddle.net/Lde241jr/2/

The linked fix simply reverses the vertex order, turning the triangle into a
CCW (front-facing) primitive so it survives culling. No shader or pipeline
change is needed — only the winding. This C reproducer ports the same vertex
triple and the same default pipeline state (cull back, front = CCW), so the
frame comes out black for the same reason.

## Difficulty Rating
2/5

## Adversarial Principles
- silent_culling_looks_like_missing_draw
- default_pipeline_state_hides_the_cause
- winding_convention_mismatch

## How GLA Helps
A GLA query for per-draw pipeline state on the single `glDrawArrays` call
reveals `GL_CULL_FACE = enabled`, `GL_CULL_FACE_MODE = GL_BACK`, and
`GL_FRONT_FACE = GL_CCW`, while a vertex-ordering check on the supplied
positions shows a negative signed 2D area (clockwise) in clip space. That
combination pinpoints winding/culling as the cause of the blank frame without
the user having to guess whether the draw was issued at all.

## Source
- **URL**: https://github.com/mrdoob/three.js/issues/30474
- **Type**: issue
- **Date**: 2025-02-06
- **Commit SHA**: (n/a)
- **Attribution**: Reported by @ganqian22; diagnosed in comment by a three.js maintainer.

## Tier
core

## API
opengl

## Framework
none

## Bug Signature
```yaml
type: framebuffer_dominant_color
spec:
  region: full
  expected_dominant_rgb: [255, 0, 0]
  actual_dominant_rgb: [0, 0, 0]
  tolerance: 16
  min_coverage: 0.60
```

## Predicted GLA Helpfulness
- **Verdict**: yes
- **Reasoning**: The bug is a classic "silent" failure — the draw is issued,
  no GL error is raised, and the framebuffer is simply empty. A human staring
  at the shader/source will not see the problem. GLA's ability to report
  effective pipeline state at the draw call (cull face + front-face mode) plus
  a winding check on the submitted vertices turns an invisible cull into a
  one-line diagnosis: "triangle winding is CW but front-face is CCW with back
  culling enabled."

## Observed GLA Helpfulness
- **Verdict**: ambiguous
- **Evidence**: validation skipped (--no-validate)
