# R9_THREE_JS_RESIZING_CANVAS: three.js EffectComposer not resized with renderer

## User Report
I have been working on a 3D project where we show 3D object in the web browser using Three.js Library.
The problem is:

1st the model is displayed in a small `dom` element or when the browser window itself is small.
Then when the window (or the `dom` element is resized) the model become pixelated

Following are some screenshots:
### Before resize:

### After resize:

### How it should be after resize:

Here is the part of code that is setting the the model dimensions (height and width), and this function gets called when the resize event if fired:

```
console.log("domChanged fired")

instance.domBoundingBox = instance.dom.getBoundingClientRect();
instance.domCenterPos.x = instance.domBoundingBox.width / 2 + instance.domBoundingBox.left;
instance.domCenterPos.y = instance.domBoundingBox.height / 2 + instance.domBoundingBox.top;

var width = instance.dom.clientWidth, height = instance.dom.clientHeight;
instance.domWidthHalf = width / 2, instance.domHeightHalf = height / 2;

// TODO: fire event to expose it to site developers

// here we should update several values regarding width,height,position
if(instance.cameraReal) {
    instance.cameraReal.aspect = instance.dom.clientWidth / instance.dom.clientHeight;
    instance.cameraReal.updateProjectionMatrix();
}

if(instance.renderer3D)
    instance.renderer3D.setSize(instance.dom.clientWidth, instance.dom.clientHeight);
```

Can anybody give me a hint? I've been working on that a couple of days already but no clue so far

## Expected Correct Output
A smooth, high-resolution frame that fills the resized canvas with the same perceived sharpness it had before the resize — gradients and edges are rendered natively at the canvas's current pixel count.

## Actual Broken Output
A blocky, low-resolution image stretched to fill the resized canvas. The content was rasterised at the old 200x150 offscreen resolution and then scaled up into an 800x600 presentation surface, so features that should be pixel-sharp instead appear as 4x4 blocks.

## Ground Truth
When the browser window (or the containing DOM element) is resized, the application calls `renderer.setSize()` on the three.js `WebGLRenderer` but forgets to call `composer.setSize()` on the companion `EffectComposer`. The composer's two internal ping-pong `WebGLRenderTarget`s remain at their pre-resize dimensions. The post-processing pipeline therefore renders the scene into an undersized offscreen FBO and then copies that FBO into the now-larger default framebuffer, producing a pixelated, upscaled image.

The OP's own accepted answer identifies `EffectComposer` as the missing piece:

> Finally the problem were solved the actually problem was coming from because the application is using the `THREE.EffectComposer` object ... the composer needed to have the size updated after the event handler function like following:
> `instance.composer.setSize(instance.dom.clientWidth, instance.dom.clientHeight);`

The root cause is that `EffectComposer` allocates its read/write `WebGLRenderTarget`s in its constructor from the renderer's size at that moment. `renderer.setSize()` reconfigures the default drawing buffer / canvas, but does not propagate to the composer, whose render targets own independent FBO + texture storage. Every `renderer.setSize(w, h)` must therefore be mirrored by a matching `composer.setSize(w, h)`. This is the canonical symptom of an offscreen-FBO size / presentation-surface size mismatch.

## Difficulty Rating
2/5

## Adversarial Principles
- fbo_size_mismatch_on_resize
- offscreen_render_target_stale_dimensions
- upscale_artifact_from_undersized_source

## How OpenGPA Helps
A frame-overview query exposes, per draw call, the bound framebuffer's color-attachment dimensions and the current viewport; the scene-render draw call reports `color_attachment0.size = 200x150` and `viewport = 0,0,200,150`, while the final blit / present targets the 800x600 default framebuffer. A single cross-check "does the offscreen RT used to compose this frame match the presentation surface size?" directly surfaces the bug.

## Source
- **URL**: https://stackoverflow.com/questions/20290402/three-js-resizing-canvas
- **Type**: stackoverflow
- **Date**: 2013-12-01
- **Commit SHA**: (n/a)
- **Attribution**: Question and self-accepted answer on Stack Overflow identifying `composer.setSize()` as the fix.

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
  draw_call_index: 0
  state_key: color_attachment_size_vs_presentation_size
  expected: offscreen color-attachment dimensions match the presentation framebuffer (800x600)
  actual: offscreen color-attachment dimensions are 200x150 while the frame is presented at 800x600
```

## Predicted OpenGPA Helpfulness
- **Verdict**: yes
- **Reasoning**: OpenGPA's frame overview exposes per-draw-call viewport and bound-framebuffer color-attachment dimensions plus the final presented framebuffer size. A simple cross-comparison between the scene-render target's size and the presentation surface's size surfaces the mismatch deterministically. Without OpenGPA, the agent must reason backward from the visual symptom ("looks pixelated") to guess at the cause — possibly blaming texture filtering, DPR, or shader code before landing on stale composer render targets.

## Observed OpenGPA Helpfulness
- **Verdict**: ambiguous
- **Evidence**: validation skipped (--no-validate)
