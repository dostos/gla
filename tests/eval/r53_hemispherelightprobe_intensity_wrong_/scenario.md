# R53_HEMISPHERELIGHTPROBE_INTENSITY_WRONG: HemisphereLightProbe intensity is wrong

## User Report
When not using legacy lighting model, the `HemisphereLightProbe` intensity is
wrong, the light created this way is about 3 times (or pi times, this is hard
tell) brighter than it should be.

Reproduction steps:
1. create a simple scene with `HemisphereLight` with intensity `3`
2. display the scene
3. replace the light with `HemisphereLightProbe`
4. display the scene and notice it is much brighter
5. set `HemisphereLightProbe` intensity to `1`
6. display the scene and notice it is the original brightness
7. use `useLegacyLights = true`
8. set `HemisphereLightProbe` intensity to `3`
9. display the scene and notice it is the original brightness

Version: r156. Browser: Chrome. OS: Linux.

## Expected Correct Output
With the modern (non-legacy) lighting model and identical authored intensity
values, `HemisphereLight(skyColor=white, groundColor=gray, intensity=3)` and
`HemisphereLightProbe(skyColor=white, groundColor=gray, intensity=3)` should
produce visually identical lit surfaces. Center pixel of a white diffuse
plane lit only by the light-probe version should read as a moderate gray —
around rgb `(130, 130, 130)` — matching the reference `HemisphereLight`
render.

## Actual Broken Output
The `HemisphereLightProbe` version is uniformly brighter than the
`HemisphereLight` reference by a factor of roughly `PI`. The center pixel
saturates to white `(255, 255, 255)` or near-white; the plane visibly
over-blows compared to the reference.

## Ground Truth
Three.js evaluates spherical-harmonic (SH) irradiance in the shader by
accumulating `shCoefficients[i] * shBasis_i(normal)`. The CPU-side constructor
of each *LightProbe* subclass translates the artist-friendly
`(color, intensity)` inputs into the raw SH coefficients that the shader
consumes. In r156, both `AmbientLightProbe` and `HemisphereLightProbe`
multiplied the sky/ground colors by `Math.sqrt(Math.PI)` instead of
`1 / Math.sqrt(Math.PI)` — a factor-of-`PI` over-scale end-to-end because
the shader already assumes the probe delivers an irradiance-scale value.

Concretely, `HemisphereLightProbe` computes its order-0 SH coefficient as:

```
const c0 = Math.sqrt( Math.PI );                   // broken: ≈ 1.7724539
this.sh.coefficients[ 0 ].copy( sky ).add( ground ).multiplyScalar( c0 );
```

The correct magnitude for the new lighting model is `1 / sqrt(PI) ≈ 0.5641896`.
A rendered pixel whose radiance should be `L` ends up as `L * PI` — exactly the
"3×" or "π×" over-brightness the reporter observed.

The PR description confirms the diagnosis:

> The "artist friendly" lights have been deprecated.

See PR #26683 ("Ambient/Hemi Light Probes: Accommodate new lighting model").
The same `sqrt(PI)` / `1/sqrt(PI)` flip appears in `AmbientLightProbe.js` and
`HemisphereLightProbe.js`, and those two files are the entire diff.

The minimal GL repro in `main.c` mirrors the mistake on the CPU: the
fragment shader reads a single "SH coefficient" uniform that should be
`color.rgb / sqrt(PI)`; the host uploads `color.rgb * sqrt(PI)` instead,
producing the ~`PI`× over-bright white plane.

## Fix
```yaml
fix_pr_url: https://github.com/mrdoob/three.js/pull/26683
fix_sha: 8fde3e25fd869033a6ddd64a40f290c584486311
fix_parent_sha: f8509646d78fcd4efaa4408119b55b2bead6e01b
bug_class: framework-internal
files:
  - src/lights/AmbientLightProbe.js
  - src/lights/HemisphereLightProbe.js
change_summary: >
  Replace the `Math.sqrt(Math.PI)` over-scale applied to the SH order-0
  coefficient inside each `*LightProbe` subclass with `1 / Math.sqrt(Math.PI)`,
  matching the non-legacy shader which already absorbs the extra `PI` factor
  elsewhere. Net effect: `HemisphereLightProbe(intensity=3)` now matches
  `HemisphereLight(intensity=3)` on a vanilla diffuse surface, instead of
  being `PI×` brighter.
```

### Captured-literal breadcrumb (for GPA trace validation)
At reproduction time, the scalar multiplier applied to the sky/ground color
before it is stored into `sh.coefficients[0]` is `Math.sqrt(Math.PI)`
≈ `1.7724538509055159`. The correct multiplier is `1 / Math.sqrt(Math.PI)`
≈ `0.5641895835477563`. The wrong value is written at
`src/lights/HemisphereLightProbe.js:19` (the `const c0 = Math.sqrt(Math.PI)`
line, which then flows into `multiplyScalar(c0)`), and at
`src/lights/AmbientLightProbe.js:14` for the analogous scaling of
`sh.coefficients[0]`. `gpa trace value 1.7724538` (or `1.7724539`, or
`3.5449077` for `2 * sqrt(PI)` in AmbientLightProbe) should surface
`src/lights/HemisphereLightProbe.js` or `src/lights/AmbientLightProbe.js` as
the high-confidence candidate. The agent, seeing a uniform whose magnitude
is `PI` times larger than expected for a unit irradiance, should
reverse-search the captured literal and land directly on the fix site.

## Upstream Snapshot
- **Repo**: https://github.com/mrdoob/three.js
- **SHA**: f8509646d78fcd4efaa4408119b55b2bead6e01b
- **Relevant Files**:
  - src/lights/AmbientLightProbe.js
  - src/lights/HemisphereLightProbe.js
  - src/lights/LightProbe.js
  - src/renderers/shaders/ShaderChunk/lights_pars_begin.glsl.js
  - src/math/SphericalHarmonics3.js

## Difficulty Rating
4/5

## Adversarial Principles
- numeric-constant-off-by-factor-pi
- symptom-is-brightness-only
- bug-lives-in-constructor-not-shader
- lighting-model-convention-drift

## How OpenGPA Helps
The bug is a single pre-upload multiplier on the CPU. Capturing the uniform
block that carries `sh_coefficient_0` and reading back its scalar magnitude
shows a value ~3× (π×) larger than the reference `HemisphereLight` upload
for the same authored `(color, intensity)` input. A `gpa trace value 1.7724`
or `gpa trace value 3.5449` on that captured literal routes directly to
`HemisphereLightProbe.js` / `AmbientLightProbe.js` — the two files whose
diff *is* the fix. Without the trace, the agent has to read the SH chain
(LightProbe → SphericalHarmonics3 → lights_pars_begin) top-down, which is
exactly the search the R10 "source-logical" category has shown to be slow
and error-prone.

## Source
- **URL**: https://github.com/mrdoob/three.js/issues/26668
- **Type**: issue
- **Date**: 2023-08-30
- **Commit SHA**: 8fde3e25fd869033a6ddd64a40f290c584486311
- **Attribution**: Reported by @hybridherbst (three.js #26668); diagnosed and fixed by @WestLangley in PR #26683.

## Tier
snapshot

## API
opengl

## Framework
three.js

## Bug Signature
```yaml
type: unexpected_color
spec:
  region: { x: 128, y: 128, w: 1, h: 1 }
  expected_rgb: [128, 128, 128]
  actual_rgb:   [255, 255, 255]
  tolerance: 8
  note: >
    Single diffuse quad lit only by a HemisphereLightProbe with authored
    intensity 1. Expected middle-gray; observed saturates to white because
    the probe uploads its SH coefficient with an extra factor of sqrt(PI).
```

## Predicted OpenGPA Helpfulness
- **Verdict**: yes
- **Reasoning**: Classic captured-literal-breadcrumb shape. The wrong value
  (`≈1.7725`) is written *exactly once* into a uniform that the shader
  reads. Reverse-searching that literal surfaces the two light-probe
  constructor files immediately, while the user-visible symptom
  ("too bright") gives no source-location hint at all.

## Observed OpenGPA Helpfulness
- **Verdict**: ambiguous
- **Evidence**: validation skipped (--no-validate)
