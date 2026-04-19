# R6: WebGPU transparent texture casts opaque shadow

## User Report
### Description

v0.180 WebGPU

Using transparent texture map on a MeshBasicMaterial with shadows causing issues as shadow map is no longer transparent

### Reproduction steps

1. mesh with alpha texture should drop shadow
2. there should be a mesh to receive shadow
3. three webgpu v0.180

### Code

see jsfiddle

### Live example

* [v0.180 WebGLRenderer](https://jsfiddle.net/10w7x6uc/)
* [v0.180 WebGPURenderer](https://jsfiddle.net/yqokvb2u/9/)

### Version

v1.180

### Device

Desktop

### Browser

Chrome

### OS

ChromeOS

## Expected Correct Output
The shadow on the receiver matches the opaque silhouette of the alpha texture
(e.g. a circular shadow for a circular alpha mask). This is what
WebGLRenderer produces for the same scene.

## Actual Broken Output
The shadow on the receiver is the full rectangular footprint of the casting
quad, with no respect for the texture's alpha channel.

## Ground Truth
A `MeshBasicMaterial` whose color comes from an alpha-channel texture casts a
shadow whose silhouette ignores the texture's alpha. The transparent regions
of the texture still occlude light, so the shadow is a solid rectangle (the
geometry's bounding quad) instead of the textured cutout shape.

The bug is specific to WebGPURenderer in three.js v0.180. WebGLRenderer
renders the same scene correctly (see the side-by-side jsfiddles linked in
the issue), so the geometry, lights, and material configuration are not at
fault. The divergence is in the WebGPU backend's shadow pass: it does not
sample the material's alpha source (`alphaMap` / map alpha channel) and does
not perform the alpha-test discard that the WebGL backend's shadow shader
performs. As a result every fragment of the casting geometry writes to the
shadow map regardless of texture alpha.

The original reporter confirmed the regression was repaired in the next
release:

> while doing jsfiddle examples I discovered it got fixed somewhere in v0.181

The maintainers did not post a written root-cause statement on the issue, so
the diagnosis is grounded in (a) the WebGL/WebGPU output divergence
demonstrated by the two jsfiddles in the issue body and (b) the reporter's
confirmation that v0.181 contains the fix. The minimal C reproducer above
ports the *pattern* — a shadow fragment shader that ignores texture alpha —
into raw GL so OpenGPA can detect it without a WebGPU backend.

## Difficulty Rating
3/5

## Adversarial Principles
- Backend-specific divergence (WebGL correct, WebGPU wrong)
- Multi-pass dependency (shadow pass shader differs from lit pass shader)
- Silent correctness bug — no GL error, no validation warning

## How OpenGPA Helps
The query
`/api/v1/frames/current/draw_calls/{shadow_pass}/shaders` reveals that the
shadow pass's fragment shader does not bind or sample the alpha texture that
the lit pass uses, even though both passes draw the same geometry. Comparing
shader uniforms across the two passes (`compare_frames` style) makes the
omission of the alpha sampler in the shadow pass immediately visible.

## Source
- **URL**: https://github.com/mrdoob/three.js/issues/32481
- **Type**: issue
- **Date**: 2025-10-18
- **Commit SHA**: (n/a)
- **Attribution**: Reported by the issue's original poster on three.js#32481

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
  pass: shadow_map
  expected_sampler_bound: alpha_texture
  observed: no_alpha_sampler_bound
  consequence: shadow_map_silhouette_equals_geometry_bbox_not_texture_alpha
```

## Predicted OpenGPA Helpfulness
- **Verdict**: yes
- **Reasoning**: The bug is a missing texture binding / missing discard in
  one specific pass. OpenGPA's per-draw-call shader and uniform inspection
  exposes exactly this kind of "shader X doesn't sample what shader Y
  samples" divergence without requiring the agent to read the framework's
  shader-stitching pipeline.

## Observed OpenGPA Helpfulness
- **Verdict**: ambiguous
- **Evidence**: validation skipped (--no-validate)
