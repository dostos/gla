# R18_WEBGLRENDERER_REVERSED_DEPTH_NOT_WORKING: Reversed depth buffer renders black through PMREMGenerator

## User Report
Several examples are rendering black when reversed depth buffer is set.

`webgl_loader_gltf_compressed.html` is one of them.

The bug appears to be related to the use of `PMREMGenerator.fromScene()`.

Reproduction steps: Set reversed depth buffer in `webgl_loader_gltf_compressed.html`.

Version: r179dev. Desktop, Chrome, macOS.

Extra hints from the thread:
- Setting `material.depthTest = false` in `createAreaLightMaterial()` in `RoomEnvironment.js` mitigates the issue.
- Commenting out a single line in `PMREMGenerator.js` (line 137) makes `webgl_loader_gltf_compressed.html` render correctly with reversed depth.

## Expected Correct Output
The scene/environment composed by PMREMGenerator appears in the rendered frame — in the minimal repro, a red triangle dominates the center of the offscreen target (center pixel ≈ `(217, 25, 25)`).

## Actual Broken Output
The framebuffer is black (or, in the minimal repro, the clear color ≈ `(12, 12, 25)`) because every fragment rendered into the reversed-Z target fails the depth test.

## Ground Truth
Per the issue thread, the root cause is that `PMREMGenerator._sceneToCubeUV()` sets `renderer.autoClear = false`. With autoClear disabled, the cubeUV render target's depth attachment is never cleared to the value the reversed-Z pipeline expects (0.0). Upstream maintainer:

> I think the issue is that `_sceneToCubeUV()` sets `autoClear` to `false` which means the internal render target does not have an appropriate clear value for the (reversed) depth buffer. If you add the below code directly under the `renderer.autoClear = false;` statement at the beginning of the method, `webgl_loader_gltf_compressed` works again.
>
> ```js
> renderer.setRenderTarget( cubeUVRenderTarget );
> renderer.clearDepth();
> renderer.setRenderTarget( null );
> ```
>
> This is in general a problem since whenever you use a reversed depth buffer and don't use `autoClear=true`, you can't rely on the default depth value in the buffer. You must clear at least once manually with the reversed clear value.

In raw GL terms: with `glDepthFunc(GL_GREATER)` active, the depth buffer must be cleared to 0.0 for any subsequent fragment (whose window-space depth is in `[0,1]`) to pass the test. If the target retains the standard clearDepth=1.0 value — either because no depth clear has been issued, or because the last depth clear used the default — then `GL_GREATER(fragment_depth, 1.0)` is false for every fragment and nothing is written. The minimal repro models exactly this: the render target is allocated and cleared with defaults (depth=1.0), then a scene pass only clears the color attachment before drawing with `GL_GREATER` — so the triangle is rejected wholesale.

## Difficulty Rating
4/5

## Adversarial Principles
- Pipeline state (depth func) and per-target clear value must agree, but the agreement is invisible from the scene graph
- autoClear=false interacts with reversed-Z in a way that is silent unless the first-frame depth contents are exactly the reversed clear value
- The failure is total (entire target black) rather than partial, so pixel diffs alone don't localize which stage dropped the geometry

## How OpenGPA Helps
Per-draw state inspection surfaces the mismatch: for the offending draw, the bound framebuffer's depth attachment was last cleared with clearDepth=1.0 while the pipeline's `DEPTH_FUNC` is `GL_GREATER`. A depth-attachment histogram before the draw (all 1.0) combined with the depth-func state makes the "GL_GREATER vs. 1.0 rejects everything" conclusion mechanical rather than speculative. Without OpenGPA the debugger typically has to bisect by commenting out lines upstream (as the reporter did in comment 3) to localize the offending render path.

## Source
- **URL**: https://github.com/mrdoob/three.js/issues/31413
- **Type**: issue
- **Date**: 2025-11-24
- **Commit SHA**: (n/a)
- **Attribution**: Reported by @CodyJasonBennett; diagnosed by @Mugen87

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
  region: { x_min: 120, y_min: 120, x_max: 136, y_max: 136 }
  expected_dominant: [217, 25, 25]
  actual_dominant: [12, 12, 25]
  tolerance: 24
```

## Predicted OpenGPA Helpfulness
- **Verdict**: yes
- **Reasoning**: The bug is an invisible state/target coupling — a `GL_GREATER` depth func against a depth attachment whose cleared value is 1.0. An agent with per-draw access to the bound framebuffer, its last depth-clear value, and the current `DEPTH_FUNC` can derive the contradiction directly from the capture; from a screenshot alone the failure is indistinguishable from dozens of other "scene renders black" bugs.

## Observed OpenGPA Helpfulness
- **Verdict**: ambiguous
- **Evidence**: validation skipped (--no-validate)
