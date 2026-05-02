# R4_MOTION_BLUR_AND_INSTANCEDMESH: Motion blur velocity MRT misses instance motion

## User Report
Motion Blur is a nice post-production effect. However, using instanced meshes, it appears that something is not working correctly. As soon as a matrix changes the position of an instance, it shows render issues.

Reproduction: see the shared fiddle (https://jsfiddle.net/z1Laon9y/). An `InstancedMesh` has its per-instance matrices animated every frame; with the motion-blur pass enabled, the rendered output shows streaks/artifacts around each instance rather than the smooth per-instance motion trail you would expect.

Version: three.js r182. Desktop Chrome on macOS.

A follow-up comment on the issue suggests:

> It seems `InstanceNode` needs a similar enhancement like `SkinningNode` in order to compute `positionPrevious` correctly. Meaning if there is a velocity MRT output, `InstanceNode` must keep track of the previous instance matrices (`previousInstanceMatrixNode`).

## Expected Correct Output
The velocity MRT attachment at the triangle's coverage should contain a non-zero 2D screen-space delta reflecting the instance's translation between the previous and current frame. For an animated instance whose world-space x shifted by 0.3 between frames with a static camera, the sampled velocity pixel should have `r ≈ 0.15` (half of the NDC delta, as encoded by the shader's `*0.5` remap).

## Actual Broken Output
The velocity MRT pixel under the instanced triangle reads `r=0.0000, g=0.0000`. The color attachment renders the instance at its current position correctly, but the velocity output contains no contribution from the instance's motion.

## Ground Truth
The vertex shader computes both the current clip-space position and the "previous" clip-space position from the same `a_instanceMatrix` attribute:

```
v_curClip  = u_viewProj     * a_instanceMatrix * vec4(a_pos, 1);
v_prevClip = u_prevViewProj * a_instanceMatrix * vec4(a_pos, 1);
```

With the camera held still (`u_viewProj == u_prevViewProj`), the two clip positions are algebraically identical, so the fragment shader's `cur - prev` is the zero vector regardless of whether the instance actually moved between frames. No previous-frame instance matrix is supplied — there is no `a_prevInstanceMatrix` attribute, no `u_prevInstanceMatrix` uniform, no buffer stashing last frame's per-instance transform.

This is exactly the upstream diagnosis from the issue thread:

> `InstanceNode` must keep track of the previous instance matrices (`previousInstanceMatrixNode`)

The parallel with `SkinningNode`/`positionPrevious` is the right one: for velocity-MRT correctness, anything that contributes a per-frame world-space transform (skinning, morph targets, per-instance matrix) has to have its previous-frame counterpart plumbed through to the vertex stage. Instancing in the node material system was wired up only for the current matrix, so motion blur post-processing sees zero screen-space velocity for the per-instance translation component and produces streaking or no blur at all where each instance has moved.

## Difficulty Rating
4/5

## Adversarial Principles
- missing_previous_frame_state_for_mrt
- shader_reuses_current_transform_for_previous
- motion_blur_velocity_plumbing

## How OpenGPA Helps
`get_draw_call` exposes the draw's full attribute and uniform binding set. The agent can enumerate everything the vertex stage reads — `a_pos`, the four slots of `a_instanceMatrix`, `u_viewProj`, `u_prevViewProj` — and observe that no `prev`-qualified per-instance source exists. Cross-referencing this with the vertex shader source (also available per draw) confirms the previous-frame position is computed by reusing the current instance matrix. A `get_pixel` on color attachment 1 at the instance's coverage region returns `(0, 0, *, *)`, corroborating that the velocity MRT carries no instance-motion signal.

## Source
- **URL**: https://github.com/mrdoob/three.js/issues/32585
- **Type**: issue
- **Date**: 2026-04-20
- **Commit SHA**: (n/a)
- **Attribution**: Reported upstream; diagnosis quoted from issue comment identifying `InstanceNode`/`previousInstanceMatrixNode` as the missing enhancement analogous to `SkinningNode`

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
  attachment: color_attachment_1
  region:
    x: 166
    y: 128
    w: 1
    h: 1
  expected:
    r_nonzero: true
  observed:
    r: 0.0
    g: 0.0
  rationale: >
    Velocity MRT attachment should encode a non-zero screen-space delta
    reflecting the per-instance translation between previous and current
    frame. With the shader reusing the current a_instanceMatrix for the
    previous-position computation and a static camera, velocity resolves
    to exactly zero regardless of instance motion.
```

## Upstream Snapshot
- **Repo**: https://github.com/mrdoob/three.js
- **SHA**: (auto-resolve from commit latest-on-issue-32585)
- **Relevant Files**:
  - src/nodes/accessors/InstanceNode.js
  - src/nodes/accessors/SkinningNode.js
  - src/nodes/accessors/VelocityNode.js
  - src/renderers/common/nodes/NodeBuilder.js
  - examples/jsm/tsl/display/MotionBlur.js

## Predicted OpenGPA Helpfulness
- **Verdict**: yes
- **Reasoning**: The bug is a missing input to the velocity pass, not a numerical oddity. It is fully diagnosable from per-draw state: the agent can enumerate vertex attributes and uniforms on the draw that writes color attachment 1, see that every transform-related binding is present in "current" form but none in "previous" form, and correlate with the vertex shader source to confirm the previous-position computation reuses the current instance matrix. A follow-up pixel probe on the velocity attachment confirms the zero-velocity signal. No need to interpret a rendered color image or diff across frames.

## Observed OpenGPA Helpfulness
- **Verdict**: ambiguous
- **Evidence**: validation skipped (--no-validate)
