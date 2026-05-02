# R1: WebGL backend: InstanceNode UBO exceeds GL_MAX_UNIFORM_BLOCK_SIZE on Chrome/ANGLE for 256+ instances

## User Report

`InstanceNode` uses a hardcoded threshold of 1000 instances to decide between UBO (`buffer()`) and vertex attributes for instance matrices. This assumes a ~64KB UBO limit, but **Chrome/ANGLE on macOS reports `GL_MAX_UNIFORM_BLOCK_SIZE = 16384` bytes** (the WebGL2 spec minimum). Any `InstancedMesh` with more than **256 instances** (256 × 64 bytes = 16,384) will silently fail to render on Chrome because the `NodeBuffer` UBO exceeds the device limit.

Safari and Firefox report 65,536 bytes, so the same code works fine there.

```js
import { WebGPURenderer } from 'three/webgpu'

const renderer = new WebGPURenderer({ forceWebGL: true })

const mesh = new InstancedMesh(geometry, material, 300) // 300 × 64 = 19,200 bytes > 16,384
scene.add(mesh)
renderer.render(scene, camera)
```

**Chrome**: shader fails with `Size of uniform block NodeBuffer_XXXXX in VERTEX shader exceeds GL_MAX_UNIFORM_BLOCK_SIZE (16384)`. The mesh does not render.

**Safari / Firefox**: renders correctly (64KB UBO limit).

- three.js version: r182
- Browser: Chrome 133 (ANGLE/Metal backend on macOS)
- OS: macOS 15.5
- Renderer: `WebGPURenderer({ forceWebGL: true })`

## Ground Truth

The renderer declares a uniform block (`InstanceBlock { mat4 matrices[N]; }`) sized against a hardcoded assumption (~64 KB worth of instances) instead of the driver-reported `GL_MAX_UNIFORM_BLOCK_SIZE`. On drivers whose actual limit is smaller, shader linking fails and the instanced draw silently renders nothing.

The upstream code hardcoded a 1000-matrix threshold, assuming every WebGL2 device exposes a ~64 KB UBO limit. Chrome/ANGLE on macOS reports only the spec minimum (16,384 bytes), so a UBO sized for the three.js threshold trivially overflows. The driver surfaces the failure only at link time with an info log message, but application code that ignores `GL_LINK_STATUS` will show only a missing mesh.

The correct approach is to query the device limit and derive the UBO/attribute cutoff dynamically:

```js
const maxUBOSize = gl.getParameter(gl.MAX_UNIFORM_BLOCK_SIZE);
const maxInstancesInUBO = Math.floor(maxUBOSize / 64); // 64 bytes per mat4

if (count <= maxInstancesInUBO) {
    // UBO path
} else {
    // vertex attribute fallback
}
```

## Expected Correct Output
A row of small orange triangles (8 instances) rendered over the dark-blue clear color. The center pixel should be approximately `(255, 76, 25)` where the triangle fan covers it.

## Actual Broken Output
Program link fails with a "Size of uniform block … exceeds GL_MAX_UNIFORM_BLOCK_SIZE" message; the subsequent `glUseProgram`/`glDrawArraysInstanced` is a no-op (GL_INVALID_OPERATION). The framebuffer remains the dark-blue clear color; the center pixel reads approximately `(0, 51, 102)`.

## Difficulty Rating
3/5

## Adversarial Principles
- silent-driver-limit-violation
- cross-browser-divergent-defaults
- hardcoded-capability-assumption
- link-stage-failure-masquerades-as-missing-geometry

## How OpenGPA Helps
An OpenGPA query for "why is my InstancedMesh not drawing on Chrome?" should surface the program link status and the driver infolog containing the `GL_MAX_UNIFORM_BLOCK_SIZE` diagnostic, pointing directly at the oversized UBO instead of the usual suspects (matrix uploads, frustum culling, attribute bindings).

## Source
- **URL**: https://github.com/mrdoob/three.js/issues/33009
- **Type**: issue
- **Date**: 2025-09-18
- **Commit SHA**: (n/a)
- **Attribution**: Reported by a three.js user (issue description authored via Claude); triaged against r182 source. Noted as already addressed on `dev` by PR #32949 in r183dev.

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
  region: full
  expected_dominant_rgb: [255, 76, 25]
  actual_dominant_rgb: [0, 51, 102]
  tolerance: 30
  rationale: "Instanced draw should cover visible area with orange triangles; link failure leaves clear color dominant."
```

## Upstream Snapshot
- **Repo**: https://github.com/mrdoob/three.js
- **SHA**: 1f2fea769315befd9bdb3f46574e2eeb92c5047a
- **Relevant Files**:
  - src/nodes/accessors/InstanceNode.js  # same issue as r6; pre-fix snapshot from r183-era dev branch
  - src/nodes/accessors/BufferNode.js
  - src/renderers/webgl-fallback/WebGLBackend.js

## Predicted OpenGPA Helpfulness
- **Verdict**: yes
- **Reasoning**: The failure mode is a link error whose text names the exact root cause (`exceeds GL_MAX_UNIFORM_BLOCK_SIZE`), but application code that ignores `GL_LINK_STATUS` or buries the infolog will show only a missing mesh. An OpenGPA query that inspects program link status, info log, and `GL_MAX_UNIFORM_BLOCK_SIZE` versus declared UBO size will deterministically identify the mismatch — far more directly than visual or geometry-level diagnostics.

## Observed OpenGPA Helpfulness
- **Verdict**: ambiguous
- **Evidence**: validation skipped (--no-validate)
