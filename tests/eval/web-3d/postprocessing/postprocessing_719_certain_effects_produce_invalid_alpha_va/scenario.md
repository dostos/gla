# R2: Certain effects produce invalid alpha values

## User Report

Related: https://github.com/pmndrs/postprocessing/discussions/706#discussioncomment-13664821

`BloomEffect` and `TextureEffect` currently produce incorrect alpha values in v6 and v7.

The output should be `max(inputColor.a, texel.a)`. Otherwise, the blurred colors end up having 0 alpha which is invalid.

**To reproduce:** https://stackblitz.com/edit/postprocessing-v6-2p8ywufj?file=src%2FApp.js

**Expected behavior:** Correct color results.

**Screenshots:** side-by-side comparison attached in the original issue — left pane (current output using `inputColor.a`) shows the blurred halo vanishing into the transparent compositor background; right pane (using `max(inputColor.a, texel.a)`) shows the expected visible halo.

**Library versions used:**
- Three: 0.178.0
- Post Processing: 6.37.5, 7.0.0-beta.12

## Expected Correct Output
For every output pixel, the alpha channel must be at least `max(inputColor.a, texel.a)` — i.e. wherever the upstream pass was opaque, the effect's output stays opaque, and wherever the bloom/texture map has coverage that the upstream pass lacked, its alpha contribution is preserved. For the probe pixel at `(4, 4)` the upstream `inputBuffer` is fully opaque (alpha=255) and the bloom `map` has zero coverage there; the correct output alpha is 255.

## Actual Broken Output
The fragment shader's output alpha is `texel.a`, so the upstream pass's opaque alpha is discarded wherever the bloom map's coverage is zero. The probe pixel at `(4, 4)` reads back as `rgba≈0,0,0,0` even though the scene there is a fully opaque magenta. In the real postprocessing chain, a subsequent pass (tone mapping, gamma correction, or the composite to the canvas) then treats those regions as transparent, causing the blurred halo to vanish and leaving sharp alpha edges around bright features.

## Ground Truth
The bug is a single missing `max()` in each of the affected fragment shaders. In `src/effects/glsl/bloom.frag`, the `mainImage` function writes `outputColor = vec4(texel.rgb * intensity, texel.a)`, passing the bloom sample's alpha straight to the output; `inputColor.a` (the upstream pass's alpha) is dropped on the floor. `src/effects/glsl/texture.frag` has the same shape — after computing `outputColor = TEXEL;`, it never reconciles `outputColor.a` with `inputColor.a`. The reporter identifies the exact correction in the issue body:

> The output should be `max(inputColor.a, texel.a)`. Otherwise, the blurred colors end up having 0 alpha which is invalid.

The maintainer confirmed the fix shipped in v6.37.6 (see commit `dc88f87` — "Improve output alpha calculation, Addresses #719"). The diff replaces `texel.a` with `max(inputColor.a, texel.a)` in `bloom.frag` and adds `outputColor.a = max(inputColor.a, outputColor.a);` after the `TEXEL` assignment in `texture.frag`.

## Fix
```yaml
fix_pr_url: https://github.com/pmndrs/postprocessing/commit/dc88f870118b54fc31c18963bbbc4e188f657e8b
fix_sha: dc88f870118b54fc31c18963bbbc4e188f657e8b
fix_parent_sha: 6e76877cd79ace6c3678de9aff63704e654dc777
bug_class: framework-internal
files:
  - src/effects/glsl/bloom.frag
  - src/effects/glsl/texture.frag
change_summary: >
  In both effect shaders, reconcile the output alpha with the upstream pass's
  alpha using `max(inputColor.a, texel.a)` instead of blindly overwriting it
  with `texel.a`. This keeps opaque regions opaque even where the bloom/texture
  map has zero coverage, and preserves the bloom/texture map's alpha where
  the upstream pass is transparent.
diff_excerpt: |
  -	outputColor = vec4(texel.rgb * intensity, texel.a);
  +	outputColor = vec4(texel.rgb * intensity, max(inputColor.a, texel.a));
```

## Difficulty Rating
2/5

## Adversarial Principles
- alpha-channel invariant silently violated (RGB looks reasonable; only the alpha channel is wrong)
- cross-pass contract: the upstream pass's alpha must survive downstream effects, but the violation is only visible after the final composite
- single-line fragment-shader bug (no API misuse, no state leak — the root cause is a missing `max()` in a one-line expression)

## How OpenGPA Helps
Probing the output framebuffer's alpha channel at pixels where the upstream pass was opaque directly reveals the invariant violation: expected alpha = 255, actual alpha = 0. OpenGPA's per-draw framebuffer dump surfaces this immediately, whereas a human debugger staring at the on-screen RGB preview typically misses it because alpha is invisible until the final composite.

## Source
- **URL**: https://github.com/pmndrs/postprocessing/issues/719
- **Type**: issue
- **Date**: 2025-07-04
- **Commit SHA**: dc88f870118b54fc31c18963bbbc4e188f657e8b
- **Attribution**: Reported on pmndrs/postprocessing issue tracker; fix confirmed by maintainer in v6.37.6 release notes

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
  probe_pixel: [4, 4]
  channel: alpha
  expected: 255
  actual: 0
  tolerance: 4
  rationale: "upstream inputBuffer is fully opaque (alpha=255) at this pixel; the bloom map has zero coverage here. The effect's output alpha should be max(255, 0) = 255."
```

## Upstream Snapshot
- **Repo**: https://github.com/pmndrs/postprocessing
- **SHA**: 6e76877cd79ace6c3678de9aff63704e654dc777
- **Relevant Files**:
  - src/effects/glsl/bloom.frag
  - src/effects/glsl/texture.frag
  - src/effects/BloomEffect.js
  - src/effects/TextureEffect.js
  - src/materials/EffectMaterial.js

## Predicted OpenGPA Helpfulness
- **Verdict**: yes
- **Reasoning**: The defect is directly observable in a single frame of captured GL state — the output framebuffer's alpha channel at a pixel where the upstream pass was opaque. An OpenGPA per-draw framebuffer query (or a pixel readback at a chosen coordinate) exposes the invariant violation without any reasoning about the shader source. With the shader source also available via OpenGPA's program dump, the one-line `texel.a` expression in `mainImage` is trivial to pair with the observed alpha.

## Observed OpenGPA Helpfulness
- **Verdict**: ambiguous
- **Evidence**: validation skipped (--no-validate)
