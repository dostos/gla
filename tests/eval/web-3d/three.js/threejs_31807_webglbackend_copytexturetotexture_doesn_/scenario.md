# R7: WebGLBackend copyTextureToTexture drops layers of 3D render targets

## User Report
In WebGL fallback, `copyTextureToTexture` doesn't copy all layers of 3D
render target textures.

I noticed the implementation of `copyTextureToTexture` in
[WebGLBackend](https://github.com/mrdoob/three.js/blob/r179/src/renderers/webgl-fallback/utils/WebGLTextureUtils.js#L699)
deviates from the one in
[WebGLRenderer](https://github.com/mrdoob/three.js/blob/r179/src/renderers/WebGLRenderer.js#L3049).
I can make a PR if those can be made the same (there are a couple of
differences in the conditionals which I don't fully understand).

### Reproduction

```ts
const rt1 = new RenderTarget3D(size, size, size)
// Draw the contents of "rt1"

const rt2 = new RenderTarget3D(size, size, size)
renderer.setRenderTarget(rt2)
void renderer.clear()
renderer.setRenderTarget(null)

renderer.copyTextureToTexture(
  rt1.texture,
  rt2.texture,
  new Box3(new Vector3(), new Vector3().setScalar(size))
)
```

Live example: https://jsfiddle.net/shotamatsuda/xu8zs0g2/

Version r179, Chrome on macOS.

## Expected Correct Output
Every depth slice of `rt2.texture` matches the corresponding slice of
`rt1.texture` after `copyTextureToTexture` — reading pixels at z=0..N-1
returns the colors that were drawn into the source.

## Actual Broken Output
Only the first depth slice (z=0) of the destination 3D texture matches
the source. Every other layer (z=1..N-1) is left at its pre-copy
contents (black / clear). In the minimal C repro:

```
dst layer 0 center rgba=255,0,0,255
dst layer 1 center rgba=0,0,0,0
dst layer 2 center rgba=0,0,0,0
dst layer 3 center rgba=0,0,0,0
```

## Ground Truth
The reporter identifies the defect directly by contrasting the two
backend implementations:

> the implementation of `copyTextureToTexture` in WebGLBackend deviates
> from the one in WebGLRenderer

`WebGLRenderer.copyTextureToTexture` iterates across the `depth` of
`Box3` and rebinds a fresh `TEXTURE_2D_ARRAY` / `TEXTURE_3D` layer per
slice before copying, while `WebGLBackend`'s fallback at
`src/renderers/webgl-fallback/utils/WebGLTextureUtils.js:699` only
performs the 2D codepath and never iterates over the source texture's
depth. The result is a single-slice copy into the base layer of the
destination 3D texture, leaving higher layers untouched.

The minimal reproducer models the same failure mode in raw GL by
attaching only layer 0 of the destination via
`glFramebufferTextureLayer` and blitting once, then probing every
destination layer via `glReadPixels` — layers ≥1 remain at their
pre-copy clear value.

## Difficulty Rating
3/5

## Adversarial Principles
- silent-data-loss (no GL error; the copy "succeeded" but is incomplete)
- layered-resource-mismatch (treating a 3D/array resource as 2D)
- API-parity-drift (two backends claim identical semantics but diverge)

## How OpenGPA Helps
Querying the destination texture's per-layer state (e.g. a
`texture/layer_histogram` or per-slice pixel sampling on the 3D texture)
shows layer 0 populated and layers 1..N-1 at the initial clear value,
immediately localizing the copy to a single slice. The draw-call log
reveals a single `glBlitFramebuffer` against a `FramebufferTextureLayer`
bound at layer 0, rather than the expected `LAYERS` blits — the
signature of a 2D-only fallback.

## Source
- **URL**: https://github.com/mrdoob/three.js/issues/31807
- **Type**: issue
- **Date**: 2026-04-20
- **Commit SHA**: (n/a)
- **Attribution**: Reported by the three.js community against r179

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
  target: destination_3d_texture
  layer: 1
  pixel: [4, 4]
  expected_rgba: [0, 255, 0, 255]
  actual_rgba: [0, 0, 0, 0]
  note: |
    After copyTextureToTexture(src3D, dst3D, full_box), the destination
    texture's non-base layers retain their pre-copy (cleared) contents
    instead of matching the source.
```

## Predicted OpenGPA Helpfulness
- **Verdict**: yes
- **Reasoning**: The bug is a structural mismatch between the draw-call
  trace (one blit, one layer bound) and the declared operation (copy a
  full Box3 across all slices). OpenGPA's per-draw-call GL state and
  per-layer texture sampling make the single-slice scope of the copy
  directly observable, without needing the agent to read and compare
  the two backend implementations.

## Observed OpenGPA Helpfulness
- **Verdict**: ambiguous
- **Evidence**: validation skipped (--no-validate)
