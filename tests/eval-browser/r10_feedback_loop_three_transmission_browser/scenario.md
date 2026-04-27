# R10 (browser): three.js MeshPhysicalMaterial transmission feedback loop

## User Report

Glass material renders broken every frame in my three.js scene since
upgrading to r182. The browser console fills with:

```
[.WebGL-0x...] GL_INVALID_OPERATION: glDrawElements:
  Feedback loop formed between Framebuffer and active Texture.
```

256+ such warnings per frame. The scene visibly stops compositing the
back-faces of any `MeshPhysicalMaterial({ transmission > 0,
side: DoubleSide })`. Repro is a single sphere with that material on a
`WebGLRenderer({ antialias: false })` — what I use because I render
through `EffectComposer`. Worked in r181, broken in r182+.

The reduced reproducer is roughly:

```js
const renderer = new THREE.WebGLRenderer({ antialias: false });
const glass = new THREE.MeshPhysicalMaterial({
  transmission: 1.0,
  roughness:    0.05,
  side:         THREE.DoubleSide,
});
scene.add(new THREE.Mesh(new THREE.SphereGeometry(1, 32, 32), glass));
renderer.render(scene, camera);
```

Reproduces on Linux/SwiftShader and on most Windows/Linux discrete-GPU
configs. macOS/ANGLE-Metal hides it because that backend exposes
`WEBGL_multisampled_render_to_texture`.

Version: three.js r182 — Chrome (Linux + SwiftShader + headless).

## Ground Truth

The transmission render target is constructed with
`samples = capabilities.samples`. When the canvas was created with
`antialias: false`, the default framebuffer reports `gl.SAMPLES === 0`,
so `capabilities.samples` is `0` and the transmission target is
allocated with `samples: 0` — i.e. no MSAA renderbuffer is sandwiched
between the texture and the framebuffer. The texture object itself is
attached as `COLOR_ATTACHMENT0`.

The back-side pass of `renderTransmissionPass()` then samples
`transmissionRenderTarget.texture` while that very texture is still the
bound DRAW framebuffer's color attachment — the textbook
framebuffer/texture feedback loop. The driver may drop the draw
silently and emits `GL_INVALID_OPERATION` per draw.

The original guard (PR #26177) avoided this by hardcoding
`samples: 4`. PR #32444 then "tidied" that to
`samples: capabilities.samples`, re-introducing the bug whenever
the canvas had `antialias: false` AND the
`WEBGL_multisampled_render_to_texture` extension was unavailable.

## Expected Correct Output

Every back-side transmission draw call sees a framebuffer whose color
attachment is *not* the same texture object that is bound to texture
unit 0 (`transmissionSamplerMap`). The render produces a coherent
shaded sphere; no GL warnings.

## Actual Broken Output

The bound `DRAW_FRAMEBUFFER`'s `COLOR_ATTACHMENT0` is the *same* GL
texture object (call it `transmissionTex`) that is also bound to
texture unit 0 with the active fragment program sampling from it. The
driver returns `GL_INVALID_OPERATION` and skips writing fragments. The
prior cleared contents of the FBO persist; the back-faces of the
sphere appear black or solid clear-color.

## Difficulty Rating

4/5

## Adversarial Principles

- bind-point collision (FBO color attachment vs. sampler unit)
- silent rendering failure (draw is dropped, prior contents persist)
- multi-PR regression (a fix's invariant is broken by a later refactor)
- platform-conditional reproduction (extension presence hides the bug)

## How OpenGPA Helps

Two queries, both made trivial by Tier 3 + the JS reflection scanner:

1. *"For the current draw call, list every bound texture object and
    every framebuffer attachment object."* — the same texture id appears
    in both lists, naming the offending object directly.
2. *"What JS-side property holds the value `0.875`
    (`material.transmission`)?"* — the trace lookup walks the registered
    roots (`scene`, `renderer`, `camera`, `app`) and returns
    `scene.children[0].material.transmission`. The agent can
    cross-reference that path with `glDrawElements` parameters and
    pinpoint the offending material instance without grepping the
    minified bundle.

Without OpenGPA the user sees only "back faces don't render" and a
scrolling wall of WebGL warnings.

## Source

- **URL**: https://github.com/mrdoob/three.js/issues/33060
- **Type**: issue
- **Date**: 2025-10-24
- **Commit SHA**: c2c5685879290d304c226a493061f6461021864c
- **Attribution**: Reported on three.js issue tracker; root cause cross-referenced with PR #32444 (regression) and PR #26177 (original fix).

## Tier

browser

## API

webgl

## Framework

three.js

## Bug Signature

```yaml
type: unexpected_state_in_draw
spec:
  rule: "no texture object bound to a sampler unit referenced by the active program may also be a color/depth/stencil attachment of the currently bound DRAW_FRAMEBUFFER"
  draw_call_index: any_back_side_transmission_pass
  offending_object_kind: texture
  appears_as:
    - sampler_binding: { unit: 0, uniform: "transmissionSamplerMap" }
    - framebuffer_attachment: { target: GL_DRAW_FRAMEBUFFER, attachment: GL_COLOR_ATTACHMENT0 }
  expected_gl_error: GL_INVALID_OPERATION
```

## Predicted OpenGPA Helpfulness

- **Verdict**: yes
- **Reasoning**: A bind-state collision visible at draw-call time. OpenGPA's per-draw inventory of texture-unit bindings and framebuffer attachments makes the feedback loop directly observable. The JS-side trace additionally maps the offending uniform value back to the originating `MeshPhysicalMaterial` instance.

## Fix

```yaml
fix_pr_url: https://github.com/mrdoob/three.js/pull/33063
fix_sha: 3ca54b0a022614b5b363bfa670ceb2ecef7a4574
fix_parent_sha: e61ab90bd7b03dd9956d170476966ca7d9f7af46
bug_class: framework-internal
files:
  - src/renderers/WebGLRenderer.js
change_summary: >
  Restores the unconditional MSAA invariant for the transmission render
  target: `renderTransmissionPass()` allocates the target with
  `samples: 4` again (rather than `capabilities.samples`), so that even
  when the canvas was created with `antialias: false` the back-side
  transmission pass cannot create a feedback loop between
  `transmissionSamplerMap` and the bound DRAW framebuffer's color
  attachment.
```

## Upstream Snapshot

- **Repo**: https://github.com/mrdoob/three.js
- **SHA**: c2c5685879290d304c226a493061f6461021864c
- **Relevant Files**:
  - src/renderers/WebGLRenderer.js
  - src/renderers/webgl/WebGLCapabilities.js
  - src/renderers/WebGLRenderTarget.js

## Browser Bundle

The pre-fix three.js ES-module bundle is vendored at
`framework/three.module.min.js` + `framework/three.core.min.js`,
copied verbatim from the upstream snapshot above. See
`framework/SOURCE.txt` for SHA + license attribution
(`framework/LICENSE.three.js` is the upstream MIT license).

## Tier-3 Link Plugin

This scenario imports the OpenGPA three.js link plugin
(`src/python/gpa/framework/threejs_link_plugin.js`, mounted by the
runner at `/_plugins/threejs-link.js`) via the `gpa-threejs-link`
importmap entry. The plugin wraps `renderer.render()`, pushes
`gl.pushDebugGroup` markers per Mesh/Light/Group around each node's
draws, and POSTs the flattened scene tree to
`/api/v1/frames/<id>/annotations`. After capture, agents can run

```
gpa scene-find name-contains:sphere --frame latest --json
gpa scene-find type:Mesh             --frame latest
```

to traverse the scene graph.

**Known gap (2026-04-27):** the WebGL extension's
`interceptor.js` does NOT yet record `gl.pushDebugGroup` /
`gl.popDebugGroup` calls into `NormalizedDrawCall.debug_groups`. Until
that is wired, `gpa scene-find` matches return correct nodes but
empty `draw_call_ids`. See
`docs/superpowers/specs/2026-04-27-bidirectional-narrow-queries-design.md`
section "Browser-eval smoke validation (2026-04-27)" for details.
