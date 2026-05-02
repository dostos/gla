# R28: Crash when combining HDR scene.background with volumetric lighting (WebGPU)

## User Report
**No idea why this happens**, but if I add an hdr background map to the
`webgpu_volume_lighting` example, my browser crashes. I tried setting the
background to a color and it works fine, but with an hdr it crashes.

Reproduction steps:
1. Use the code from https://threejs.org/examples/?q=volu#webgpu_volume_lighting
2. Add an hdr background
3. Crash

```js
import * as THREE from "three";
import { HDRLoader } from "three/examples/jsm/Addons.js";

export async function addHDR(url, scene) {
    const loader = new HDRLoader();
    const envMap = await loader.loadAsync(url);
    envMap.mapping = THREE.EquirectangularReflectionMapping;
    scene.environment = envMap;
    scene.background = envMap;
}
```

Call `addHDR(...)` after setting up the volumetric scene and the tab will
crash. Version r182, Chrome on Linux. The WebGL backend seems to be fine.

A follower reported the following WebGPU validation warning:

> Attachment state of [RenderPipeline "renderPipeline_Background.material_22"]
> is not compatible with [RenderPassEncoder (unlabeled)].
> [RenderPassEncoder (unlabeled)] expects an attachment state of
> { colorTargets: [0={format:TextureFormat::RGBA16Float}], sampleCount: 1 }.
> [RenderPipeline "renderPipeline_Background.material_22"] has an attachment
> state of { colorTargets: [0={format:TextureFormat::RGBA16Float}],
> depthStencilFormat: TextureFormat::Depth24Plus, sampleCount: 1 }.

## Expected Correct Output
The volumetric-lighting scene renders with the HDR environment visible as the
sky background, matching the WebGL backend's behavior.

## Actual Broken Output
Under the WebGPU backend the tab crashes the moment the background pipeline
is first used. Before the crash, the browser emits a WebGPU validation error
indicating that the background render pipeline advertises a depth-stencil
attachment while the render pass that tries to use it has only a color
attachment.

## Ground Truth
The three.js WebGPU renderer builds the background material's render pipeline
with a depth-stencil format (`Depth24Plus`) baked into its attachment state,
but the render pass used to draw the background into the volumetric
lighting's intermediate `RGBA16Float` target has no depth attachment. WebGPU
requires pipeline and pass attachment states to match exactly, so the draw
call is rejected and the context is lost.

The upstream validation message is explicit:

> [RenderPassEncoder (unlabeled)] expects an attachment state of
> { colorTargets: [0={format:TextureFormat::RGBA16Float}], sampleCount: 1 }.
> [RenderPipeline "renderPipeline_Background.material_22"] has an attachment
> state of { colorTargets: [0={format:TextureFormat::RGBA16Float}],
> depthStencilFormat: TextureFormat::Depth24Plus, sampleCount: 1 }.

The mismatch only surfaces when `scene.background` is an equirectangular HDR
texture, because that path instantiates a dedicated background pass that
draws into the volumetric effect's color-only target; a plain color
background takes a different code path that shares the main pass's
attachments. The WebGL backend tolerates this because GL framebuffer
completeness rules are more permissive and do not compare against a
pre-baked pipeline attachment record.

## Difficulty Rating
4/5

## Adversarial Principles
- backend-divergent-behavior
- validation-error-distant-from-symptom
- cross-pass-state-leak

## How OpenGPA Helps
OpenGPA's per-draw framebuffer attachment inventory and pipeline/pass state
dumps let the agent diff what each draw call's bound FBO actually contains
against what the corresponding shader pipeline was compiled to expect.
Querying `/api/v1/frames/current/draw_calls/<id>` for the first background
draw would surface the missing depth attachment immediately, and comparing
to the main scene pass (which does carry depth) would localize the
divergence.

## Source
- **URL**: https://github.com/mrdoob/three.js/issues/32706
- **Type**: issue
- **Date**: 2025-11-14
- **Commit SHA**: (n/a)
- **Attribution**: Reported by the issue author on mrdoob/three.js#32706; WebGPU validation message quoted by a follow-up commenter in the same thread.

## Tier
snapshot

## API
webgpu

## Framework
three.js

## Bug Signature
```yaml
type: unexpected_state_in_draw
spec:
  draw_call_selector: background_pass_first_draw
  expected_attachments:
    color: [RGBA16Float]
    depth_stencil: Depth24Plus
  actual_attachments:
    color: [RGBA16Float]
    depth_stencil: none
```

## Upstream Snapshot
- **Repo**: https://github.com/mrdoob/three.js
- **SHA**: (auto-resolve from PR #32706)
- **Relevant Files**:
  - src/renderers/webgpu/WebGPUBackend.js
  - src/renderers/common/Background.js
  - src/renderers/common/RenderPipeline.js
  - src/renderers/common/Pipelines.js
  - examples/webgpu_volume_lighting.html
  - src/renderers/webgpu/utils/WebGPUPipelineUtils.js

## Predicted OpenGPA Helpfulness
- **Verdict**: ambiguous
- **Reasoning**: OpenGPA's current Tier-1 capture is GL/Vulkan-oriented; WebGPU capture and cross-backend pipeline/pass inventory are not yet first-class. The scenario is a strong motivator for a WebGPU backend that records per-draw attachment state, but an agent using today's OpenGPA against the WebGL-backed variant would not see the bug at all (WebGL is fine). Helpfulness is contingent on landing a WebGPU capture backend that records `RenderPipelineDescriptor.depthStencil` alongside the active `RenderPassDescriptor` attachment list.

## Observed OpenGPA Helpfulness
- **Verdict**: ambiguous
- **Evidence**: validation skipped (--no-validate)
