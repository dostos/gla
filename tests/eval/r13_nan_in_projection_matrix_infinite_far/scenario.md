# R13: WebXRDepthSensing can result in invalid projectionMatrix (`NaN` values)

## User Report

When using WebXR depth sensing, Three.js adjusts the `far` and `near` properties of the camera to match the `depthFar` and `depthNear` coming from the depth-sensing module. In the case of the Meta Quest 3, the `far` value becomes `Infinity`.

Steps to reproduce:
1. Open the [`webxr_xr_dragging`](https://threejs.org/examples/#webxr_xr_dragging) example on a Quest 3 with depth sensing enabled:
   ```js
   document.body.appendChild( XRButton.createButton( renderer, {
       'optionalFeatures': [ 'depth-sensing' ],
       'depthSensing': { 'usagePreference': [ 'gpu-optimized' ], 'dataFormatPreference': [] }
   } ) );
   ```
2. Click on 'Start XR'
3. Click on 'Stop XR' to exit
4. Notice the canvas being blank after exiting

Rendering during the immersive session looks fine. But when exiting, the scene shows up empty (blank canvas). The issue started in r167.

Version: r167 — Meta Quest 3, Chrome, Android

## Ground Truth

A perspective projection matrix is built from `near = 0.1`, `far = Infinity`.
The standard `makePerspective` formulas place `far` in both the numerator and
denominator of the z-scale and z-translate entries:

- `m[10] = (far + near) / (near - far)`  →  `Inf / -Inf = NaN`
- `m[14] = (2 * far * near) / (near - far)`  →  `Inf / -Inf = NaN`

The resulting `mat4` is uploaded verbatim as the `uProjection` uniform. In
the vertex shader, every `gl_Position = uProjection * vec4(aPos, 1.0)` then
has NaN in `gl_Position.z`. GPU clipping compares `z` against `-w` and `+w`;
NaN fails every ordered comparison, so every primitive is discarded. The
frame contains only the clear color — zero fragments from the triangle.

WebXR depth sensing on Meta Quest 3 reports `depthFar = Infinity`, three.js
propagates that value into `camera.far`, and `Matrix4.makePerspective`
produces NaN entries in the projection matrix. After the immersive session
ends and the user camera is used for normal rendering, the polluted matrix
renders a blank canvas.

The fix (PR #29120) adds a dedicated infinite-far code path in
`setProjectionFromUnion`, using the non-generalized infinite perspective
formula instead of the standard formula that divides by `near - far`.

## Expected Correct Output

A 400×300 frame on a dark-blue background (`0.1, 0.1, 0.3`) with a large
orange (`1.0, 0.5, 0.2`) triangle centered in the viewport, covering roughly
one third of the pixels.

## Actual Broken Output

A uniform dark-blue 400×300 frame. Not a single orange fragment is written.
No GL error, no shader warning — `glGetError()` returns `GL_NO_ERROR`.

## Difficulty Rating

3/5

A visually blank frame with no errors is a generic symptom — it could be a
missing draw call, wrong viewport, depth test failure, cleared back-buffer,
failed shader compile, culled geometry, or NaN. The root cause only becomes
apparent when the projection matrix uniform is inspected and specific cells
are recognized as NaN.

## Adversarial Principles

- **Silent numerical failure**: NaN is never an OpenGL error. Shader compile
  and link succeed, `glGetError` stays clean, the draw call executes.
- **Post-vertex clipping discard**: the vertex shader "runs to completion"
  for every vertex — the failure is downstream in fixed-function clipping,
  far from any user code to step through.
- **Plausibility of `Infinity`**: `camera.far = Infinity` is a legitimate
  request (glTF's infinite perspective), so the matrix construction looks
  defensible until you trace the algebra.

## How OpenGPA Helps

`get_draw_call(draw_id=0)` returns the uniform block for the draw call,
including `uProjection`. Cells `[2][2]` and `[3][2]` (column-major indices
10 and 14) are NaN, immediately localizing the bug to projection-matrix
construction. Without OpenGPA, the agent must add debug readbacks,
recompile, or mentally re-derive the perspective formulas.

## Source

- **URL**: https://github.com/mrdoob/three.js/issues/29098
- **Type**: issue
- **Date**: 2024-08-16
- **Commit SHA**: (n/a — see fix PR #29120)
- **Attribution**: Reported by @cabanier; fix by @RemusMar via PR #29120

## Tier

core

## API

opengl

## Framework

none

## Bug Signature

```yaml
type: nan_or_inf_in_uniform
spec:
  uniform_name: uProjection
  component_indices: [10, 14]
  expected_finite: true
```

## Upstream Snapshot
- **Repo**: https://github.com/mrdoob/three.js
- **SHA**: 4f067f0f4dc9e81f7fb3484962f2e973f71fab60
- **Relevant Files**:
  - src/renderers/webxr/WebXRManager.js  # base of fix PR #29120 (infinite-far projection for depth-sensing)
  - src/math/Matrix4.js
  - src/cameras/PerspectiveCamera.js

## Predicted OpenGPA Helpfulness

- **Verdict**: yes
- **Reasoning**: The root cause lives entirely in a uniform value that is
  invisible to the source code at the draw site. OpenGPA's captured uniform
  values make the NaN entries trivially inspectable, collapsing what is
  otherwise an open-ended blank-frame debugging hunt into a single query.

## Observed OpenGPA Helpfulness
- **Verdict**: ambiguous
- **Evidence**: validation skipped (--no-validate)
