# R11_SCREEN_GLITCH_WITH_BLOOM_ON_M1_MAC: Screen glitch with Bloom on M1 Mac

## User Report
When using the `BloomEffect` on an M1 Mac (Chrome and Edge), there is a glitch
that causes the screen to go black in certain areas. This only seems to happen
with certain models though. On Windows, the same models and code do not have
any issue.

To Reproduce: https://jsfiddle.net/KevTheDev/3k1nyhz2/

Expected behavior: No glitches should be visible.

Library versions used:
- three: 0.155.0
- postprocessing: 6.33.0

Device: Mac M1. OS: macOS Ventura 13.4.1. Browsers: Edge 115 (arm64), Chrome 116 (arm64).

A maintainer noted: "This seems to be caused by invalid color values that
result in undefined hardware behaviour." A follow-up investigation filed
upstream as three.js #26767 reports:

> While investigating this bug I found the root cause in the
> `lights_pars_begin` shader chunk. It looks like `shGetIrradianceAt`
> sometimes produces negative values which leads to unexpected behaviour.
> This happens regardless of whether a light probe is used or not.
>
> The issue becomes more noticeable when the result is stored in a
> `HalfFloatType` buffer for further processing as this doesn't clamp the
> values to `[0, 1]` and leads to more errors down the line. When rendered
> directly to screen, the output will contain black pixels where
> `shGetIrradianceAt` returns bad values.

Workaround the reporter suggested: limit the return value of
`shGetIrradianceAt` to at least 0.

## Expected Correct Output
A smoothly shaded quad whose luminance rises and falls with the lighting
basis, fed through a bloom bright-pass. Every pixel of the final image should
be a finite non-negative color; no black holes or NaN-induced artifacts.

## Actual Broken Output
Portions of the quad rendered by the bright-pass read from directions where
the simulated spherical-harmonic evaluation returned a negative component.
Downstream tonemapping (`sqrt(color)`) of a negative half-float yields NaN,
which most drivers rasterize as black. The glitch appears as black patches
on an otherwise lit surface — the exact failure mode the M1 users saw with
BloomEffect.

## Ground Truth
The `shGetIrradianceAt` helper in the `lights_pars_begin` shader chunk
evaluates a spherical-harmonic expansion whose linear terms are signed, so
any environment or probe whose gradient exceeds the DC coefficient produces
negative irradiance for some surface normals. three.js did not clamp the
result. When the renderer's output buffer is `HalfFloatType` (which
postprocessing's EffectComposer uses for HDR), those negative values survive
into the bloom chain; downstream math that assumes non-negative radiance
(`sqrt`, `pow`, `log`) then returns NaN, which hardware rasterizes as
undefined — commonly black on Apple Silicon and Intel integrated GPUs.

The reporter of three.js #26767 explicitly identified the chunk and the
missing clamp:

> It looks like `shGetIrradianceAt` sometimes produces negative values
> which leads to unexpected behaviour.

and demonstrated that forcing `max(result, 0.0)` before returning from
`shGetIrradianceAt` eliminates the artifacts. See three.js issue
[#26767](https://github.com/mrdoob/three.js/issues/26767) and the related
postprocessing discussion at issue
[#526](https://github.com/pmndrs/postprocessing/issues/526).

## Fix
```yaml
fix_pr_url: https://github.com/mrdoob/three.js/pull/26778
fix_sha: (auto-resolve from PR #26778)
fix_parent_sha: (auto-resolve from PR #26778)
bug_class: framework-internal
files:
  - src/renderers/shaders/ShaderChunk/lights_pars_begin.glsl.js
change_summary: >
  Clamps the output of `shGetIrradianceAt` in the lights_pars_begin shader
  chunk so spherical-harmonic evaluations cannot return negative irradiance.
  This prevents negative half-float values from propagating into the
  postprocessing bloom chain, where downstream `sqrt`/`pow` math on
  negatives produces NaN and manifests as black glitch patches.
```

## Upstream Snapshot
- **Repo**: https://github.com/mrdoob/three.js
- **SHA**: (auto-resolve from PR #26778)
- **Relevant Files**:
  - src/renderers/shaders/ShaderChunk/lights_pars_begin.glsl.js
  - src/lights/LightProbe.js
  - src/math/SphericalHarmonics3.js

## Difficulty Rating
4/5

## Adversarial Principles
- cross-repo-diagnosis
- hdr-half-float-propagation
- nan-from-sqrt-of-negative
- platform-dependent-manifestation

## How OpenGPA Helps
Querying the RGBA16F render target pixel values reveals the negative
components written by the lighting shader before the bloom pass consumes
them. A histogram query on the irradiance FBO surfaces the negative range
that would otherwise be masked by the screen-facing `[0,1]` clamp; stepping
into the bloom pass's draw call shows NaN appearing after the `sqrt` call.

## Source
- **URL**: https://github.com/pmndrs/postprocessing/issues/526
- **Type**: issue
- **Date**: 2023-08-18
- **Commit SHA**: (n/a)
- **Attribution**: Reported by @KevTheDev; root cause identified by @Mugen87 and filed in three.js #26767

## Tier
core

## API
opengl

## Framework
none

## Bug Signature
```yaml
type: color_histogram_in_region
spec:
  region: { x: 0.2, y: 0.4, w: 0.2, h: 0.2 }
  channel: r
  expected_range: [0.0, 2.0]
  observed_contains: [NaN, 0.0]
```

## Predicted OpenGPA Helpfulness
- **Verdict**: yes
- **Reasoning**: The bug is invisible in the source C code alone — the
  diagnosis requires seeing that an intermediate HDR buffer holds negative
  values before the second pass consumes them. OpenGPA's ability to read
  back floating-point framebuffer contents between passes is precisely the
  capability needed.

## Observed OpenGPA Helpfulness
- **Verdict**: ambiguous
- **Evidence**: validation skipped (--no-validate)
