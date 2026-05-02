# R1_PIXIJS_ALPHAMASK_STALE_MAPCOORD: Pooled mask texture reused without refreshing UV-transform uniform

## User Report
### PixiJS version

8.17.0

### Link to minimal reproduction

https://stackblitz.com/edit/pixijs-v8-v9aazsue?file=src%2Fmain.js

### Steps to reproduce

1. Create two differently-sized shapes which will act as alpha masks. In this
   case, we'll do a 100x80 rectangle and a 70x110 rectangle.
   ```ts
   const maskRectA = new Graphics().rect(10, 20, 100, 80).fill(0xffffff);
   maskRectA.position.set(20, 50);

   const maskRectB = new Graphics().rect(5, 5, 70, 110).fill(0xffffff);
   maskRectB.position.set(290, 45);
   ```
2. Create `AlphaMask` instances for these mask shapes with
   `renderMaskToTexture = true`.
   ```ts
   const alphaMaskA = new AlphaMask({ mask: maskRectA });
   alphaMaskA.renderMaskToTexture = true;

   const alphaMaskB = new AlphaMask({ mask: maskRectB });
   alphaMaskB.renderMaskToTexture = true;
   ```
3. Apply these alpha masks to some arbitrary display objects.

### What is expected?

- `alphaMaskA` should mask `squareA` to a 100x80 area.
- `alphaMaskB` should mask `squareB` to a 70x110 area.

### What is actually happening?

`alphaMaskA` applies as expected, but `alphaMaskB` does not.

- `alphaMaskA` correctly masks `squareA` to a 100x80 area.
- `alphaMaskB`, however, masks `squareB` to a ~50x110 area instead of the
  expected 70x110 area.

### System Info

```
OS: macOS 14.8.4
Browser: Chrome 146.0.7680.165
```

### Any additional comments?

I have a workaround which patches `MaskFilter.apply()` to make sure
`this._textureMatrix.update()` is called first. I included this patch in the
repro I shared. I doubt that patch is a holistic fix.

## Expected Correct Output
- Left half: 130x130 green square, masked to a 100x80 axis-aligned region.
- Right half: 130x130 blue square, masked to a 70x110 axis-aligned region.

## Actual Broken Output
- Left half is correct.
- Right half's blue square is masked using mask A's `(100/128, 80/128)` UV
  transform applied to mask B's underlying 70x110 contents, so the visible
  blue region is squeezed horizontally and clipped vertically — roughly a
  ~50x110 strip rather than the intended 70x110 rectangle. (The reporter
  observed exactly this in the linked StackBlitz repro.)

## Ground Truth
The reporter's flow analysis traces the bug to `MaskFilter._textureMatrix`
short-circuiting on identical texture references inside `MaskFilter.apply()`:

> `this._textureMatrix.texture = this.sprite.texture` → same object reference
> → setter's `if (this.texture === value) return` fires → `update()` is
> skipped — `mapCoord` is still `{a: 108/128, d: 94/128}` from Mask A. But
> it should be `{a: 76/128, d: 79/128}` for Mask B. The shader samples at
> wrong UV coordinates → mask appears distorted.

The pooled-texture aliasing is intrinsic to PixiJS's `TexturePool` design:
both masks request a 128x128 source, so the pool hands back the same
`filterTexture_1` with `frame.width/height` rewritten and `updateUvs()`
called on the texture itself — but the *filter's* derived `_textureMatrix`
uniform is never re-derived because the equality guard fires first. The
reporter confirms a workaround: forcing `this._textureMatrix.update()` at
the top of `MaskFilter.apply()` restores correct UVs (their
`patchMaskFilterApply()` shim in the linked repro).

## Difficulty Rating
4/5

## Adversarial Principles
- pooled-resource identity collision (same handle, different intent)
- uniform staleness across superficially-independent draws
- equality-guard short-circuit hides a required side effect (`update()`)
- bug is invisible without comparing per-draw uniform values
- visual symptom is "wrong size" — easily mistaken for a bounds/layout bug

## How OpenGPA Helps
A single per-draw uniform inventory ("for each draw call, give me every
sampler binding and the value of every active uniform that references the
bound mask texture") shows draw call 1 and draw call 2 with identical
`uMapCoord = (0.781, 0.625)` despite the texture's *contents* having
changed between them. Comparing the texture's white-region extent on the
GPU against the `uMapCoord` value at the consuming draw immediately
flags the inconsistency — no framework knowledge required.

## Source
- **URL**: https://github.com/pixijs/pixijs/issues/11995
- **Type**: issue
- **Date**: 2026-04-18
- **Commit SHA**: (n/a)
- **Attribution**: Reported on the PixiJS issue tracker; the flow
  breakdown in the issue body (annotated by the reporter as
  AI-assisted) traces the regression to the
  `MaskFilter._textureMatrix.texture` setter's early-return.

## Tier
core

## API
opengl

## Framework
none

## Bug Signature
```yaml
type: unexpected_state_in_draw
spec:
  rule: "uMapCoord at draw call 1 must not equal uMapCoord at draw call 2 when the bound mask texture's live sub-region has changed between the draws"
  draw_call_indices: [0, 1]
  offending_uniform: uMapCoord
  shared_texture_uniform: uMask
  observed_state:
    draw_0: { uMapCoord: [0.78125, 0.625] }   # 100/128, 80/128 — correct for mask A
    draw_1: { uMapCoord: [0.78125, 0.625] }   # stale; should be 70/128, 110/128
  expected_state:
    draw_1: { uMapCoord: [0.546875, 0.859375] }
```

## Upstream Snapshot
- **Repo**: https://github.com/pixijs/pixijs
- **SHA**: 6e59c6fd0fb031f661f4d7db99dd44f45f5e4ef1
- **Relevant Files**:
  - src/filters/mask/MaskFilter.ts  # base of fix PR #11997 (TextureMatrix forced update on pooled reuse)
  - src/rendering/renderers/shared/texture/TextureMatrix.ts
  - src/rendering/renderers/shared/texture/TexturePool.ts

## Predicted OpenGPA Helpfulness
- **Verdict**: yes
- **Reasoning**: The bug surfaces as a per-draw uniform value that is
  silently wrong relative to the bound texture's intended use. OpenGPA's
  Tier-1 raw uniform capture exposes the discrepancy directly: two draw
  calls sharing one texture object but expecting different UV transforms
  is a one-query diagnostic. No heuristic or framework hook is needed —
  the agent just compares `uMapCoord` between the two draws and notices
  it didn't change despite the mask sub-region having changed.

## Observed OpenGPA Helpfulness
- **Verdict**: ambiguous
- **Evidence**: validation skipped (--no-validate)
