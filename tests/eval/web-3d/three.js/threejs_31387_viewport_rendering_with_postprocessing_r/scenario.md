# R17: Viewport rendering with PostProcessing renderer overwrites scene

## User Report
With the WebGPURenderer and TSL node system I am not seeing `renderer.autoClear` respected when rendering with the post processing renderer. Rendering to a viewport directly after does not respect the frame buffer's color and overwrites with background.

Reproduction steps:
1. Create a basic PostProcessing node with a scene pass
2. Call PostProcessing render
3. Render to a viewport after post processing, notice white background

```js
renderer.clear();

// WORKS
// renderer.render( scene, camera );
// BREAKS
postProcessing.render()

// minimap-like ViewHelper
{
  const dim = 128;
  const x = renderer.domElement.offsetWidth - dim;
  const y = renderer.domElement.offsetHeight - dim;
  renderer.getViewport(viewport);
  renderer.setViewport(x, y, dim, dim);
  renderer.render(minMapScene, orthoCamera);
  renderer.setViewport(viewport);
}
```

(Original thread: https://discourse.threejs.org/t/issue-with-post-processing-and-viewport-and-renderer-clear-flags/85011)

## Expected Correct Output
Tone-mapped scene fills the presented framebuffer; a small minimap (green triangle on white) is composited in the upper-right corner. The center pixel of the framebuffer remains the tone-mapped scene color (a near-red).

## Actual Broken Output
The center pixel of the presented framebuffer is white. The tone-mapped scene from post-processing is gone — only the corner viewport region carries the green minimap on a white background.

## Ground Truth
`PostProcessing.render()` and the normal `renderer.render()` path do not share framebuffer/clear assumptions. The post-processing path renders into an internal target that effectively *is* the presented surface; a follow-up `renderer.render()` issues a `clear` on that same surface before drawing into the small viewport region, wiping the post-processed scene. Per upstream maintainer @Mugen87:

> A manual `render()` call after `postProcessing.render()` is problematic. `PostProcessing` and normal `render()` calls have different approaches for tone mapping and color space conversion. Besides, clear operation affect different internal framebuffers so you need a different approach.

The recommended workaround is to make the minimap a `pass()` inside the post-processing graph and blend it (`postProcessing.outputNode = TSL.blendColor(scenePass, mapPass)`). A scoped framework fix was discussed in the same thread: add `PassNode.setViewport()` / `PassNode.setScissor()` (alternatively `RenderTarget.autoScissor` / `autoViewport`) so a pass can constrain its draw to a sub-region without `RenderTarget.setSize()` clobbering the viewport/scissor state.

In raw OpenGL terms the failure mode reduces to: `glClear(GL_COLOR_BUFFER_BIT)` is issued before the small-viewport draw, but `glClear` ignores `glViewport` — it clears the entire color attachment unless `glScissor` + `GL_SCISSOR_TEST` are enabled. The minimal repro reproduces exactly this: step 3's clear wipes the tone-mapped output left in `postFbo` by step 2.

## Difficulty Rating
3/5

## Adversarial Principles
- Two render paths whose framebuffer/clear assumptions silently conflict
- glClear ignores viewport (only scissor constrains it)
- Implicit framebuffer state held across pipeline phase boundaries

## How OpenGPA Helps
The per-draw framebuffer-binding view shows that step 3's `glClear` and triangle draw target the *same* FBO as the post-processing tone-map quad — there is no rebind to the default framebuffer between the phases. Pixel sampling between draws further pinpoints when the center pixel transitions from red to white, attributing the loss directly to the clear call rather than to the minimap geometry.

## Source
- **URL**: https://github.com/mrdoob/three.js/issues/31387
- **Type**: issue
- **Date**: 2025-08-15
- **Commit SHA**: (n/a)
- **Attribution**: Reported by @grahnen; diagnosed by @Mugen87

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
  region: { x_min: 96, y_min: 96, x_max: 160, y_max: 160 }
  expected_dominant: [216, 25, 25]
  actual_dominant: [255, 255, 255]
  tolerance: 24
```

## Predicted OpenGPA Helpfulness
- **Verdict**: yes
- **Reasoning**: Per-draw framebuffer-binding inspection plus pixel sampling between draws lets the agent attribute the lost scene to a specific `glClear` after the post-processing pass — something hard to see from a final screenshot alone, since the corner minimap still appears correctly and only the center has been overwritten.

## Observed OpenGPA Helpfulness
- **Verdict**: ambiguous
- **Evidence**: validation skipped (--no-validate)
