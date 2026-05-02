# R9: Transparent objects render with wrong brightness due to inline sRGB encoding

## User Report
When using sRGB textures (such as in 3DS models), the GammaCorrectionShader seems to brighten the texture more than when the EffectComposer is not used. The GammaCorrectionShader is needed when using the EffectComposer to produce similar colors to when the EffectComposer is not used.

**To Reproduce**
1. Create a shape with a texture and an opacity of 0.4 and use an EffectComposer, with a GammaCorrectionShader pass.
2. Create a shape with an opacity of 0.4 just using a normal render (no EffectComposer).
3. Note that the colors are brighter on the first shape.

You can see how the bottom (post-processed) is brighter for the texture and a lower opacity makes the issue more apparent. The difference is also stronger the more transparent an object is — there's not much difference with `opacity = 0.9` but with `opacity = 0.1` it's quite obvious.

As a side note, a similar problem was seen with generic shapes with color but it appears that setting the clearColor on the RenderPass can help with that issue but not with textured objects.

## Expected Correct Output
A red overlay rendered with alpha 0.5 on top of a black background should evaluate the alpha blend in linear-sRGB space and encode at the end:
- linear blend = 0.5·(1,0,0) + 0.5·(0,0,0) = (0.5, 0, 0)
- encoded for an sRGB display ≈ pow(0.5, 1/2.2) ≈ 0.730
- 8-bit framebuffer pixel ≈ rgba(186, 0, 0, 255)

## Actual Broken Output
Center pixel reads `rgba=128, 0, 0, 255`. The red channel is roughly 31% darker than it should be for a perceptually-correct linear blend. Equivalently, the apparent opacity of the overlay is wrong: a "0.5 alpha" overlay produces a pixel that, after the display's own sRGB→linear interpretation, behaves as if blended at a different coverage than 0.5.

## Ground Truth
The fragment shader applies the linear→sRGB encoding (`pow(c, 1/2.2)`) inline, on its own output, *before* the fixed-function alpha blend runs. Because the framebuffer is a normal linear-storage RGBA8 attachment with no `GL_FRAMEBUFFER_SRGB`, the GPU's blend unit then interpolates between two values that are already in non-linear sRGB space. Alpha blending is only physically meaningful on linearly-encoded color, so the result is wrong.

This was confirmed by the three.js maintainers in the upstream thread:

> The proper workflow is to render the scene in linear-sRGB color space and convert to sRGB color space as a final post-processing step. However, currently, three.js converts to sRGB color space in-line in the shader, _prior_ to blending with the drawing buffer. This is fine if the material is opaque. But if the material is transparent, it is not correct.
> — @WestLangley, https://github.com/mrdoob/three.js/issues/23019#issuecomment-995352517

> So to clarify, the upper part of the fiddle is actually too dark whereas the lower part (using post-processing) is the correct image.
> — @WestLangley, https://github.com/mrdoob/three.js/issues/23019#issuecomment-1011082262

The architectural fix landed across r152/r153, where sRGB color management became the default and a new `OutputPass` moved tone mapping + sRGB encoding into a single post-process pass that runs *after* all blending in a linear half-float render target (see https://github.com/mrdoob/three.js/issues/23019#issuecomment-1568700091 and the related #26129).

## Difficulty Rating
3/5

## Adversarial Principles
- color-space-confusion
- encode-before-blend
- visually-plausible-but-numerically-wrong

## How OpenGPA Helps
Querying the draw call for the transparent overlay reveals two facts simultaneously: (a) blending is enabled with `GL_SRC_ALPHA / GL_ONE_MINUS_SRC_ALPHA` against a linear RGBA8 framebuffer with `GL_FRAMEBUFFER_SRGB` disabled, and (b) the bound fragment shader's source contains a `pow(c, vec3(1.0/2.2))` on the outgoing color. Surfacing both facts together — without forcing the agent to guess which uniform or which texture is the "gamma" — is what lets the agent name "blending happens in sRGB space" instead of chasing the texture or the opacity uniform.

## Source
- **URL**: https://github.com/mrdoob/three.js/issues/23019
- **Type**: issue
- **Date**: 2021-12-13
- **Commit SHA**: (n/a)
- **Attribution**: Reported by @ngokevin, diagnosed by @WestLangley and @donmccurdy

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
  region:
    x: 200
    y: 200
    w: 1
    h: 1
  expected_rgba: [186, 0, 0, 255]
  tolerance: 12
  channels: [r, g, b]
```

## Predicted OpenGPA Helpfulness
- **Verdict**: yes
- **Reasoning**: The diagnosis requires correlating three pieces of GL state for the transparent draw call: the blend func/equation, the framebuffer's color encoding (`GL_FRAMEBUFFER_SRGB` state + attachment internal format), and the fragment shader source. A baseline agent without capture has to guess which of the many possible knobs (texture decode, material opacity, tone mapping, premultiplied alpha, `GL_FRAMEBUFFER_SRGB`) is at fault. OpenGPA's per-draw-call state dump — which already exposes blend state, bound program, and shader source — collapses that search into one query.

## Observed OpenGPA Helpfulness
- **Verdict**: ambiguous
- **Evidence**: validation skipped (--no-validate)
