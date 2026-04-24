# R6: ORM texture ignores metalness map contribution

## User Report
### Description of the bug

The gbuffer-metalness.frag chunk uses 'metalness'

```
#ifdef out_ORM

	out_ORM.z = metalness;

#endif
```

In the THREE shader chunk the code looks like this (metalnessmap_fragment.glsl.js):
```
float metalnessFactor = metalness;

#ifdef USE_METALNESSMAP

	vec4 texelMetalness = texture2D( metalnessMap, vMetalnessMapUv );

	// reads channel B, compatible with a combined OcclusionRoughnessMetallic (RGB) texture
	metalnessFactor *= texelMetalness.b;

#endif
```

In theory, the correct code to fill the buffer should look like this:
```
#ifdef out_ORM

	out_ORM.z = metalnessFactor;

#endif
```

### Library versions used

 - Three: [162]
 - Post Processing: [v7.0.0-alpha.3]

## Expected Correct Output
The fragment writes `metalness * texelMetalness.b` into the B channel of the
ORM render target. With `metalness = 1.0` and a metalnessMap whose B channel
is `128/255 ≈ 0.502`, the B channel of the output pixel should be
approximately `128`.

## Actual Broken Output
The B channel of the output pixel is `255` — the unmodulated `metalness`
uniform — regardless of the metalnessMap's B channel. The metalness map
contribution is silently dropped.

## Ground Truth
The ORM-packed metalness output assigns the raw `metalness` uniform instead
of the locally computed `metalnessFactor`, which is the product of the
uniform and the sampled metalnessMap.b. The reporter quotes the broken
chunk:

> The gbuffer-metalness.frag chunk uses 'metalness' ... In theory, the
> correct code to fill the buffer should look like this: `out_ORM.z = metalnessFactor;`

Maintainer confirmation:

> Thanks for pointing this out! It will be fixed in the next release via
> cdd1558 ... Fixed in `postprocessing@7.0.0-alpha.4`.

See commit cdd1558229274e3d37c85ec7dc6a95a908d6a9e2 ("Update
gbuffer-metalness.frag — Fixes #617"), which replaces the assignment with
`out_ORM.z = metalnessFactor;`.

## Fix
```yaml
fix_pr_url: https://github.com/pmndrs/postprocessing/commit/cdd1558229274e3d37c85ec7dc6a95a908d6a9e2
fix_sha: cdd1558229274e3d37c85ec7dc6a95a908d6a9e2
fix_parent_sha: 0f4ad3e08e8d2c982a48948931653a0d9af56e01
bug_class: framework-internal
files:
  - src/shader-chunks/shaders/gbuffer-metalness.frag
change_summary: >
  Replaces `out_ORM.z = metalness;` with `out_ORM.z = metalnessFactor;` in
  the gbuffer-metalness shader chunk so the ORM target's B channel includes
  the metalnessMap contribution computed earlier in the chunk, matching
  three.js' metalnessmap_fragment convention.
```

## Difficulty Rating
3/5

## Adversarial Principles
- wrong-variable-written-to-output
- dropped-texture-modulation
- shader-chunk-naming-collision

## How OpenGPA Helps
Querying the ORM output pixel and comparing it against the bound
metalnessMap's B-channel value reveals the output is independent of the
texture. Inspecting the active program's uniform/sampler bindings shows
`metalnessMap` is bound and sampled, yet the B-channel output equals the
raw `metalness` uniform — pointing at the wrong-variable assignment in the
fragment shader.

## Source
- **URL**: https://github.com/pmndrs/postprocessing/issues/617
- **Type**: issue
- **Date**: 2024-03-08
- **Commit SHA**: cdd1558229274e3d37c85ec7dc6a95a908d6a9e2
- **Attribution**: Reported by postprocessing user; fixed by @vanruesc

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
  region: center_1x1
  channel: b
  expected_approx: 128
  tolerance: 8
  observed: 255
```

## Predicted OpenGPA Helpfulness
- **Verdict**: yes
- **Reasoning**: OpenGPA can read back the ORM output pixel, enumerate the
  bound textures and uniforms for the draw call, and show that the output
  B channel does not depend on the sampled metalnessMap. That evidence
  narrows the bug to the shader assignment without needing upstream source
  inspection.

## Observed OpenGPA Helpfulness
- **Verdict**: ambiguous
- **Evidence**: validation skipped (--no-validate)
