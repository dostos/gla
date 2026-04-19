# R4_COLOR_MANAGEMENT_CHANGES_IN_THREE: sRGB texture uploaded as linear while framebuffer encodes sRGB

## User Report
I've seen changes landing on THREE lately related to color management that seemed change A-Frame default behavior

[A-Frame 1.4.2 on THREE r147](https://aframe.io/aframe/examples/showcase/ui/)

[A-Frame master on THREE r152](https://glitch.com/edit/#!/hammerhead-rare-skipjack?path=info-message.js%3A113%3A0)

@donmccurdy Sorry to bother. I went through the changelog. There are tons of changes and couldn't make it complete sense. Do you have a quick summary of the changes we have to do to get the same results than r147? Thanks so much

## Expected Correct Output
A 256×256 window filled with mid-gray matching the texture input:
framebuffer RGB ≈ (128, 128, 128). This is what you get when the texture is
uploaded as `GL_SRGB8` (hardware decodes 128 → ~0.216 linear) or when
`GL_FRAMEBUFFER_SRGB` is disabled.

## Actual Broken Output
A 256×256 window filled with a distinctly brighter gray: framebuffer RGB ≈
(188, 188, 188). The sampled value 128/255 ≈ 0.502 is treated as linear, then
sRGB-encoded on output, lifting it to ~0.741.

## Ground Truth
A diffuse texture containing sRGB-encoded bytes is uploaded with a linear
internal format (`GL_RGB8`) while `GL_FRAMEBUFFER_SRGB` is enabled. The shader
samples the sRGB bytes as if they were linear values; the framebuffer then
gamma-encodes those values to sRGB on write. The effective result is a
double-encoded image — everything is noticeably brighter than the input
texture, the classic "washed out" look A-Frame scenes exhibited after the
three.js r152 color management changes made sRGB output encoding the default.

The three.js r152 release made `renderer.outputColorSpace = SRGBColorSpace`
the default, so the final blit now gamma-encodes linear values to sRGB. Apps
that relied on the pre-r152 behavior never tagged their diffuse textures as
sRGB and never had to: the shader just sampled the bytes and they went to the
screen as-is. Post-r152, diffuse textures must declare `texture.colorSpace =
SRGBColorSpace` so three.js uploads them as an sRGB-decoding internal format
(equivalently, selects an `sRGB` sampler). Without that tag, the shader
interprets sRGB-encoded bytes as linear values, and the output encoding
doubles the gamma.

The A-Frame maintainer confirmed this is exactly the required migration:

> I was writing a component and handling textures manually and learned I have to do:
> `texture.colorSpace = THREE.SRGBColorSpace;`

And the three.js maintainer's pointed migration note:

> Setting `renderer="colorManagement: false;"` appears to get you back to the r147 behavior in r152, but that's more of a temporary workaround than a solution.

See also the aframe-environment-component fix thread (linked issue #83),
which walks through the same pattern: ground `map`/`emissiveMap` textures had
to be switched to `THREE.sRGBEncoding` (the r152-era equivalent) or the
environment preset would render washed out.

## Difficulty Rating
2/5

## Adversarial Principles
- Silent gamma mismatch (no GL error, no validation warning)
- Symptom is a brightness shift, not a crash or missing geometry
- Root cause spans two separate GL states (texture internal format + FB encode)
- Output still looks "rendered" — just wrong

## How OpenGPA Helps
Querying the draw call's sampled texture shows `internalFormat = GL_RGB8`
while `GL_FRAMEBUFFER_SRGB` is enabled on the default framebuffer — a
mismatch OpenGPA can surface directly. The framebuffer dominant color (~188)
vs. the texel value (128) also pinpoints that a gamma transform is happening
exactly once too often on the output path.

## Source
- **URL**: https://github.com/aframevr/aframe/issues/5302
- **Type**: issue
- **Date**: 2023-06-15
- **Commit SHA**: (n/a)
- **Attribution**: Reported by @dmarcos; diagnosis confirmed by @donmccurdy and @mrxz

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
  expected_rgb: [128, 128, 128]
  tolerance: 10
```

## Upstream Snapshot
- **Repo**: https://github.com/aframevr/aframe
- **SHA**: 5e98e2d672d49a1d5a217fa9c0507ac5d82ca949
- **Relevant Files**:
  - src/systems/renderer.js  # default-branch SHA near issue close (no linked A-Frame PR; fix is app-side); (inferred)
  - src/components/material.js
  - src/components/environment.js

## Predicted OpenGPA Helpfulness
- **Verdict**: yes
- **Reasoning**: Tier-1 state capture exposes both the texture internal
  format (`GL_RGB8`) and the framebuffer sRGB-encode state (`GL_FRAMEBUFFER_SRGB`
  enabled). An agent asking for the draw call's sampled textures plus the
  framebuffer state gets the mismatch in one query. Without OpenGPA, the
  agent would have to reason about an observed "washed out" screenshot in
  terms of invisible GL state — a pure textual round-trip with no
  ground truth.

## Observed OpenGPA Helpfulness
- **Verdict**: ambiguous
- **Evidence**: validation skipped (--no-validate)
