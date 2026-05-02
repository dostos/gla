# R6_LATEST_BUILD_6_38_1_GOT_GLITCHY_OPACITY_: EffectPass final-pass blending darkens screen during fade

## User Report
### Description of the bug

Animate opacity fadein/fadeout, it glitches black all around

### To reproduce

I believe just animate? im using alpha canvas above another canvas

### Expected behavior

Stable fade as below 6.38.1

### Library versions used

 - Three: tested from 178 to 182, actually in 182
 - Post Processing: 6.38.1

### Mobile

 - Device: Tablet Lenovo
 - OS: Android 12
 - Browser Webview/Chromium

## Expected Correct Output
The center of the window displays the post-processed scene color — solid orange `(255, 153, 51)` — regardless of the animated opacity value, because the final composite-to-screen pass should be an opaque copy.

## Actual Broken Output
The center of the window is roughly half-brightness orange `(~128, ~77, ~26)`: the source color was blended against the black default framebuffer clear using `uOpacity = 0.5`.

## Ground Truth
The last post-processing pass renders a fullscreen quad of the post-processed scene to the default framebuffer with `GL_BLEND` enabled and `glBlendFuncSeparate(SRC_ALPHA, ONE_MINUS_SRC_ALPHA, ONE, ONE_MINUS_SRC_ALPHA)`. During a fade the fragment alpha is less than 1, so the final color is blended against whatever is already in the default framebuffer (here, the black clear color) instead of overwriting it. The result is a darkened / "black glitchy" frame whenever opacity is animated.

The upstream maintainer confirmed the regression was introduced by a deliberate blend-state change on `EffectMaterial` in 6.38.1:

> I changed the behavior of the `EffectPass` in 6.38.1 to use `NormalBlending` with `tranparent` set to `true` on the `EffectMaterial` in hopes that this would help fix #475, but alas.
>
> I'll revert that change tomorrow and publish a new release after some more testing.

The reporter independently isolated the same surface symptom:

> The Glitch: Occurs when EffectPass is the final pass in the composer chain (rendering directly to screen). [...] When forced to write to an intermediate buffer (by adding a subsequent pass), the output is correct.

The fix was shipped as v6.38.2 (reverting the blend-mode change). See release notes at https://github.com/pmndrs/postprocessing/releases/tag/v6.38.2.

## Difficulty Rating
3/5

## Adversarial Principles
- state_leak:blend_mode_final_pass
- final_pass_not_opaque_copy

## How OpenGPA Helps
Inspecting the last draw call's GL state shows `GL_BLEND = ENABLED` and an alpha-blending `blendFunc` even though the draw targets framebuffer 0 and the source fragment's alpha is `uOpacity = 0.5`. That combination — "compositing to the default framebuffer with non-1 source alpha" — is exactly the anti-pattern that produces the darkened output, and it is visible directly in `unexpected_state_in_draw` plus a pixel query on the result.

## Source
- **URL**: https://github.com/pmndrs/postprocessing/issues/735
- **Type**: issue
- **Date**: 2026-04-18
- **Commit SHA**: (n/a)
- **Attribution**: Reported by pmndrs/postprocessing issue #735; root cause confirmed by maintainer @vanruesc

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
  x: 128
  y: 128
  expected_rgb: [255, 153, 51]
  tolerance: 8
```

## Upstream Snapshot
- **Repo**: https://github.com/pmndrs/postprocessing
- **SHA**: 6f40279377ff28d7c07351df2a5006625897a718
- **Relevant Files**:
  - src/materials/EffectMaterial.ts  # parent of closing commit 3f6f8efcc (EffectPass blend revert for v6.38.2)
  - src/passes/EffectPass.ts

## Predicted OpenGPA Helpfulness
- **Verdict**: yes
- **Reasoning**: The bug is a pure GL-state regression on the final draw call — blend enable + alpha-blending blendFunc when writing to FBO 0. Both the bad state (visible via per-draw-call state snapshot) and the resulting darkened pixel (visible via pixel query) are exactly what OpenGPA surfaces, and the Tier-1 raw-state view distinguishes this from shader-math bugs that look similar in screenshots.

## Observed OpenGPA Helpfulness
- **Verdict**: ambiguous
- **Evidence**: validation skipped (--no-validate)
