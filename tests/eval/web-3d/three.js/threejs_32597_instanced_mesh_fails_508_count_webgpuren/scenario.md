# R3: Instanced mesh silently fails when UBO exceeds MAX_UNIFORM_BLOCK_SIZE

## User Report
I recently released my new website and found a pretty quaint bug. My
InstancedMesh centerpiece "ring of rings" didn't show up at all on my iPhone.
After some extensive testing in the simulator here's what I've determined.

If an instanced mesh exceeds an instance count of 507 then it does not render.
No errors appear in the terminal and everything else renders correctly.

- Easily repeatable on iOS 16.2 (my guess is it affects <=16.X)
- Fixed on iOS 17.5 (my guess is fixed in >=17.X)
- Lowered the number of vertices in the instanced-mesh root geo and it had no
  impact. 508 still was the hard cutoff for when an instancedmesh would no
  longer render.
- This occurs with the WebGPURenderer being pushed into the WebGL2 fallback.

Reproduction:
```js
const geometry = new THREE.SphereGeometry(5, 12, 8);
// Not visible iOS <=16.2 (silent failure)
let iMesh508 = new THREE.InstancedMesh(geometry, new THREE.MeshBasicMaterial({color:0xff0000}), 508);
scene.add(iMesh508);
// Is visible iOS <=16.2
let iMesh507 = new THREE.InstancedMesh(geometry, new THREE.MeshBasicMaterial({color:0x0000ff}), 507);
scene.add(iMesh507);
```

Version: three.js r182. Device: iPhone 11 Pro Max simulator on iOS 16.2. No
errors in Safari's console when inspected.

## Expected Correct Output
A 64×32 grid of small red triangles covering the 256×256 viewport — one per
instance of the instanced draw call. Center pixel should sample a red
triangle.

## Actual Broken Output
On drivers whose `GL_MAX_UNIFORM_BLOCK_SIZE` is below the requested
128 KB (e.g. Mesa llvmpipe at 64 KB, WebKit WebGL2 at 16 KB), the
framebuffer is entirely black. No `glGetError` code is set; the shader
compiles and links; the draw call executes. The geometry simply does
not appear.

## Ground Truth
The scenario declares `layout(std140) uniform Instances { mat4 M[2048]; }`
and backs it with a 131 072-byte UBO. The OpenGL 4.x spec only guarantees
`MAX_UNIFORM_BLOCK_SIZE >= 16384` bytes, and WebGL 2 inherits that
guarantee. When the backing buffer binding exceeds the implementation's
limit, `glBindBufferBase` / draw-time validation fails silently on many
drivers — no GL error is generated for out-of-range UBO bindings in
several vendor implementations, and the shader simply reads undefined
(often zero) matrix data, producing degenerate `gl_Position` values that
clip every triangle.

The three.js maintainer traced this to the same root cause in
`InstanceNode`:

> `InstanceNode` makes the assumption that a device supports 64KB UBO
> size for both WebGPU and WebGL 2 which is not correct.
>
> The _minimum guaranteed_ UBO block size in WebGL 2 is only 16KB … So I
> suspect the issue is we allocate a too large UBO which fails on older
> iOS device. If a matrix takes 64 bytes, `count` should be 250 when
> using WebGL 2 if we want to be on the safe side.

The reporter confirmed `gl.getParameter(gl.MAX_UNIFORM_BLOCK_SIZE)`
returned exactly `16384` on the iOS 16.2 simulator, and a corrected
`InstanceNode` that queries the runtime limit before choosing the UBO
path resolved the issue:

> Also very happy to report your fix does work here … Can use
> instancedMeshes with counts in the thousands and no problems now.

The buggy assumption lives at
`src/nodes/accessors/InstanceNode.js:303-309` at commit
`69a97bfb1145b591dd9fe60170e8e8a32fb5a64e`.

## Difficulty Rating
4/5

## Adversarial Principles
- silent_failure_no_gl_error
- implementation_dependent_limit
- std140_block_size_vs_device_cap
- threshold_dependent_repro

## How OpenGPA Helps
OpenGPA captures `glGetIntegerv(GL_MAX_UNIFORM_BLOCK_SIZE)` at context
creation and the size of every UBO bound for a draw call. An agent can
query the UBO-bindings view for the failing draw, compare the bound
buffer size against the context's advertised limit, and directly surface
the size overrun that no `glGetError` reports. Without OpenGPA, the
caller sees a clean `GL_NO_ERROR` and an empty framebuffer with no
mechanical signal pointing at the UBO.

## Source
- **URL**: https://github.com/mrdoob/three.js/issues/32597
- **Type**: issue
- **Date**: 2025-12-21
- **Commit SHA**: 69a97bfb1145b591dd9fe60170e8e8a32fb5a64e
- **Attribution**: Reported by @Bug-Reaper; diagnosed by @Mugen87

## Upstream Snapshot
- **Repo**: https://github.com/mrdoob/three.js
- **SHA**: 69a97bfb1145b591dd9fe60170e8e8a32fb5a64e
- **Relevant Files**:
  - src/nodes/accessors/InstanceNode.js
  - src/renderers/common/Renderer.js
  - src/renderers/webgl-fallback/WebGLBackend.js

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
  region: [32, 32, 224, 224]
  expected_dominant_rgb: [230, 51, 51]
  actual_dominant_rgb: [0, 0, 0]
  tolerance: 40
```

## Predicted OpenGPA Helpfulness
- **Verdict**: yes
- **Reasoning**: The bug is a quantitative mismatch between a captured
  GL integer (`MAX_UNIFORM_BLOCK_SIZE`) and a captured buffer size
  (UBO bound to the draw). Both are raw facts OpenGPA already exposes,
  and neither is visible through the GL error mechanism, debuggers'
  default warning channels, or the rendered image alone — the hallmark
  "silent failure" category OpenGPA is designed for.

## Observed OpenGPA Helpfulness
- **Verdict**: ambiguous
- **Evidence**: validation skipped (--no-validate)
