# R4_V7_ISSUE_WITH_CUSTOM_POINTS_SHADER_THREE: MRT normal attachment garbled when fragment shader omits location=1 output

## User Report
### Description of the bug

When enabling gbuffer normals in the render pipeline, custom Points (implemented with THREE.ShaderMaterial) and default THREE.SpriteMaterial objects fail to render and become invisible.

### To reproduce

Enable NORMAL pass to a scene that contains a SpriteMaterial or Points using ShaderMaterial. Everything renders properly except the sprite or points.

### Workaround

Adding the following to the SpriteMaterial onBeforeCompile or directly to the custom Points fragment shader make the sprites or points render properly:

```
// Variable declarations
layout(location = 1) out vec3 gBufferNormal;
// In main
gBufferNormal = normalize(vWorldNormal);
```

### Expected behavior

I made a custom effect to add SSAO to the RenderPipeline which requires the GBuffer NORMAL pass to be enabled, and everything works as expected, except the Points and SpriteMaterials don't render.

### Library versions used

 - Three: 0.176.0
 - Post Processing: 7.0.0-beta.11

### Desktop

 - OS: Windows
 - Browser: Chrome 137.0.7151.104
 - Graphics hardware: NVIDIA

## Expected Correct Output
After the draw, attachment 1 in the triangle footprint should either retain
the clear value `(128, 128, 255)` (encoded up-normal) or a shader-written
normal. Geometry that writes to a normal G-Buffer should produce a valid
normal at every rasterized pixel.

## Actual Broken Output
Attachment 1 inside the triangle footprint is overwritten with undefined
values (driver-dependent; commonly solid black / uninitialized register
state). Points/Sprites become invisible in the final composite because
downstream effects sample nonsense from the normal buffer.

## Ground Truth
A framebuffer is bound with two color attachments (color + gBufferNormal) and
`glDrawBuffers` enables both. The fragment shader, however, only declares
`layout(location=0) out vec4 out_Color`. Rasterized pixels in attachment 1 end
up undefined instead of keeping the cleared "up" normal (or a shader-computed
normal), which downstream passes (SSAO, decals) misread.

The upstream maintainer confirms that non-PBR materials such as
`PointsMaterial` and `SpriteMaterial` were missing the G-Buffer output
declarations when the `NORMAL` G-Buffer channel was enabled:

> Only non-PBR materials like `PointsMaterial` should be affected. These
> materials don't define any of the variables that are expected to be
> present in PBR materials.

The reporter's workaround confirms the same root cause:

> Adding the following to the SpriteMaterial onBeforeCompile or directly to
> the custom Points fragment shader make the sprites or points render
> properly:
> `layout(location = 1) out vec3 gBufferNormal;`
> `gBufferNormal = normalize(vWorldNormal);`

The fix (v7.0.0-beta.13) injects default output declarations library-side for
all materials so that the fragment outputs always match the enabled draw
buffers.

## Difficulty Rating
3/5

## Adversarial Principles
- silent_output_mismatch
- mrt_partial_write
- shader_vs_fbo_contract

## How OpenGPA Helps
OpenGPA exposes the draw call's bound framebuffer attachments, the active
`glDrawBuffers` set, and the fragment shader source. An agent can
cross-reference the two and immediately see that the shader declares one
output while two draw buffers are enabled, pinpointing the missing
`layout(location=1)` declaration without guessing.

## Source
- **URL**: https://github.com/pmndrs/postprocessing/issues/708
- **Type**: issue
- **Date**: 2025-06-13
- **Commit SHA**: (n/a)
- **Attribution**: Reported by @japhiaolson; diagnosed by @vanruesc

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
  attachment: color1
  region:
    x: 96
    y: 64
    w: 64
    h: 64
  expected_rgb: [128, 128, 255]
  tolerance: 8
  rule: "Pixels inside the rasterized triangle in COLOR_ATTACHMENT1 must retain the cleared 'up' normal (128,128,255); deviation indicates undefined writes from a shader missing a location=1 output."
```

## Upstream Snapshot
- **Repo**: https://github.com/pmndrs/postprocessing
- **SHA**: 17762f08864484817f47ad53e0d4c596e76eb5b2
- **Relevant Files**:
  - src/effects/GBufferConfig.ts  # default-branch SHA at issue close (fix shipped in v7.0.0-beta.13); (inferred)
  - src/materials/PointsMaterial.ts
  - src/materials/SpriteMaterial.ts
  - src/passes/GeometryPass.ts

## Predicted OpenGPA Helpfulness
- **Verdict**: yes
- **Reasoning**: The bug is a mismatch between static draw-time state (FBO
  draw-buffer count) and shader-declared outputs. Both are directly
  inspectable through OpenGPA's per-draw snapshot. A baseline agent looking
  only at the rendered frame sees "points invisible" with no obvious cause;
  an OpenGPA-equipped agent can diff outputs vs. enabled attachments and name
  the missing declaration in one query.

## Observed OpenGPA Helpfulness
- **Verdict**: ambiguous
- **Evidence**: validation skipped (--no-validate)
