# R7_REGRESSION_LOGARITHMICDEPTHBUFFER_ISSUES: InstancedMesh sprites clipped when logarithmicDepthBuffer is enabled (v181 regression)

## User Report
I have a three.js scene with many small sprites scattered across a large terrain using `InstancedMesh` objects, and I occasionally enable `logarithmicDepthBuffer` to get some good screenshots of the scene. Otherwise I mostly keep `logarithmicDepthBuffer` disabled as it causes significant performance issues.

Anyway, I recently upgraded from three.js v179 to v182, and I noticed that starting in v181, with `logarithmicDepthBuffer` enabled, my sprites get "cut" when viewed at an angle.

I can say with 100% certainty, that the bug is NOT present in v180.

Minimum reproducible example: https://jsfiddle.net/L602b3jh — alternate the `importmap` URLs between `three@0.180.0` and `three@0.181.0` to see the difference.

Did anything change regarding logarithmic depth, or depth in general, between v180 and v181 of three.js that may be causing this?

(Follow-up from another contributor): after some testing, reverting PR #32109 fixes the issue. Since the PR is not directly related to logarithmic depth buffer, it seems to have a side effect we are currently not aware of. A further check suggests that the `once()` treatment of `positionView` is no longer being reapplied in the fragment stage — and since `clipSpace` now drives `positionView.z`, that reapplication is necessary.

### Version
r181

## Expected Correct Output
With `logarithmicDepthBuffer: true` and an `InstancedMesh` of small sprite planes scattered across a large terrain, every instance renders fully at any camera angle, matching the v180 behavior.

## Actual Broken Output
Starting at v181, individual instanced sprite quads are sliced: a portion of each quad is clipped (discarded or depth-failed) along what looks like a view-dependent plane, so sprites appear "cut" when the camera is oblique. The visual cut moves with camera angle.

## Ground Truth
Root cause: PR #32109 ("TSL: Add active stack and improve 'node block' support") changed how TSL's node builder manages variable scoping between stages. Variables declared with `.once()` or equivalent cache-per-stage decorators are no longer being materialized into the fragment stage when they are first referenced inside a nested stack (the "fragmentation stage"). In particular, `positionView` is now computed via `clipSpace` for its `.z` component when `logarithmicDepthBuffer` is enabled — a computation that must be present in both vertex and fragment stages. After #32109, the fragment-stage reapplication of that `once`-scoped node is skipped, so the fragment shader ends up using a stale or incorrectly-scoped `positionView.z`, which in turn corrupts the logarithmic-depth `gl_FragDepth` write, producing the per-fragment clipping artifact seen on the instanced sprites.

Evidence from the upstream thread:

> "After some testing I can confirm reverting #32109 fixes the issue. Since the PR is not directly related to logarithmic depth buffer, it seems to have a side effect we are currently no[t] aware of."

> "I'm checking, it seems that the `once()` method of `positionView` is not being reapplied in the fragmentation stage of that code. Now that we're using `clipSpace` for `positionView.z`, this should be necessary."

> (PR #32109 description) "Variables declared outside the stack are being added to the main stack. This fixes the bug in question, and opens some windows for optimization as well."

See PR #32109 (mrdoob/three.js) for the behavioral change that introduced the regression; the fix will reinstate per-stage reapplication of `once()`-scoped nodes such as `positionView` when they are referenced from a nested stack during fragment code generation.

## Difficulty Rating
4/5

## Adversarial Principles
- cross_stage_scoping_bug
- shader_graph_compiler_regression
- logarithmic_depth_clipspace_dependency
- instanced_rendering_interaction

## How OpenGPA Helps
OpenGPA's per-draw-call shader source capture lets the agent diff the generated fragment shader between v180 and v181 for the same `InstancedMesh` material with `logarithmicDepthBuffer: true`, isolating the exact `positionView`/`gl_FragDepth` snippet that is missing or misplaced. Combined with uniform and varying dumps per instance, the agent can see that `vViewPosition.z` (or its TSL equivalent) is no longer being assigned in the fragment stage, which otherwise requires reading tens of TSL source files to reason about statically.

## Source
- **URL**: https://github.com/mrdoob/three.js/issues/32686
- **Type**: issue
- **Date**: 2026-04-20
- **Commit SHA**: (n/a)
- **Attribution**: Reported on mrdoob/three.js#32686; diagnosis hints from thread comments referencing PR #32109.

## Tier
snapshot

## API
opengl

## Framework
three.js

## Upstream Snapshot
- **Repo**: https://github.com/mrdoob/three.js
- **SHA**: 1dcf17505d4f443c8c3ce53bfd229deeac6a3583
- **Relevant Files**:
  - src/nodes/core/NodeBuilder.js
  - src/nodes/core/StackNode.js
  - src/nodes/core/VarNode.js
  - src/nodes/accessors/Position.js
  - src/nodes/display/ViewportDepthNode.js
  - src/renderers/common/nodes/NodeMaterial.js
  - examples/jsm/nodes/display/LogarithmicDepthBufferNode.js

## Bug Signature
```yaml
type: unexpected_state_in_draw
spec:
  draw_call_selector: "InstancedMesh with logarithmicDepthBuffer=true"
  expected:
    fragment_shader_contains: "positionView"
    fragment_shader_uses: "gl_FragDepth computed from view-space z"
  actual:
    fragment_shader_missing_reassignment_of: "positionView"
    gl_FragDepth_source: "vertex-stage-only value, not reapplied per-fragment"
  symptom: "per-instance quad clipping varying with camera angle"
```

## Predicted OpenGPA Helpfulness
- **Verdict**: yes
- **Reasoning**: The bug's visible symptom (angle-dependent clipping of instanced sprites) is far from its root cause (missing fragment-stage reapplication of a scoped TSL node). Without OpenGPA, the agent has to reason purely from the JS source across many node files to connect `logarithmicDepthBuffer` to `positionView.z` scoping. With OpenGPA, the agent can dump the two generated fragment shaders (v180-equivalent vs v181) for the same material, observe the missing `positionView`/`vViewPosition` reassignment, and localize the bug to the stack-scoping change in #32109 without having to mentally simulate the TSL compiler. This converts a multi-file static-analysis task into a direct shader-text diff.

## Observed OpenGPA Helpfulness
- **Verdict**: ambiguous
- **Evidence**: validation skipped (--no-validate)
