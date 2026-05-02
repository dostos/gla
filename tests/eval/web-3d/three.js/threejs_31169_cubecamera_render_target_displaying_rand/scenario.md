# R13: CubeCamera render target displayed as sampler2D shows wrong texture

## User Report
My scene has a cube in it. That cube's material.map is displaying a render target's texture. A CubeCamera updates that texture every N frames.

```
// Add a cube to the scene
const box = new Mesh(new BoxGeometry(), new MeshStandardMaterial())
const rt = new WebGLCubeRenderTarget()
// Visualize the render target
box.map = rt.texture;
```

You can see the texture updating, but if you zoom around a bit, at a certain angle the texture displayed swaps to just be the plant texture — which is not supplied to the box material in any way.

What exactly is happening here? It seems like when the object intersects the camera frustum's near plane it may cause this behavior.

r176, Chrome, Linux desktop.

## Expected Correct Output
The quad sampling `uTex` (a `sampler2D`) displays the contents that were uploaded to the texture object bound to unit 0. The author's mental model is "the texture is the texture — it doesn't matter which bind point you use to read it."

## Actual Broken Output
The center pixel is black (0,0,0) instead of one of the six face colors, and `glGetError` returns `0x0502` (`GL_INVALID_OPERATION`). On WebGL the same condition is reported as:

> WebGL: INVALID_OPERATION: bindTexture: textures can not be used with multiple targets

In three.js the observed symptom is that the cube appears textured with whatever *other* 2D texture happened to be left bound on the unit (the "plant texture" the reporter never passed to the box material).

## Ground Truth
A GL texture object acquires a target the first time it is bound with a non-zero target. Once `envTex` has been bound as `GL_TEXTURE_CUBE_MAP` and populated with `glTexImage2D(GL_TEXTURE_CUBE_MAP_POSITIVE_X + i, …)`, rebinding it with `glBindTexture(GL_TEXTURE_2D, envTex)` is an error:

> WebGL: INVALID_OPERATION: bindTexture: textures can not be used with multiple targets

The failing bind is a no-op for the TEXTURE_2D slot on that unit. The draw therefore samples whatever texture was previously bound to TEXTURE_2D on unit 0 (in three.js, a prior material's map — the reporter's "plant texture"; in our minimal repro, the default texture 0, which samples as black). This is maintainer Mugen87's point in the thread — "It is invalid to assign a cube render target … to the `map` property of a material" — and the underlying GL rule is that texture objects are *target-typed*, not untyped storage.

The fix in application code is to render the cube render target through a cube sampler (`envMap`, or a custom shader using `samplerCube`) rather than rebinding it as `map`.

## Difficulty Rating
3/5

## Adversarial Principles
- Plausible-sounding user mental model ("a texture is a texture")
- Silent failure path: the INVALID_OPERATION from `glBindTexture` is easy to miss in logs, and the draw call still "succeeds" with stale unit state
- Cross-state interaction: the visible pixels depend on *what was previously bound* to the 2D slot, not on anything in the current draw call's own setup
- View-dependent appearance in the original three.js case (frustum culling changes which material binds last) misleads the reporter toward camera/near-plane hypotheses

## How OpenGPA Helps
OpenGPA's per-draw GL state snapshot records the bound texture object per texture unit *together with each object's creation target*. A query like `/api/v1/frames/current/draw_calls/N/textures` will show texture unit 0 reporting an object whose own target is `TEXTURE_CUBE_MAP` while the sampler at the same unit expects `TEXTURE_2D`, plus the `INVALID_OPERATION` from the preceding `glBindTexture` in the error log. That single view collapses the three-layer confusion (user code, three.js material system, GL binding rules) into one observable state conflict.

## Source
- **URL**: https://github.com/mrdoob/three.js/issues/31169
- **Type**: issue
- **Date**: 2026-04-20
- **Commit SHA**: (n/a)
- **Attribution**: Reported by three.js user; diagnosis by @Mugen87 in the thread

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
  draw_call_index: 0
  texture_unit: 0
  sampler_uniform: uTex
  expected_target: GL_TEXTURE_2D
  observed_object_target: GL_TEXTURE_CUBE_MAP
  expected_gl_error: GL_INVALID_OPERATION
  expected_center_pixel_rgba: [0, 0, 0, 255]
```

## Predicted OpenGPA Helpfulness
- **Verdict**: yes
- **Reasoning**: The root cause is a mismatch between a texture object's creation-time target and its sampling-time target. This is invisible in source code (the JS/GL call sequence looks symmetrical) but trivially visible in captured GL state that tracks per-object target alongside per-unit binding. OpenGPA's Tier 1 draw-call state dump surfaces this directly, whereas a baseline agent armed only with source and screenshots has to reason from the reporter's misleading "near-plane" hypothesis and the buried WebGL warning.

## Observed OpenGPA Helpfulness
- **Verdict**: ambiguous
- **Evidence**: validation skipped (--no-validate)
