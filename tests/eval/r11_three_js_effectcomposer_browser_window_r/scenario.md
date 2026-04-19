# R11: three.js EffectComposer resize leaves blend shader sampling a stale render target

## User Report
I have a rendering setup where a resizing problem occurs when resizing the browser window.

I render two scenes, one of them for objects with postprocessing effects applied. For the effects I use the THREE.EffectComposer and shaders from the example directory.

The two scene renders are then additively blended with the help of another shader example.

See following simplified setup: http://jsbin.com/hibum/18/edit?js,output (in the HTML part I include a few js sources from the three.js repository)

If you shrink the output panel, then reload the page and again widen the panel, you'll see something like this:

The main scene (blue sphere) did update its rendering size, but the effects scene (orange sphere) still has the same resolution, just upscaled.

I can't find out which render target or renderer (or shader uniform?) needs to be updated at the browser resize event to still correctly output the image after resizing.

For the main composer it works with a `setSize()` call, but if I do that on the effects composer, it won't render the effects scene.

Any help is appreciated, thanks.

## Expected Correct Output
Both the main pass (blue sphere) and the effects pass (orange sphere) are
sampled from full-resolution render targets; the blended image is crisp at the
new window size.

## Actual Broken Output
The main pass (blue) is crisp at the new size, but the effects pass (orange) is
stretched/upscaled — clearly sampled from a texture smaller than the current
viewport.

## Ground Truth
After a browser resize, the three.js post-processing pipeline recreates its
EffectComposer render targets at the new size, but the final additive-blend
shader's `tDiffuse2` sampler uniform still references the *old*, smaller
effects render target. The composited frame shows the main scene at the new
resolution while the post-processed content appears upscaled from the pre-resize
size.

The root cause is a stale sampler uniform, not a missing resize call. Calling
`setSize()` or `reset()` on the EffectComposer recreates its internal render
target textures, but any shader material that captured a reference to the *old*
render-target texture object keeps sampling the orphaned texture. Per the
accepted answer on the thread:

> I had to reset both EffectComposers and then also reset the `tDiffuse2`
> uniform of the AdditiveBlendShader:
> `blend.uniforms.tDiffuse2.value = effects.renderTarget2;`

i.e., both composers need `reset()` **and** the blend-pass sampler uniform
must be rebound to the new render target texture; otherwise the uniform still
points at the pre-resize texture object.

## Difficulty Rating
3/5

## Adversarial Principles
- stale_sampler_uniform_after_resize
- render_target_lifetime_mismatch
- silent_correctness_bug_no_gl_error

## How OpenGPA Helps
An agent inspecting the final composite draw call via
`/api/v1/frames/current/draw_calls/N/textures` sees that one of its bound
sampler2Ds has dimensions `200x150` while the viewport is `800x600` — an
immediate smoking gun that a sampler is bound to a stale render target from
before the resize.

## Source
- **URL**: https://stackoverflow.com/questions/23460040/three-js-effectcomposer-browser-window-resize-issue
- **Type**: stackoverflow
- **Date**: 2014-05-05
- **Commit SHA**: (n/a)
- **Attribution**: Question and accepted answer by the original poster on Stack Overflow

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
  draw_call_selector: last_draw_to_default_framebuffer
  expectation: all_bound_sampler_textures_match_viewport_dimensions
  violation: sampler_texture_dimensions_smaller_than_viewport
  sampler_uniform_name: tDiffuse2
  expected_texture_size: [800, 600]
  actual_texture_size: [200, 150]
```

## Predicted OpenGPA Helpfulness
- **Verdict**: yes
- **Reasoning**: The diagnosis is a direct lookup: "for each sampler bound to
  the compositing draw, what are the source texture's dimensions?" Tier-1 raw
  capture already records bound textures per draw call and each texture's
  allocated size, so the mismatch (200x150 sampler feeding an 800x600 viewport)
  is visible without any framework metadata. A plain-eyeball LLM looking only
  at rendered pixels would likely misattribute the blur to filtering or DPR
  issues; OpenGPA turns it into a structural state check.

## Observed OpenGPA Helpfulness
- **Verdict**: ambiguous
- **Evidence**: validation skipped (--no-validate)
