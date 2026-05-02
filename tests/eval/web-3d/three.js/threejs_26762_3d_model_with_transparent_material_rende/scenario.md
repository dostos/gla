# R3: 3D model with transparent material rendered incorrectly

## User Report

Some parts of the model have z-fighting/stitching artifacts, for example on the legs. Is this a bug?

See attached wasp GLTF demo. The legs and some other areas show visible stitching/z-fighting where the geometry overlaps.

Version: r155

## Ground Truth

Opaque overlapping geometry is rendered with `glDepthMask(GL_FALSE)` while
depth testing is still enabled. Because no depth values are written, the
depth buffer stays at its cleared value during the sequence, and later
draws' fragments always pass the depth test — regardless of whether they
are actually behind earlier-drawn surfaces. The result is incorrect
occlusion: whichever primitive was submitted last wins in every overlap
region.

The upstream diagnosis:

> This is a modeling issue. For some reasons, `depthWrite` is disabled
> for the legs materials. Enabling it solves the rendering issues.

In three.js, `material.depthWrite` maps to `gl.depthMask()`. When a
material has `depthWrite: false` but is treated as opaque (drawn during
the opaque pass, without back-to-front sorting), overlapping primitives
lose correct occlusion: whichever draw runs last writes color, because
no prior draw wrote depth for the depth test to reject against. The fix
in three.js is to enable `depthWrite` on those materials so `glDepthMask`
stays `GL_TRUE` during the draw.

## Expected Correct Output
Two overlapping triangles. The green triangle (T1, front, z=-0.4) was
drawn first; the red triangle (T2, behind, z=+0.4) was drawn second.
Where they overlap, the green triangle should occlude the red one. The
central overlap band should be **green**.

## Actual Broken Output
In the central overlap band the red triangle shows through in front of
the green one — i.e., the later-submitted but farther-away primitive
wins. On real meshes with many interleaved overlapping primitives this
manifests as the z-fighting / stitching pattern seen on the wasp model's
legs and hair.

## Difficulty Rating
3/5

## Adversarial Principles
- hidden_pipeline_state
- draw_order_dependence
- invisible_state_toggle

## How OpenGPA Helps
OpenGPA's per-draw state inspection surfaces `depth_mask = GL_FALSE` on
the offending draw calls while `depth_test = GL_TRUE` — a combination
that is almost always wrong for opaque geometry. The agent can query
`/api/v1/frames/current/draws/{i}` and compare the depth mask on each
draw against neighboring draws to spot the discrepancy without having
to guess from pixels alone.

## Source
- **URL**: https://github.com/mrdoob/three.js/issues/26762
- **Type**: issue
- **Date**: 2023-09-15
- **Commit SHA**: (n/a)
- **Attribution**: Reported by @pailhead on three.js; diagnosed by @Mugen87

## Tier
core

## API
opengl

## Framework
none

## Bug Signature
```yaml
type: unexpected_state_in_draw
spec:
  draw_call_index: 1
  state: depth_mask
  expected: true
  actual: false
  context:
    depth_test: true
    depth_func: GL_LESS
    reason: "opaque overlapping geometry drawn with depth writes disabled"
```

## Upstream Snapshot
- **Repo**: https://github.com/mrdoob/three.js
- **SHA**: 18ae441f1cf275971bcdcef25be03f6f67965690
- **Relevant Files**:
  - src/renderers/WebGLRenderer.js  # default-branch SHA at issue close (no PR; modeling-only workaround); (inferred)
  - src/renderers/webgl/WebGLState.js
  - src/materials/Material.js

## Predicted OpenGPA Helpfulness
- **Verdict**: yes
- **Reasoning**: The bug is invisible from shader source and vertex data —
  it lives entirely in per-draw pipeline state. OpenGPA's raw capture of
  `glDepthMask` state per draw call directly exposes the discrepancy.
  Without OpenGPA, an agent would have to infer depthMask state from
  pixel patterns across many frames; with OpenGPA one query answers it.

## Observed OpenGPA Helpfulness
- **Verdict**: ambiguous
- **Evidence**: validation skipped (--no-validate)
