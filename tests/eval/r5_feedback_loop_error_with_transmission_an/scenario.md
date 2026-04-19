# R5_FEEDBACK_LOOP_ERROR_WITH_TRANSMISSION_AN: Transmission RT feedback loop when `samples == 0`

## User Report
### Description

`GL_INVALID_OPERATION: Feedback loop formed between Framebuffer and active Texture` occurs every frame when all of the following conditions are met:

1. `WebGLRenderer` created with `antialias: false`
2. A `MeshPhysicalMaterial` with `transmission > 0` and `side: DoubleSide`
3. `WEBGL_multisampled_render_to_texture` extension is unavailable

The error floods the console (256+ per frame), degrades performance, and breaks antialiasing. Rendering still produces partial output but draw calls involving the transmission texture are silently dropped by the browser.

**Introduced in:** r182 by PR #32444
**Last confirmed in:** r183
**Works in:** r181 and earlier

### Expected Behavior

No GL errors. The glass sphere renders as a transparent refractive object with correct antialiasing, same as r181.

### Actual Behavior

Every frame produces 256+ `GL_INVALID_OPERATION` errors:

```
[.WebGL-0x...] GL_INVALID_OPERATION: glDrawElements: Feedback loop formed between Framebuffer and active Texture.
[Violation] 'requestAnimationFrame' handler took <N>ms
WebGL: too many errors, no more errors will be reported to the console for this context.
```

### Root Cause

PR #32444 changed the transmission render target in `renderTransmissionPass()` from `samples: 4` (hardcoded) to `samples: capabilities.samples` (dynamic). With `antialias: false`, `gl.getParameter(gl.SAMPLES)` returns `0`, so the transmission RT is created with `samples: 0`.

With `samples: 0`, no MSAA renderbuffer is allocated. The transmission texture is attached directly as `COLOR_ATTACHMENT0` of the framebuffer:

```
samples >= 1:  Framebuffer → Renderbuffer (MSAA) → blitFramebuffer → Texture (safe)
samples == 0:  Framebuffer → Texture (direct attachment, same object read + written)
```

The feedback loop triggers in the back-face rendering block (`WebGLRenderer.js` lines 2016-2042, r183):

```js
if (extensions.has('WEBGL_multisampled_render_to_texture') === false) {
    for (let i = 0, l = opaqueObjects.length; i < l; i++) {
        const material = opaqueObjects[i].material;
        if (material.side === DoubleSide) {
            material.side = BackSide;
            renderObject(opaqueObjects[i], ...);  // shader samples from transmissionRenderTarget.texture
            material.side = DoubleSide;            // which IS the bound framebuffer's COLOR_ATTACHMENT0
        }
    }
}
```

During `renderObject()`, the shader reads from `transmissionRenderTarget.texture` (the transmission map uniform) while the same texture is simultaneously the bound framebuffer's `COLOR_ATTACHMENT0`.

### Why This Is Common in Practice

- **`antialias: false`** is the standard configuration when using `EffectComposer` (canvas MSAA is redundant since the composer has its own MSAA render targets)
- **`side: DoubleSide`** is common on glass/lens materials in GLTF models (`GLTFLoader` sets it from the GLTF `doubleSided: true` property)
- **Extension unavailability** varies by platform, making the bug appear intermittently across devices

### Suggested Fix

Ensure the transmission RT always has at least 1 sample so a renderbuffer is allocated:

```js
// In WebGLRenderer.js, renderTransmissionPass():
const transmissionSamples = Math.max(4, capabilities.samples);

currentRenderState.state.transmissionRenderTarget[camera.id] = new WebGLRenderTarget(1, 1, {
    generateMipmaps: true,
    type: /* ... */,
    minFilter: LinearMipmapLinearFilter,
    samples: transmissionSamples,  // was: capabilities.samples
    // ...
});
```

Alternatively, expose `transmissionRenderTarget.samples` as a configurable renderer property.

### Workaround

We use a monkey-patch on `WebGLRenderTarget.prototype.setSize()` that detects transmission RTs by their unique property signature and forces `samples: 4`:

```js
import { WebGLRenderTarget, LinearMipmapLinearFilter } from 'three';

const originalSetSize = WebGLRenderTarget.prototype.setSize;
WebGLRenderTarget.prototype.setSize = function (width, height, depth) {
  if (
    this.texture?.generateMipmaps === true &&
    this.texture.minFilter === LinearMipmapLinearFilter &&
    this.resolveDepthBuffer === false &&
    this.resolveStencilBuffer === false &&
    this.samples === 0
  ) {
    this.samples = 4;
  }
  return originalSetSize.call(this, width, height, depth);
};
```

### Reproduction steps

1. Create a `WebGLRenderer` with `antialias: false` (the standard configuration when using `EffectComposer`, since the composer provides its own MSAA render targets)
2. Add any mesh with a `MeshPhysicalMaterial` that has `transmission > 0` and `side: DoubleSide` to the scene (e.g., a glass sphere, or any GLTF model with a double-sided transmissive material)
3. Set up an `EffectComposer` with a `RenderPass` and `OutputPass`
4. Start the render loop

The error appears on the very first frame and repeats every frame thereafter.

**Platform note:** On macOS Chrome (ANGLE/Metal backend), the `WEBGL_multisampled_render_to_texture` extension is available. When present, Three.js skips the back-face rendering block in `renderTransmissionPass()` entirely, hiding the bug. The bug reproduces natively on platforms where the extension is unavailable (many mobile devices, some Linux/Windows GPU drivers). To reproduce on macOS Chrome, the extension must be blocked before renderer creation.

### Code

```js
import {
  WebGLRenderer, Scene, PerspectiveCamera, DoubleSide,
  MeshPhysicalMaterial, SphereGeometry, Mesh,
} from 'three';
import { EffectComposer } from 'three/examples/jsm/postprocessing/EffectComposer.js';
import { RenderPass } from 'three/examples/jsm/postprocessing/RenderPass.js';
import { OutputPass } from 'three/examples/jsm/postprocessing/OutputPass.js';

const renderer = new WebGLRenderer({ antialias: false });
renderer.setSize(800, 600);
document.body.appendChild(renderer.domElement);

const scene = new Scene();
const camera = new PerspectiveCamera(45, 800 / 600, 0.1, 100);
camera.position.z = 3;

const glass = new MeshPhysicalMaterial({
  transmission: 1.0,
  roughness: 0.05,
  ior: 1.45,
  thickness: 0.5,
  side: DoubleSide,
});
scene.add(new Mesh(new SphereGeometry(1, 32, 32), glass));

const composer = new EffectComposer(renderer);
composer.renderTarget1.samples = 8;
composer.renderTarget2.samples = 8;
composer.addPass(new RenderPass(scene, camera));
composer.addPass(new OutputPass());

renderer.setAnimationLoop(() => composer.render());
```

### Version

r182

### Device

Desktop

### Browser

Chrome

### OS

MacOS

## Expected Correct Output
A refracted glass sphere rendered to the transmission RT without GL
errors, with the back-face pass reading from an MSAA-resolved copy of
the transmission target (as in r181 and earlier, which hardcoded
`samples: 4`).

## Actual Broken Output
Every frame emits hundreds of `GL_INVALID_OPERATION: Feedback loop
formed between Framebuffer and active Texture`. Draw calls in the
back-face pass are silently dropped by the driver; the resulting
frame shows partial/missing transmissive geometry and lost
antialiasing.

## Ground Truth
A transmissive DoubleSide material's back-face pass samples from the
transmission render target's texture while that same texture is
attached as `COLOR_ATTACHMENT0` of the currently bound framebuffer.
When the renderer is created with `antialias: false` and
`WEBGL_multisampled_render_to_texture` is unavailable, three.js r182
builds the transmission RT with `samples: capabilities.samples`, which
evaluates to `0`, so no MSAA renderbuffer is allocated and the texture
is attached directly — producing a GPU read/write feedback loop on
every frame.

The regression was introduced in r182 by PR #32444, which parameterised
the transmission RT's sample count:

> PR #32444 changed the transmission render target in
> `renderTransmissionPass()` from `samples: 4` (hardcoded) to
> `samples: capabilities.samples` (dynamic). With `antialias: false`,
> `gl.getParameter(gl.SAMPLES)` returns `0`, so the transmission RT is
> created with `samples: 0`.

The `samples == 0` path attaches the texture directly instead of
resolving from a renderbuffer:

> ```
> samples >= 1:  Framebuffer → Renderbuffer (MSAA) → blitFramebuffer → Texture (safe)
> samples == 0:  Framebuffer → Texture (direct attachment, same object read + written)
> ```

The feedback loop fires inside the DoubleSide back-face block that
runs when the MSAA render-to-texture extension is missing:

> During `renderObject()`, the shader reads from
> `transmissionRenderTarget.texture` (the transmission map uniform)
> while the same texture is simultaneously the bound framebuffer's
> `COLOR_ATTACHMENT0`.

A maintainer confirmed the root fix in comment 1:

> The force of MSAA has hidden a feedback loop that is present in the
> current transmission implementation. […] How about we update the
> code to: `samples: Math.max( 4, capabilities.samples );`

## Difficulty Rating
4/5

## Adversarial Principles
- Platform-dependent extension gating hides the bug on the primary
  dev platform (macOS Chrome has `WEBGL_multisampled_render_to_texture`)
- Regression is triggered by a configuration combination
  (`antialias: false` + `DoubleSide` + transmission) rather than a
  single flag
- Rendering still produces a frame — the failure is a flood of GL
  errors plus silent draw-drops, not a crash or blank screen
- MSAA previously acted as an accidental guardrail; removing it
  exposed a pre-existing invariant violation

## How OpenGPA Helps
At the offending `glDrawArrays`, OpenGPA can inspect live GL state and
observe that the texture bound to sampler unit 0 is also the current
framebuffer's `COLOR_ATTACHMENT0` — the exact invariant the spec
forbids. A single state query at draw time pinpoints the feedback
loop without needing a full MSAA/no-MSAA behavioural diff.

## Source
- **URL**: https://github.com/mrdoob/three.js/issues/33060
- **Type**: issue
- **Date**: 2026-04-18
- **Commit SHA**: (n/a)
- **Attribution**: Reported upstream on mrdoob/three.js#33060; regression introduced by PR #32444

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
  condition: sampled_texture_is_current_color_attachment
  sampler_unit: 0
  framebuffer_attachment: GL_COLOR_ATTACHMENT0
  draw_call: glDrawArrays
  must_be_equal:
    - bound_texture(GL_TEXTURE0, GL_TEXTURE_2D)
    - framebuffer_attachment_object(GL_DRAW_FRAMEBUFFER, GL_COLOR_ATTACHMENT0)
```

## Upstream Snapshot
- **Repo**: https://github.com/mrdoob/three.js
- **SHA**: e61ab90bd7b03dd9956d170476966ca7d9f7af46
- **Relevant Files**:
  - src/renderers/WebGLRenderer.js  # base of fix PR #33063 (transmission RT samples)
  - src/renderers/webgl/WebGLCapabilities.js
  - src/renderers/WebGLRenderTarget.js

## Predicted OpenGPA Helpfulness
- **Verdict**: yes
- **Reasoning**: The failure mode is a single-draw state invariant
  (sampler texture name == current color attachment name). OpenGPA's
  draw-time state inspection directly surfaces this equality, whereas
  purely visual diffs are fragile because the bug manifests as
  dropped draws plus an error flood rather than a deterministic
  pixel change.

## Observed OpenGPA Helpfulness
- **Verdict**: ambiguous
- **Evidence**: validation skipped (--no-validate)
