# R20: Object with MeshPhysicalMaterial contains Transmission artifacts

## User Report
3D Objects with the MeshPhysicalMaterial will display weird artifacts when the
transmission property is greater than 0. The object with the transmission
property will display this behavior if there is another object near it.

Repro steps: create two spheres, set one to `MeshPhysicalMaterial.transmission
= 1`, place the transparent one in front of the opaque one, view in the
three.js editor. Screenshots show banded/blocky color artifacts across the
transmissive sphere where the opaque sphere is seen through it.

Environment: Chrome / Edge / Firefox on Windows 10 with AMD GPU (ANGLE
D3D11 backend). Works fine in r149; broken starting r150. The artifacts do
not reproduce on macOS (M2 Pro), on an NVIDIA RTX 2070 laptop, nor on an
older iMac with an AMD GPU. Updating the AMD driver does not fix it.

One follow-up reporter (on an AMD Ryzen 5 Pro integrated GPU) confirmed
the artifacts still appear in r155 across Firefox/Edge/Chrome even with
`powerPreference: "high-performance"`. Patching the shader to replace
`textureLod` with `texture`, or replacing `textureSize` with a hard-coded
vec2, did not remove the artifacts.

## Expected Correct Output
The transmissive sphere should show a smoothly blurred view of the opaque
sphere behind it (bicubic filtered mipmap lookup of the framebuffer).

## Actual Broken Output
On affected AMD/ANGLE/D3D11 configurations, the transmissive sphere shows
banded, blocky, or repeated texel artifacts where the framebuffer sample
should be blurred. The artifacts change slightly between browsers (Chrome
vs. Edge) but are all variations of the same bicubic-lookup miscompilation.

## Ground Truth
The regression was introduced in PR #25483, which replaced the previous
bilinear `getTransmissionSample` with a bicubic filter. The new
`textureBicubic` helper reads four `textureLod(tex, uv, lod)` taps per
filtered sample at a dynamically-computed LOD, and uses `textureSize(tex,
int(lod))` to compute the per-level pixel size.

> "Then I guess this issue was introduced with the shader modifications
> from #25483." — @Mugen87

> "It seems Windows systems with AMD GPUs have issues with the new the
> shader code from #25483. Nvidia cards are not affected. Since all
> browser on the respective systems render the artifacts, this looks
> like a GPU driver issue." — @Mugen87

Reporters were asked to replace `textureLod` with `texture` and to
hard-code the `textureSize` result; neither workaround removed the
artifacts, which rules out both as the sole trigger and points at the
combination (dynamic-LOD sampling of a GPU-generated mipmap chain on a
render-target texture) as stressing an ANGLE/D3D11 code path that the
AMD HLSL compiler miscompiles.

The three.js issue was closed without a confirmed upstream fix: the
original reporter switched to a working NVIDIA GPU mid-thread and a later
follow-up was never acted on. As of r155 the bicubic path in
`transmission_pars_fragment.glsl.js` is unchanged.

See PR #25483 for the change that introduced the bicubic path.

## Difficulty Rating
5/5

## Adversarial Principles
- Driver-specific miscompilation (AMD ANGLE D3D11) — bug is not in the
  application's GL state, not in the shader's GLSL semantics, and not
  reproducible on Mesa/NVIDIA/Apple GPUs.
- Non-reproducible: eval harness runs on Linux/Xvfb with Mesa/llvmpipe,
  so the artifact cannot manifest regardless of capture fidelity.
- Hypothesis-only diagnosis: no upstream fix landed; thread was closed
  due to lack of feedback after the original reporter's active GPU
  changed.
- Minimal workarounds (remove `textureLod`, hard-code `textureSize`)
  fail — the triggering combination is unclear even to maintainers.

## How OpenGPA Helps
Minimal. OpenGPA captures GL state and draw-call metadata, but the GL
state here is valid on every driver — the bug is in how AMD's HLSL
backend (via ANGLE) lowers `textureLod` with a dynamic LOD over a
mipmapped render-target texture. A capture on a non-AMD system shows
no artifact; a capture on an affected AMD/Windows box would show
correct GL state plus a visually broken framebuffer. The agent could
identify the unusual draw pattern (mipmapped FBO sampled with
fractional LOD) and the correlation with PR #25483, but cannot
attribute the miscompilation without a side-channel into ANGLE's
generated HLSL or the D3D11 driver.

## Source
- **URL**: https://github.com/mrdoob/three.js/issues/25648
- **Type**: issue
- **Date**: 2023-03-10
- **Commit SHA**: (n/a)
- **Attribution**: Reported by @KMamuyac; follow-up from @LeviPesin and @kstopse; triaged by @Mugen87

## Tier
snapshot

## API
opengl

## Framework
threejs

## Upstream Snapshot
- **Repo**: https://github.com/mrdoob/three.js
- **SHA**: 8fab13b240999d157459f0caefbc5ee4357fd45d
- **Relevant Files**:
  - src/renderers/shaders/ShaderChunk/transmission_pars_fragment.glsl.js
  - src/renderers/shaders/ShaderChunk/transmission_fragment.glsl.js
  - src/renderers/shaders/ShaderChunk/common.glsl.js
  - src/materials/MeshPhysicalMaterial.js
  - src/renderers/webgl/WebGLBackground.js

## Bug Signature
```yaml
type: unexpected_color
spec:
  region: center
  reason: bicubic transmission filter should produce a smoothly blurred sample of the framebuffer; on AMD/ANGLE/D3D11 the sample shows banding/block artifacts
  tolerance: driver-dependent; not reproducible on Mesa/NVIDIA
```

## Predicted OpenGPA Helpfulness
- **Verdict**: no
- **Reasoning**: Bug manifests only on AMD GPUs on Windows through ANGLE's D3D11 backend, where the HLSL compiler appears to miscompile the dynamic-LOD bicubic sampling introduced in PR #25483. Every GL/WebGL API call is valid and identical across machines; the artifact exists below the GL abstraction layer that OpenGPA captures. Both maintainer-suggested shader workarounds (dropping `textureLod`, hard-coding `textureSize`) failed to remove the artifacts, and the upstream issue was closed with no confirmed fix — there is no single state or call OpenGPA could highlight that distinguishes the broken frame from a working one on a different GPU. The scenario is also not reproducible in the eval harness (Linux/Xvfb/Mesa), so ground-truth scoring against a rendered frame isn't available.

## Observed OpenGPA Helpfulness
- **Verdict**: ambiguous
- **Evidence**: validation skipped (--no-validate)
