# R6_WEBGL_BACKEND_INSTANCENODE_UBO_EXCEEDS_G: InstanceNode UBO exceeds GL_MAX_UNIFORM_BLOCK_SIZE when hardcoded 1000-matrix budget assumes 64KB

## User Report
### Description

`InstanceNode` uses a hardcoded threshold of 1000 instances to decide between UBO (`buffer()`) and vertex attributes for instance matrices:

https://github.com/mrdoob/three.js/blob/dev/src/nodes/accessors/InstanceNode.js#L153-L158

```js
// Both backends have ~64kb UBO limit; fallback to attributes above 1000 matrices.
if ( count <= 1000 ) {
    instanceMatrixNode = buffer( instanceMatrix.array, 'mat4', Math.max( count, 1 ) ).element( instanceIndex );
} else {
    // vertex attribute fallback
}
```

This assumes a ~64KB UBO limit, but **Chrome/ANGLE on macOS reports `GL_MAX_UNIFORM_BLOCK_SIZE = 16384` bytes** (the WebGL2 spec minimum). Any `InstancedMesh` with more than **256 instances** (256 × 64 bytes = 16,384) will silently fail to render on Chrome because the `NodeBuffer` UBO exceeds the device limit.

Safari and Firefox report 65,536 bytes, so the same code works fine there.

### Reproduction

```js
import { WebGPURenderer } from 'three/webgpu'

const renderer = new WebGPURenderer({ forceWebGL: true })

const mesh = new InstancedMesh(geometry, material, 300) // 300 × 64 = 19,200 bytes > 16,384
scene.add(mesh)
renderer.render(scene, camera)
```

**Chrome**: shader fails with `Size of uniform block NodeBuffer_XXXXX in VERTEX shader exceeds GL_MAX_UNIFORM_BLOCK_SIZE (16384)`. The mesh does not render.

**Safari / Firefox**: renders correctly (64KB UBO limit).

### Suggested fix

Query `GL_MAX_UNIFORM_BLOCK_SIZE` at init and compute the threshold dynamically instead of hardcoding 1000:

```js
const maxUBOSize = gl.getParameter(gl.MAX_UNIFORM_BLOCK_SIZE);
const maxInstancesInUBO = Math.floor(maxUBOSize / 64); // 64 bytes per mat4

if (count <= maxInstancesInUBO) {
    // UBO path
} else {
    // vertex attribute fallback
}
```

### Environment

- three.js version: r182
- Browser: Chrome 133 (ANGLE/Metal backend on macOS)
- OS: macOS 15.5
- Renderer: `WebGPURenderer({ forceWebGL: true })`

Issue I encounter while working on a client project / description written by Claude

## Expected Correct Output
A triangle (or a grid of instanced triangles) rendered against the dark
background clear color. The program links cleanly and `glDrawArrays` /
`glDrawElementsInstanced` produces visible fragments.

## Actual Broken Output
The framebuffer is filled entirely with the clear color — no triangle is
visible. `glLinkProgram` returns `GL_FALSE` with an info log complaining
that the uniform block size exceeds `GL_MAX_UNIFORM_BLOCK_SIZE`, and the
subsequent draw generates `GL_INVALID_OPERATION` because the bound program
is not linked.

## Ground Truth
A shader declares a `std140` uniform block containing a large `mat4` array
sized from a hardcoded budget (1000 matrices × 64 bytes ≈ 64KB). The code
never queries `GL_MAX_UNIFORM_BLOCK_SIZE`, so on any driver reporting less
than that budget (notably Chrome/ANGLE on macOS at 16384 bytes), the program
fails to link. The draw call then does nothing and the `InstancedMesh`
silently fails to render.

The three.js `InstanceNode._createInstanceMatrixNode` picked between a UBO
and a vertex-attribute fallback using a hardcoded threshold that assumed
a ~64KB UBO budget, without consulting the device limit:

> Both backends have ~64kb UBO limit; fallback to attributes above 1000 matrices.

In the original code:

```js
// WebGPU has a 64kb UBO limit, WebGL 2 ensures only 16KB; fallback to attributes if a certain count is exceeded
const limit = ( builder.renderer.backend.isWebGPUBackend === true ) ? 1000 : 250;
if ( count <= limit ) {
    instanceMatrixNode = buffer( instanceMatrix.array, 'mat4', Math.max( count, 1 ) ).element( instanceIndex );
} else {
    // vertex attribute fallback
}
```

The reporter observed on Chrome/ANGLE (macOS Metal backend):

> Chrome/ANGLE on macOS reports GL_MAX_UNIFORM_BLOCK_SIZE = 16384 bytes (the WebGL2 spec minimum). Any InstancedMesh with more than 256 instances (256 × 64 = 16,384) will silently fail to render.

The fix landed in PR #32949 ("WebGPURenderer: Improve checks for uniform
buffer limits"), which lowered the WebGL threshold to 250 (≈16KB) and keeps
1000 only on the WebGPU path. The robust fix is to query the device limit
at init and derive the threshold from it, as the reporter suggested.

The minimal repro ports the same *pattern* into core OpenGL 3.3: it queries
`GL_MAX_UNIFORM_BLOCK_SIZE`, then deliberately declares a `NodeBuffer` with
`(max/64)+32` mat4 entries to emulate the "hardcoded budget exceeds device
limit" mistake. Link fails and the clear color dominates the frame.

## Difficulty Rating
4/5

## Adversarial Principles
- silent-cross-platform-divergence
- hardcoded-platform-assumption
- limit-not-queried
- shader-link-failure-without-visible-error
- ubo-size-bounds

## How OpenGPA Helps
The user-visible symptom is only "the frame is empty." OpenGPA's draw-call
inspection surfaces two raw facts that pinpoint the cause immediately:
(1) the program bound for the draw has `GL_LINK_STATUS == GL_FALSE` with an
info log citing `GL_MAX_UNIFORM_BLOCK_SIZE`, and (2) the draw generated
`GL_INVALID_OPERATION`. Cross-referencing the bound uniform-block size
against `GL_MAX_UNIFORM_BLOCK_SIZE` makes the overflow explicit without the
agent having to guess which uniform is "too big."

## Source
- **URL**: https://github.com/mrdoob/three.js/issues/33009
- **Type**: issue
- **Date**: 2025-02-05
- **Commit SHA**: 1f2fea769315befd9bdb3f46574e2eeb92c5047a
- **Attribution**: Reported against three.js r182 (Chrome/ANGLE on macOS); fixed in PR #32949.

## Tier
core

## API
opengl

## Framework
none

## Upstream Snapshot
- **Repo**: https://github.com/mrdoob/three.js
- **SHA**: 1f2fea769315befd9bdb3f46574e2eeb92c5047a
- **Relevant Files**:
  - src/nodes/accessors/InstanceNode.js
  - src/nodes/accessors/BufferNode.js
  - src/renderers/webgl-fallback/nodes/GLSLNodeBuilder.js
  - src/renderers/webgpu/nodes/WGSLNodeBuilder.js
  - src/nodes/core/NodeBuilder.js
  - src/nodes/geometry/RangeNode.js

## Bug Signature
```yaml
type: framebuffer_dominant_color
spec:
  dominant_color_rgba: [0.1, 0.1, 0.12, 1.0]
  min_coverage: 0.98
  tolerance: 0.02
  note: >
    With the oversized NodeBuffer the vertex program fails to link, the draw
    call emits GL_INVALID_OPERATION, and no fragments are written. The
    framebuffer is therefore dominated by the clear color.
```

## Predicted OpenGPA Helpfulness
- **Verdict**: yes
- **Reasoning**: The bug is entirely about raw GL state that Tier 1 capture
  already records — program link status, program info log, active uniform
  block size, and the post-draw GL error. A coding agent without OpenGPA
  sees only "nothing rendered" and has to guess whether the mesh is off
  screen, culled, depth-tested away, or the program is invalid. OpenGPA
  points directly at the link-status/info-log pair, which states the UBO
  overflow verbatim, eliminating the guesswork that made the original bug
  cross-platform and silent.

## Observed OpenGPA Helpfulness
- **Verdict**: ambiguous
- **Evidence**: validation skipped (--no-validate)
