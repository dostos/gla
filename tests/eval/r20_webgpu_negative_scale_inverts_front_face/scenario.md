# R20: WebGPU: Negative scale inverts front-face direction

## User Report

On webGPU only (not the webGL2 fallback) the following results in the front-face direction inverting:

```js
tubeTop.scale.set(newXY.y, rawXY.x * 2, newXY.y)
tubeBottom.scale.set(newXY.y, -rawXY.x * 2, newXY.y)
```

(WebGPU) - Bugged? The tube with negative Y scale appears incorrect.
(WebGL2 Fallback) - Normal

I'm keen to get a PR in here if possible, appreciated if someone wants to point me generally where to hunt for webGPU mesh-scale / face-direction logic.

Live example: https://jsfiddle.net/vjgan6xh/1/

Version: ^0.179.1 — Desktop Chrome, macOS/Linux

## Ground Truth

A model matrix with negative scale on one axis has a negative determinant, which flips triangle winding in clip space from CCW to CW (or vice versa). If the renderer fixes `frontFace = CCW` + `cullMode = BACK` unconditionally, the mirrored mesh's now-CW surface is classified as a back face and culled before rasterization. The mesh disappears on the first frame instead of rendering mirrored. Before the upstream fix, the WebGPU backend exhibited this while the WebGL backend did not, because the two backends disagreed on `frontFace`/`cullMode` conventions relative to their clip-space orientation.

The linked PR that fixes the bug identifies the precise mismatch:

> The PR makes sure the WebGPU backend implements the render pipeline values for `frontFace` and `cullMode` like in WebGL backend.

Root cause: the WebGPU backend's chosen convention for `frontFace`/`cullMode` did not mirror what WebGL uses relative to clip-space handedness. Negative-determinant transforms (such as `scale.y = -1`) flip the clip-space winding of each triangle; without an aligned convention — or a per-object compensation that swaps `frontFace` when `det(model) < 0` — the backend culls the visible side of mirrored meshes.

## Expected Correct Output
Both triangles render: the left one at its normal orientation, the right one mirrored along Y — but both visible and red. The right-half center pixel is red (>128).

## Actual Broken Output
Only the left triangle renders. The negative-Y-scaled right triangle is culled because its effective winding flipped from CCW to CW and the `GL_BACK` cull mode drops it. The right-half center pixel is black (clear color).

## Difficulty Rating
3/5

## Adversarial Principles
- negative-determinant-flips-winding
- backend-convention-mismatch
- no-gl-error-silent-cull

## How OpenGPA Helps
An OpenGPA query like "for draw N, what were `GL_CULL_FACE_MODE` and `GL_FRONT_FACE`, and what is the sign of det(model matrix) in uniform `u_model`?" surfaces the combination: `BACK` + `CCW` + `det(u_model) < 0`, i.e., the back-face cull is eating the mirrored mesh's visible side. That pinpoints the fix (swap front face or cull mode on negative-determinant transforms) without guessing between blending, depth, or shader bugs.

## Source
- **URL**: https://github.com/mrdoob/three.js/issues/31764
- **Type**: issue
- **Date**: 2025-11-10
- **Commit SHA**: (n/a)
- **Attribution**: Reported on three.js issue tracker; fixed by linked PR #31769 (@sunag, aligning WebGPU backend `frontFace`/`cullMode` to WebGL)

## Tier
core

## API
opengl

## Framework
none

## Bug Signature
```yaml
type: framebuffer_dominant_color
spec:
  region: right_half_center_pixel
  expected_dominant: "red (mirrored triangle rasterized)"
  actual_dominant: "black (negative-det triangle culled by GL_BACK + GL_CCW)"
  tolerance: "red channel > 128 ⇒ correct; red channel ~0 ⇒ bug"
```

## Upstream Snapshot
- **Repo**: https://github.com/mrdoob/three.js
- **SHA**: cf60b969c46b0b27e1262b1e24dff908480a89cf
- **Relevant Files**:
  - src/renderers/webgpu/WebGPUBackend.js  # base of fix PR #31769 (align frontFace/cullMode to WebGL)
  - src/renderers/webgpu/utils/WebGPUPipelineUtils.js
  - src/renderers/common/nodes/NodeMaterial.js

## Predicted OpenGPA Helpfulness
- **Verdict**: yes
- **Reasoning**: The bug is a per-draw interaction between static pipeline state (`GL_FRONT_FACE`, `GL_CULL_FACE_MODE`) and a per-object uniform (model matrix determinant). OpenGPA's ability to correlate cull state with shader-uniform values for a specific draw call lets a developer see that mirrored meshes silently drop primitive counts, directly implicating the winding/cull convention rather than blending, depth, or geometry upload.

## Observed OpenGPA Helpfulness
- **Verdict**: ambiguous
- **Evidence**: validation skipped (--no-validate)
