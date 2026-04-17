# R1_WEBGL_BACKEND_INSTANCENODE_UBO_EXCEEDS_G: InstancedMesh UBO exceeds GL_MAX_UNIFORM_BLOCK_SIZE

## Bug
The renderer declares a uniform block (`InstanceBlock { mat4 matrices[N]; }`) sized against a hardcoded assumption (~64 KB worth of instances) instead of the driver-reported `GL_MAX_UNIFORM_BLOCK_SIZE`. On drivers whose actual limit is smaller, shader linking fails and the instanced draw silently renders nothing.

## Expected Correct Output
A row of small orange triangles (8 instances) rendered over the dark-blue clear color. The center pixel should be approximately `(255, 76, 25)` where the triangle fan covers it.

## Actual Broken Output
Program link fails with a "Size of uniform block … exceeds GL_MAX_UNIFORM_BLOCK_SIZE" message; the subsequent `glUseProgram`/`glDrawArraysInstanced` is a no-op (GL_INVALID_OPERATION). The framebuffer remains the dark-blue clear color; the center pixel reads approximately `(0, 51, 102)`.

## Ground Truth Diagnosis
The upstream code hardcoded a 1000-matrix threshold, assuming every WebGL2 device exposes a ~64 KB UBO limit. Chrome/ANGLE on macOS reports only the spec minimum, so a UBO sized for the three.js threshold trivially overflows:

> Chrome/ANGLE on macOS reports `GL_MAX_UNIFORM_BLOCK_SIZE = 16384` bytes (the WebGL2 spec minimum). Any `InstancedMesh` with more than **256 instances** (256 × 64 bytes = 16,384) will silently fail to render on Chrome because the `NodeBuffer` UBO exceeds the device limit.

The driver surfaces the failure only at link time:

> shader fails with `Size of uniform block NodeBuffer_XXXXX in VERTEX shader exceeds GL_MAX_UNIFORM_BLOCK_SIZE (16384)`. The mesh does not render.

The correct approach is to query the device limit and derive the UBO/attribute cutoff dynamically:

> Query `GL_MAX_UNIFORM_BLOCK_SIZE` at init and compute the threshold dynamically instead of hardcoding 1000.

## Difficulty Rating
3/5

## Adversarial Principles
- silent-driver-limit-violation
- cross-browser-divergent-defaults
- hardcoded-capability-assumption
- link-stage-failure-masquerades-as-missing-geometry

## How GLA Helps
A GLA query for "why is my InstancedMesh not drawing on Chrome?" should surface the program link status and the driver infolog containing the `GL_MAX_UNIFORM_BLOCK_SIZE` diagnostic, pointing directly at the oversized UBO instead of the usual suspects (matrix uploads, frustum culling, attribute bindings).

## Source
- **URL**: https://github.com/mrdoob/three.js/issues/33009
- **Type**: issue
- **Date**: 2025-09-18
- **Commit SHA**: (n/a)
- **Attribution**: Reported by a three.js user (issue description authored via Claude); triaged against r182 source. Noted as already addressed on `dev` by PR #32949 in r183dev.

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
  expected_dominant_rgb: [255, 76, 25]
  actual_dominant_rgb: [0, 51, 102]
  tolerance: 30
  rationale: "Instanced draw should cover visible area with orange triangles; link failure leaves clear color dominant."
```

## Predicted GLA Helpfulness
- **Verdict**: yes
- **Reasoning**: The failure mode is a link error whose text names the exact root cause (`exceeds GL_MAX_UNIFORM_BLOCK_SIZE`), but application code that ignores `GL_LINK_STATUS` or buries the infolog will show only a missing mesh. A GLA query that inspects program link status, info log, and `GL_MAX_UNIFORM_BLOCK_SIZE` versus declared UBO size will deterministically identify the mismatch — far more directly than visual or geometry-level diagnostics.

## Observed GLA Helpfulness
- **Verdict**: ambiguous
- **Evidence**: validation skipped (--no-validate)
