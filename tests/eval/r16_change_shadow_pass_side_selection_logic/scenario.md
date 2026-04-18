# R16_CHANGE_SHADOW_PASS_SIDE_SELECTION_LOGIC: Shadow pass culls the wrong face side

## Bug
During the shadow-map depth pass, the renderer enables front-face culling. For a caster whose visible surface to the light is its front face (the common case for closed-mesh surfaces oriented toward the light), this discards the exact triangles that should populate the shadow map. Downstream, the lit pass samples the shadow map and concludes those surfaces never occluded the light, producing missing shadows or peter-panning.

## Expected Correct Output
The shadow-caster triangle (CCW as seen from the light) rasterizes into the depth target, and the center pixel of the diagnostic framebuffer is red (rendered caster). Equivalently: a shadow-map pass should retain front-facing casters so the lit pass can compare against them.

## Actual Broken Output
The triangle is culled before rasterization because its CCW winding marks it as a front face and `glCullFace(GL_FRONT)` discards exactly those. The center pixel is black (clear color); the caster contributes nothing to the depth target, so downstream the surface is treated as unshadowed.

## Ground Truth Diagnosis
The upstream issue pins the visible symptoms to shadow-pass face selection:

> Shadow rendering appears to use an incorrect face side in some cases. Objects that are not visible to the light source may still cast shadows, while objects oriented toward the light source may fail to cast them correctly.

and

> 1) Objects that should cast shadows sometimes fail to do so.
> 2) Peter-panning artifacts in certain scenarios.

The reporter's closing comment names the regressing change directly:

> front face culling was introduced in the last release, so some users can observe unexpected artifacts.

Root cause: the depth pass unconditionally enables front-face culling (a common self-shadow-acne mitigation), which is incorrect for casters whose front face is what the light sees. The minimal program reproduces this by enabling `GL_CULL_FACE` with `glCullFace(GL_FRONT)` before drawing a CCW front-facing triangle; the triangle is dropped, mirroring the lost depth contribution in the shadow pass.

## Difficulty Rating
3/5

## Adversarial Principles
- upstream-state-dictates-downstream-absence
- plausible-default-wrong-for-case
- no-gl-error-silent-cull

## How OpenGPA Helps
An OpenGPA query like "what was `GL_CULL_FACE_MODE` during the depth-only draw into the shadow FBO, and how many primitives survived clipping vs. were culled?" immediately surfaces `GL_FRONT` with zero surviving primitives for the caster. That is directly diagnostic of wrong-side selection — far faster than guessing between bias, orientation, or matrix mistakes.

## Source
- **URL**: https://github.com/mrdoob/three.js/issues/33172
- **Type**: issue
- **Date**: 2025-10-14
- **Commit SHA**: (n/a)
- **Attribution**: Reported on three.js issue tracker; closed by reporter with `shadowSide` workaround

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
  region: center_pixel
  expected_dominant: "red (front-facing shadow caster rasterized into target)"
  actual_dominant: "black (caster culled by glCullFace(GL_FRONT) during shadow pass)"
  tolerance: "red channel > 128 ⇒ correct; red channel ~0 ⇒ bug"
```

## Predicted OpenGPA Helpfulness
- **Verdict**: yes
- **Reasoning**: The bug is a single piece of pipeline state (`GL_CULL_FACE_MODE = GL_FRONT`) causing silent primitive loss during a specific pass. OpenGPA's per-draw state + primitive-count inspection reveals both the offending state and its downstream effect (zero depth writes from a caster expected to write many), without requiring the user to guess the culprit among bias, winding, or matrix candidates.

## Observed OpenGPA Helpfulness
- **Verdict**: ambiguous
- **Evidence**: validation skipped (--no-validate)
