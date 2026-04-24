# R17: Incorrect clipping with global clipping planes and nested render calls (Reflector)

## User Report
Global [clipping planes](https://threejs.org/docs/index.html#api/en/renderers/WebGLRenderer.clippingPlanes) can be defined on the renderer. While these are specified in World Space, they are converted to camera space in the renderer. Nested render calls can cause these to be recomputed for a different camera, and their original state is never restored. This results in the remainder of the render call using incorrect clipping planes.

### Reproduction steps

1. Setup global clipping planes on the renderer
2. Add an object to the scene that results in a nested render call (e.g. Reflector)
3. Render the scene and observe the clipping behaving inconsistently

### Code

```js
renderer.clippingPlanes = [ new THREE.Plane( new THREE.Vector3( 1, 0, 0 ), 0 ) ];
const reflector = new Reflector( ... );
scene.add( reflector );
```

Moving the camera around shows that the clipping isn't consistent between the sphere and its reflection. This happens because the main sphere is rendered _after_ the Reflector (and thus after the nested render call that messes up the global clipping plane uniforms). Once the Reflector is out of view it won't be rendered, and the sphere is consistently clipped along the defined clipping plane.

Version: r164. Chrome / Firefox on Linux.

## Expected Correct Output
Both outer-pass quads (drawn on the positive-X half of the screen) appear with the same clipping behavior — the x ≥ 0 world clip plane holds for every outer draw call.

## Actual Broken Output
The first outer quad renders correctly against the world-space plane. The second outer quad — the one issued after the simulated nested render — is clipped by the nested pass's transformed plane (y ≥ 0) instead, so the bottom-right quad gets fully clipped out while the top-right remains.

## Ground Truth
The `WebGLRenderer`'s clipping uniforms are computed per-camera: `Clipping.setState()` transforms each world-space plane by the current camera's view matrix and uploads the result to the shared clipping UBO / uniform. A nested render call (e.g. `Reflector` rendering its virtual camera into a RenderTarget) invokes `setState` again with the nested camera, overwriting those uniforms. When control returns to the outer render, the outer camera's clipping uniforms are never re-uploaded, so the rest of the outer draws use the nested camera's transform.

The maintainer's fix (PR #28113) tracks the active camera per render-state on `WebGLRenderStates`, so the renderer can redo the camera-dependent restore (clipping, viewport) after a nested render returns:

> This PR makes sure the camera is tracked in the render state so it's possible to perform camera related restore operation after a nested render call. Clipping uniforms are now correctly restored and also the viewport configuration can be restored in the renderer now.

See PR #28113 and merge commit 645ff11.

## Fix
```yaml
fix_pr_url: https://github.com/mrdoob/three.js/pull/28113
fix_sha: 645ff11b6e08ea0f845940a4ba13491c40198af2
fix_parent_sha: 7690b5090676101c5c3818eeadbf92f8fa7c60e1
bug_class: framework-internal
files:
  - src/renderers/WebGLRenderer.js
  - src/renderers/webgl/WebGLRenderStates.js
  - examples/jsm/objects/Reflector.js
  - examples/jsm/objects/ReflectorForSSRPass.js
  - examples/jsm/objects/Refractor.js
  - examples/jsm/objects/Water.js
change_summary: >
  Track the active camera on each WebGLRenderState so the renderer can re-apply
  camera-dependent state (clipping uniforms, viewport) after a nested render
  call returns. The viewport-save/restore workarounds that lived in Reflector,
  Refractor, Water, and ReflectorForSSRPass are removed, since the renderer
  now handles the restore centrally.
```

## Difficulty Rating
4/5

## Adversarial Principles
- state-leak-across-subrender
- camera-dependent-uniform-not-restored
- symptom-delayed-from-cause (outer draw issued long after the offending nested pass)

## How OpenGPA Helps
Comparing the uniform block / `uClipPlane` value used by outer draw A vs outer draw B in the per-draw-call snapshot immediately shows the plane vector changed between two draws that the agent believed shared one "global" clip plane. Querying `uniform_value_across_draws` for the clip uniform pinpoints the nested-pass boundary as the source of the mutation.

## Source
- **URL**: https://github.com/mrdoob/three.js/issues/28111
- **Type**: issue
- **Date**: 2024-04-11
- **Commit SHA**: (n/a)
- **Attribution**: Reported by @mrxz

## Tier
core

## API
opengl

## Framework
none

## Upstream Snapshot
- **Repo**: https://github.com/mrdoob/three.js
- **SHA**: 7690b5090676101c5c3818eeadbf92f8fa7c60e1
- **Relevant Files**:
  - src/renderers/WebGLRenderer.js
  - src/renderers/webgl/WebGLRenderStates.js
  - src/renderers/webgl/WebGLClipping.js
  - examples/jsm/objects/Reflector.js
  - examples/jsm/objects/Refractor.js
  - examples/jsm/objects/Water.js

## Bug Signature
```yaml
type: unexpected_state_in_draw
spec:
  uniform: uClipPlane
  draw_call_index: 1
  expected_value: [1.0, 0.0, 0.0, 0.0]
  actual_value: [0.0, 1.0, 0.0, 0.0]
  note: >
    Outer-pass draw B is expected to use the same world-space clip plane as
    draw A, but the uniform was mutated by an intervening nested render and
    never restored.
```

## Predicted OpenGPA Helpfulness
- **Verdict**: yes
- **Reasoning**: The bug is a silent mutation of a shader uniform between two outer-pass draw calls. Per-draw uniform snapshots expose the divergence directly; a diff of uniform state between draw N and draw N+1 reveals which value changed and, paired with the draw-call call-site, points at the nested render boundary. This is squarely in Tier-1 OpenGPA's sweet spot — raw state per draw, no heuristics needed.

## Observed OpenGPA Helpfulness
- **Verdict**: ambiguous
- **Evidence**: validation skipped (--no-validate)
