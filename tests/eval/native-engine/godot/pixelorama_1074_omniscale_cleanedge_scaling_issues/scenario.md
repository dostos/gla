# R12: OmniScale/CleanEdge scaler samples only the top-left pixel

## User Report
**Pixelorama version:**
1.0.1 and commit 9c170ee5a02984537780766c23f4038e3875afb1 also attempted on itch.io web build

**OS/device including version:**
Arch Linux native, and FlatPak with Nvidia GTX 1050 Ti mobile

**Issue description:**
OmniScale, and CleanEdge scaling only grabs top left pixel of image for scaling

**Steps to reproduce:**

1. Open the scale image menu.
2. Set interpolation to OmniScale, or CleanEdge.
3. Set Width/Height to a value other than the original size
4. Press 'OK'

## Expected Correct Output
A 256x256 upscale of the 4x4 test image: a recognisable pattern where the
top-left 64x64 region is red and the rest is a green/blue checkerboard.

## Actual Broken Output
A solid red 256x256 framebuffer — the entire output is the colour of texel
`(0, 0)` of the source texture.

## Ground Truth
A fullscreen image-scaling pass that applies a `mat2` UV transform in the
fragment shader never has its transformation uniform written by the CPU.
In GLSL the uniform therefore defaults to the zero matrix, so every fragment
ends up sampling the source texture at `(0, 0)`. The rescaled image comes out
as a flat fill of the source's top-left texel.

The fragment shader declares `uniform mat2 transformation_matrix;` without a
default value, and the scale code path for OmniScale/CleanEdge never calls
the equivalent of `glUniformMatrix2fv` for it. Per the GLSL spec an unset
program uniform is initialised to zero, so `transformation_matrix * v_uv` is
`vec2(0.0, 0.0)` for every fragment and `texture(src_tex, vec2(0))` returns
the top-left texel. Fix commit `3113459` (`Fix #1074`) patches the upstream
shader `src/Shaders/Effects/Rotation/CommonRotation.gdshaderinc` with a
one-line change:

> `-uniform mat2 transformation_matrix;`
> `+uniform mat2 transformation_matrix = mat2(vec2(1.0, 0.0), vec2(0.0, 1.0));`

i.e. it supplies an identity default at the shader layer so the missing CPU
write no longer collapses the UVs to the origin (see commit
3113459224232f9ad51ef10abb12c22c28a8676a).

## Difficulty Rating
3/5

## Adversarial Principles
- silent-zero uniform default
- uniform declared but never written by the CPU
- symptom (solid fill) is far away from the cause (transform matrix)

## How OpenGPA Helps
An agent that asks OpenGPA for the uniform values bound to the draw call sees
`transformation_matrix = mat2(0.0)` next to a `texture(...)` sampler read.
That single fact — "the UV transform is the zero matrix" — collapses the
search from the entire scaling pipeline to one unwritten uniform, and the
near-uniform red framebuffer histogram corroborates that every fragment
sampled the same source texel.

## Source
- **URL**: https://github.com/Orama-Interactive/Pixelorama/issues/1074
- **Type**: issue
- **Date**: 2024-08-11
- **Commit SHA**: 3113459224232f9ad51ef10abb12c22c28a8676a
- **Attribution**: Reported against Pixelorama 1.0.1; fixed by @OverloadedOrama

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
  expected_dominant_color: null
  actual_dominant_color: [255, 0, 0]
  min_fraction: 0.95
  region: full
```

## Upstream Snapshot
- **Repo**: https://github.com/Orama-Interactive/Pixelorama
- **SHA**: 9c170ee5a02984537780766c23f4038e3875afb1
- **Relevant Files**:
  - src/Shaders/Effects/Rotation/CommonRotation.gdshaderinc  # parent of closing commit 3113459 (identity default added to transformation_matrix)
  - src/Shaders/Effects/Rotation/OmniScale.gdshader
  - src/Shaders/Effects/Rotation/cleanEdge.gdshader

## Predicted OpenGPA Helpfulness
- **Verdict**: yes
- **Reasoning**: The root cause is a single uniform value that diverges from
  the developer's mental model; OpenGPA's per-draw uniform dump surfaces the
  zero matrix directly. Without OpenGPA the symptom (solid colour) looks
  like a texture-binding or blend-state problem, which leads investigation
  away from the shader uniform.

## Observed OpenGPA Helpfulness
- **Verdict**: ambiguous
- **Evidence**: validation skipped (--no-validate)
