# R30_DISPLAYP3_AND_EFFECTCOMPOSER_DOESN_T_WOR: EffectComposer drops renderer's output colorspace

## User Report
### Description

Adding EffectComposer to the wide gamut example breaks the output colorspace.

Expected result: the displayp3 texture should be visible on both sides of the
slider.

As far as I can tell `OutputPass` should figure out the colorspace from the
renderer by itself here:
https://github.com/mrdoob/three.js/blob/80587e802b6104083c56f70d9d4275620b4d7915/examples/jsm/postprocessing/OutputPass.js#L99
and I can't find any colorspace settings on EffectComposer.

### Reproduction steps

1. Clone this branch: https://github.com/Doerge/three.js/tree/bug-report-display-p3-effect-composer
2. Serve the root and open the http://localhost:8000/examples/webgl_test_wide_gamut.html example that adds EffectComposer to the existing wide gamut example.
3. Both sides of the slider should correctly show the wide gamut texture on a wide gamut display.

### Code

```js
renderer = new THREE.WebGLRenderer( { antialias: true } );
renderer.setAnimationLoop( animate );

composer = new EffectComposer( renderer );
const renderPass = new RenderPass( sceneR, camera );
composer.addPass( renderPass );
const glitchPass = new GlitchPass();
composer.addPass( glitchPass );
const outputPass = new OutputPass()
composer.addPass( outputPass );

function animate() {
    renderer.setScissor( 0, 0, sliderPos, window.innerHeight );
    renderer.render( sceneL, camera );

    renderer.setScissor( sliderPos, 0, window.innerWidth, window.innerHeight );
    composer.render( sceneR, camera );
}
```

### Version

0.183.0

### Device / Browser / OS

Desktop / Chrome / MacOS

## Expected Correct Output
Both halves of the wide-gamut slider example show the DisplayP3 texture at full gamut on a wide-gamut display — identical color reproduction on the left (direct) and right (composed) sides.

## Actual Broken Output
The left side (direct `renderer.render`) shows the correct DisplayP3-encoded output. The right side (passed through `EffectComposer` with `RenderPass` + `GlitchPass` + `OutputPass`) is visibly desaturated / wrong-gamut because the pipeline ends up in sRGB encoding.

## Ground Truth
The reporter states the expectation and locates the failure site directly:

> As far as I can tell `OutputPass` should figure out the colorspace from the renderer by itself here: https://github.com/mrdoob/three.js/blob/80587e802b6104083c56f70d9d4275620b4d7915/examples/jsm/postprocessing/OutputPass.js#L99 and I can't find any colorspace settings on EffectComposer.

That is: `OutputPass` (and/or the intermediate render targets that `EffectComposer` allocates for its passes) do not inherit `renderer.outputColorSpace`, so the final write to the canvas is encoded as sRGB regardless of what the user configured. The reporter's follow-up ("Wow, thanks for the ultra fast fix @Mugen87 🙏") confirms that a maintainer patched this against the same assumption — propagating the renderer's output colorspace into the composer's output step.

## Difficulty Rating
4/5

## Adversarial Principles
- cross-component-metadata-propagation
- colorspace-at-pipeline-boundaries
- silent-default-overrides-user-configuration

## How OpenGPA Helps
An agent can query `/api/v1/frames/current/draw_calls` to locate the final blit/OutputPass draw and inspect its bound framebuffer format and any sRGB-encode state (`GL_FRAMEBUFFER_SRGB`), then compare against the draw that wrote the direct path. The mismatch — direct path writes with sRGB encoding to a wide-gamut swapchain, composed path writes from an RGBA8 intermediate without the encoding step — surfaces the missing colorspace propagation through the composer chain.

## Source
- **URL**: https://github.com/mrdoob/three.js/issues/33030
- **Type**: issue
- **Date**: 2026-04-19
- **Commit SHA**: (n/a)
- **Attribution**: Reported by @Doerge; fix by @Mugen87

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
  draw_call_role: final_output_blit
  state: framebuffer_srgb_encoding
  expected: enabled_or_wide_gamut_target
  actual: disabled_rgba8_intermediate
```

## Upstream Snapshot
- **Repo**: https://github.com/mrdoob/three.js
- **SHA**: ee01f32583d15adf56c828c82fa63dabb9eec1b9
- **Relevant Files**:
  - examples/jsm/postprocessing/OutputPass.js
  - examples/jsm/postprocessing/EffectComposer.js
  - examples/jsm/postprocessing/RenderPass.js
  - src/renderers/WebGLRenderer.js
  - src/constants.js
  - examples/webgl_test_wide_gamut.html

## Predicted OpenGPA Helpfulness
- **Verdict**: ambiguous
- **Reasoning**: OpenGPA can clearly surface the *mechanical* discrepancy — the intermediate RGBA8 FBO, the missing `GL_FRAMEBUFFER_SRGB` on the final composed write, and the divergence from the direct render path. That's enough for an agent to point at the post-process chain as the culprit. But mapping "intermediate FBO has wrong format / encode state" back to the specific three.js abstraction ("OutputPass doesn't read `renderer.outputColorSpace`") still requires the agent to read the JS pipeline — OpenGPA shows the symptom, not the API-level cause.

## Observed OpenGPA Helpfulness
- **Verdict**: ambiguous
- **Evidence**: validation skipped (--no-validate)
