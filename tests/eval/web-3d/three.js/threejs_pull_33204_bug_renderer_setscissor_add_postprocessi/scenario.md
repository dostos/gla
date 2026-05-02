# R6: PostProcessing in split-screen viewport corrupts the other half

## User Report
After setting up a split-screen render in three.js (left half = `scene`, right half = `scene2` via `PostProcessing`), the left half doesn't display correctly — adding `PostProcessing` to the right viewport clobbers the left viewport region.

Repro setup:
- `WebGPURenderer` (also reproduces with `forceWebGL: true`)
- `renderer.setPixelRatio(window.devicePixelRatio)` then `renderer.setSize(SCREEN_WIDTH, SCREEN_HEIGHT)`
- `renderer.setScissorTest(true)`
- Per frame:
  - `setScissor(0, 0, W/2, H)` + `setViewport(0, 0, W/2, H)` → `renderer.render(scene, camera)`
  - `setScissor(W/2, 0, W/2, H)` + `setViewport(W/2, 0, W/2, H)` → `postProcessing.render()`

Live repro: https://jsfiddle.net/dc6mnv9a/2/

Three.js version: r173. Reproduces on both WebGL and WebGPU backends.

## Expected Correct Output
Two side-by-side viewports rendering independently — green cube on the left half, red cube (post-processed) on the right half.

## Actual Broken Output
The left half is missing / blanked out after the right-half post-processing pass runs. Only the right viewport contains visible content.

## Ground Truth
Per maintainer in PR #33204 ("PassNode: Fix scissor and viewport setup"):

> The scene setup in #33203 isn't valid but even with the intended approach it turns out the scissor and viewport dimensions are not correctly computed in `PassNode`. The pixel ratio might not be correct when `setScissor()` and `setViewport()` are called so it's important to compute the effective dimensions in `setSize()`.

The fix was to compute the effective scissor/viewport dimensions (multiplying by `_pixelRatio` and `_resolutionScale`) inside `PassNode.setSize()` rather than at the time `setScissor()`/`setViewport()` are called on the pass — because by then the renderer's pixel ratio may not reflect the values that were active when the user supplied the scissor/viewport rectangles. Without this, the post-processing pass writes to the wrong region of the framebuffer, overlapping (and overwriting) the previously-rendered left viewport.

See https://github.com/mrdoob/three.js/pull/33204 (fixes #33203).

## Fix
```yaml
fix_pr_url: https://github.com/mrdoob/three.js/pull/33204
fix_sha: 21ae3131839e11323b4449c7374e876628b88a38
fix_parent_sha: 21ae3131839e11323b4449c7374e876628b88a38
bug_class: framework-internal
framework: three.js
framework_version: r173
files:
  - src/nodes/display/PassNode.js
change_summary: >
  PassNode previously applied scissor and viewport rectangles using whatever
  pixel ratio was current at draw time, which could differ from the ratio
  active when the user originally configured them. The fix moves the
  effective-dimension computation (multiplying by `_pixelRatio` and
  `_resolutionScale`) into `setSize()`, so the pass's scissor/viewport
  rectangles stay consistent with its render target.
```

## Flywheel Cell
primary: framework-maintenance.web-3d.code-navigation
secondary:
  - framework-maintenance.web-3d.captured-literal-breadcrumb

## Difficulty Rating
3/5

## Adversarial Principles
- bug-lives-inside-framework-not-user-code
- pixel-ratio-bugs-only-manifest-on-hidpi-or-with-explicit-setpixelratio
- multi-viewport-bugs-only-show-when-passes-are-composed-with-render

## How OpenGPA Helps
`gpa trace` over a frame would reveal that the post-processing pass issues `glScissor`/`glViewport` (or the WebGPU equivalent) with rectangle dimensions that do not match the user-supplied `setScissor(W/2, 0, W/2, H)` once the device pixel ratio is non-1 — pointing at `PassNode` as the source of the wrong rectangle. `/feedback-loops` and the per-pass framebuffer overview would show the post-processing render target overlapping the previously-rendered left viewport rather than being confined to the right half.

## Source
- **URL**: https://github.com/mrdoob/three.js/issues/33203
- **Type**: issue
- **Date**: 2026-04-29
- **Commit SHA**: 21ae3131839e11323b4449c7374e876628b88a38
- **Attribution**: Reported in three.js#33203; fix authored by maintainer in PR #33204.

## Tier
maintainer-framing

## API
opengl

## Framework
three.js

## Bug Signature
```yaml
type: code_location
spec:
  expected_files:
    - src/nodes/display/PassNode.js
  fix_commit: 21ae3131839e11323b4449c7374e876628b88a38
```

## Predicted OpenGPA Helpfulness
- **Verdict**: yes
- **Reasoning**: The bug surfaces as a wrong-sized scissor/viewport rectangle on the post-processing draw — exactly the kind of per-call GL state OpenGPA's trace and framebuffer overview tools expose. An agent comparing the user's intended rectangle (`W/2, 0, W/2, H`) against the actual `glScissor` arguments captured during the pass would see the pixel-ratio mismatch and trace it back to `PassNode`'s scissor/viewport setup.

## Observed OpenGPA Helpfulness
- **Verdict**: ambiguous
- **Evidence**: validation skipped (--no-validate)
