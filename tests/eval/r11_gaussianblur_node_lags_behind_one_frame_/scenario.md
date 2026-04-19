# R11: GaussianBlur node lags behind one frame when used with Reflector

## User Report
### Description

When using the GaussianBlur Node to blur the texture of a reflector (for example to simulate roughness), the blur causes the texture to be one frame behind. This is especially visible with fast and/or user-controlled movement.

### Reproduction steps

1. Create Reflector
2. Pass Reflector to GaussianBlur
3. Pass result of this to outputNode of Material of geometry that shows the reflection

### Code

```js
import { gaussianBlur } from 'three/addons/tsl/display/GaussianBlurNode.js';
import { vec3, vec4, output, reflector } from 'three/tsl';
import {
  Scene, PerspectiveCamera, WebGPURenderer,
  CircleGeometry, PlaneGeometry, Mesh,
  MeshBasicNodeMaterial, MeshPhongNodeMaterial,
  DoubleSide, Object3D, Vector3
} from 'three/webgpu';

// ... scene with a reflective ground plane and a rim ...

const groundReflector = reflector({ resolutionScale: 1, generateMipmaps: true, bounces: false, samples: 4 });
const blurDirect = gaussianBlur(groundReflector, 1, 1).mul(0.4);
const planeMaterial = new MeshPhongNodeMaterial({ colorNode: vec3(1.0) });
planeMaterial.outputNode = blurDirect; // groundReflector

// Animation: camera oscillates each tick
window.setInterval(() => {
  frame++;
  camera.position.x = Math.sin(frame/2) * 7;
  renderer.render(scene, camera);
}, 1000);
```

### Live example

https://codepen.io/NoxDawnsong/pen/zxBMzvm

### Version

r182, Chrome on Linux desktop.

## Expected Correct Output
On each frame, the displayed blurred reflection should correspond to the current camera position. The draw that samples the reflector's color attachment should be preceded, in the same frame, by the draw(s) that write to that attachment.

## Actual Broken Output
On each frame, the displayed blurred reflection corresponds to the previous frame's camera position. On frame 0 specifically, the blur samples an uninitialized / cleared reflector target and the final composite is flat (no scene content), because the sampling draw runs before the producing draw on the same frame.

## Ground Truth
A post-process node (GaussianBlur) samples the render target of a producer node (Reflector) in the same frame, but the post-process's update callback runs before the producer's update callback. The blur therefore reads the texture contents from the previous frame — producing a one-frame lag that is visible under camera/user motion.

The reporter's own investigation pinpoints an ordering bug between the two nodes' update callbacks:

> After putting some logs into the `onBeforeRender` of the reflector and `updateBefore` of the GaussianBlur, i confirmed my suspicion that these are called in the wrong order. The GaussianBlur renders first, thus processing outdated data.

They also verified the ordering from the node graph side:

> The sequence can also be followed through the `Inspector`.

And confirmed that manually invoking the reflector's update before `render()` is not sufficient to fix it:

> Unfortunately, just putting `groundReflector._reflectorBaseNode.updateBefore(renderer, scene, camera)` before the render-call does not work there.

The root cause is scheduling inside the node pipeline: `GaussianBlurNode.updateBefore` is dispatched ahead of `ReflectorBaseNode.updateBefore` within the same frame, so the blur's input texture contains the previous frame's reflector output (or, on frame 0, the cleared/uninitialized contents of the render target).

## Difficulty Rating
3/5

## Adversarial Principles
- cross-pass-ordering
- stale-texture-read
- post-process-producer-consumer-cycle

## How OpenGPA Helps
An agent can query the draw call list for the final frame, find the blur-sampling draw, inspect which texture is bound to its sampler unit, and then ask "which draw call in this frame last wrote to that texture?" When the answer is "none" (or "an earlier frame's write"), the ordering bug is self-evident — no per-frame diff required.

## Source
- **URL**: https://github.com/mrdoob/three.js/issues/32985
- **Type**: issue
- **Date**: 2026-04-19
- **Commit SHA**: (n/a)
- **Attribution**: Reported by three.js user on issue #32985

## Tier
core

## API
opengl

## Framework
none

## Bug Signature
```yaml
type: unexpected_state_in_draw
spec:
  description: "Draw call that samples the reflector's color attachment precedes, within the same frame, the draw call that writes to that attachment. The sampled texture is in an unexpected state (not written this frame) at the moment of sampling."
  sampling_program_fragment: "texture(src, uv + vec2(x,y)/256.0)"
  sampled_texture_role: "reflector_color_attachment"
  expected_producer_before_consumer: true
  observed_producer_before_consumer: false
```

## Predicted OpenGPA Helpfulness
- **Verdict**: yes
- **Reasoning**: Tier 1 capture records the per-frame draw call list, the FBO bound to each draw, and the textures bound to each sampler. That is exactly the information needed to answer "does draw call B's sampled texture have a producing write earlier in this same frame?" The reporter already diagnosed the bug from `onBeforeRender` / `updateBefore` log ordering; OpenGPA exposes the equivalent ordering at the GL layer without needing framework instrumentation.

## Upstream Snapshot
- **Repo**: https://github.com/mrdoob/three.js
- **SHA**: (auto-resolve from commit 32985-head)
- **Relevant Files**:
  - src/renderers/common/Renderer.js
  - src/nodes/display/GaussianBlurNode.js
  - src/nodes/accessors/ReflectorNode.js
  - examples/jsm/objects/Reflector.js

## Observed OpenGPA Helpfulness
- **Verdict**: ambiguous
- **Evidence**: validation skipped (--no-validate)
