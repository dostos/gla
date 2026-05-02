# R4: MSAA does not always work when doing RTT

## User Report

I would expect to have same output image when rendering to screen with `antialias: true` or when using EffectComposer + RenderPass + OutputPass and a render target with 4 samples.

Open [https://jsfiddle.net/5kczseda/1/](https://jsfiddle.net/5kczseda/1/). The left cube is rendered to screen while the right cube uses postprocessing and has aliasing.

This behaviour changes depending on material type and clear color opacity. A simplified fiddle reproducing the issue: [https://jsfiddle.net/n41advb2/1/](https://jsfiddle.net/n41advb2/1/). When reducing the ambient light intensity to a more common value, the aliasing on the right cube disappears: [https://jsfiddle.net/n41advb2/2/](https://jsfiddle.net/n41advb2/2/). So this is maybe some sort of precision-related issue. The aliasing is unrelated to `OutputPass` — even a simple copy shader produces the aliasing.

The aliasing also disappears when using `THREE.UnsignedByteType` for the multisampled render target: [https://jsfiddle.net/6q07hpa2/](https://jsfiddle.net/6q07hpa2/). You don't see it when rendering to the default framebuffer because values get clamped (the default framebuffer is RGBA8); when using render targets with higher precision (FP16 or FP32), the clamping does not happen and MSAA can't mitigate the aliasing.

### Version

three.js r157, WebGL2, desktop.

## Expected Correct Output

A 400×300 frame with a smoothly anti-aliased diagonal edge running from the top-left corner to the bottom-right corner. Pixels along the diagonal should form a visible gradient between the fully-lit interior (near white after tone mapping) and the black background — approximately half-intensity at the geometric edge, since each edge pixel has ~2/4 samples covered.

## Actual Broken Output

The diagonal edge is jagged: edge pixels are nearly as bright as interior pixels, with no visible intermediate gradient band. The read-back shows the interior pixel at `(W/4, H/4)` and the edge pixel at `(W/2, H/2)` both land in the 240–255 range per channel after tone mapping, despite the edge pixel having only 2/4 sample coverage. There is no gradient; the diagonal looks identical to a no-MSAA render.

## Ground Truth

When the post-processing render target uses `RGBA16F` (three.js `HalfFloatType`, which is the default for `EffectComposer`), per-sample color writes are unclamped. The triangle fragments write `(20, 20, 20)` into every covered sample; the background samples hold `(0, 0, 0)`. `glBlitFramebuffer` resolves the 4 samples per pixel by linear averaging:

- Interior pixel (coverage 4/4): resolved to `20.0`.
- Edge pixel (coverage 2/4): resolved to `10.0`.

The final Reinhard tone map `x / (1 + x)` then maps:

- `20 / 21 ≈ 0.9524` → `243` in 8-bit.
- `10 / 11 ≈ 0.9091` → `231` in 8-bit.

Both pixels land in the saturated "near-white" region of the tone-mapping curve. The difference the human eye needs to see an anti-aliased edge — a gradient through mid-tone values — is gone, so the edge looks aliased even though MSAA fired correctly.

The same scene rendered to `RGBA8` (`UnsignedByteType`) per-sample-clamps to `1.0` at write time, so the averages become `1.0` (interior) and `0.5` (edge). The tone map then produces distinctly different output, and the edge is properly smoothed. Citation, Mugen87 in the thread:

> My theory is that what you see is a special case related to value ranges that MSAA can't handle. You don't see it when rendering to the default framebuffer because values get clamped (the default framebuffer is RGBA8). When using render targets with higher precision (FP16 or FP32), the clamping does not happen and MSAA can't mitigate the aliasing.

Mugen87 then linked a canonical reference that describes the mechanism in detail: Matt Pettineo's "MSAA Overview", section "Working with HDR and Tone Mapping" (<https://mynameismjp.wordpress.com/2012/10/24/msaa-overview/>). One very bright sample can dominate the average; resolving before tone mapping loses the high-frequency edge information that a perceptually-correct resolve would preserve.

The thread later merged into issue #33104. A per-sample tone-map-before-resolve pass, or a bright-sample weighting scheme in the resolve, are the standard mitigations; three.js does not do either, which is why the post-processing path aliases and the direct-to-screen path does not.

## Difficulty Rating

4/5

The failure mode is non-local: the render target, the draw call, and the tone map are all individually "correct" under their local semantics. The aliasing emerges from the interaction between (a) unclamped HDR sample writes, (b) linear-average MSAA resolve, and (c) a saturating tone-map curve. An agent cannot find this by inspecting a single shader or a single state entry — it has to reason about sample-level color statistics and how they flow through the resolve and tone map.

## Adversarial Principles

- **Interaction bug across three subsystems**: the bug is invisible in any single pass.
- **Precision-on-demand**: using a higher-precision render target (normally an improvement) is what exposes the issue.
- **Visual symptom disguised as a different bug class**: "MSAA is broken" looks like a driver or state bug; it is actually a numerical-precision issue in the resolve-plus-tonemap pipeline.
- **Default framebuffer bias**: the same scene works when rendered directly to the screen, so developers assume their scene is fine and the post-processing stack is broken.

## How OpenGPA Helps

Tier 1 captures per-draw framebuffer format metadata. The query `get_draw_call(draw_id=0)` exposes that the color attachment is `GL_RGBA16F` with `samples=4`, and that the subsequent draw samples from a single-sample `RGBA16F` texture. `compare_frames` or `get_pixel` at edge vs interior coordinates in the FP16 resolve buffer reveals that the edge pixel holds `~10.0` and the interior `~20.0` — both pre-tone-map HDR values, making the dominant-sample problem quantitatively obvious instead of requiring the agent to guess at precision from visual aliasing alone.

## Source

- **URL**: https://github.com/mrdoob/three.js/issues/26954
- **Type**: issue
- **Date**: 2023-10-12
- **Commit SHA**: (n/a — merged into tracking issue #33104; no single fix commit)
- **Attribution**: Reported by @LR17; diagnosis by @Mugen87 (see quoted comment)

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
  region: edge_pixel
  edge_pixel_coords: [200, 150]
  interior_pixel_coords: [100, 75]
  expected_edge_luma_fraction_of_interior: [0.3, 0.7]
  observed_edge_luma_fraction_of_interior_min: 0.9
  channel: r
```

## Predicted OpenGPA Helpfulness

- **Verdict**: yes
- **Reasoning**: The root cause is a numerical property of an intermediate floating-point render target that is never observable from source code. OpenGPA's per-draw attachment format + pixel readback of the FP16 resolve buffer (pre tone-map) immediately reveals that the edge pixel holds ~10.0 and the interior ~20.0, turning an ambiguous "edges look jagged" symptom into a concrete HDR-resolve-then-saturating-tone-map diagnosis.

## Observed OpenGPA Helpfulness
- **Verdict**: ambiguous
- **Evidence**: validation skipped (--no-validate)
