# R14: WebGPURenderer shadow-casting-light limit halved vs WebGLRenderer

## User Report
It seems r182 uses far more texture units to handle shadow casting lights than r181.

**Reproduction steps:** Add some shadow casting lights.

**Live example:**
- r181 → 15 lights on my gpu before reaching the limit: https://jsfiddle.net/drc3hvs7/
- r182 → 5 lights on my gpu before reaching the limit: https://jsfiddle.net/2hj3dgau/

You can change the `n` variable to change the number of lights added in the fiddle.

Original forum report: https://discourse.threejs.org/t/max-texture-units-in-threejs-r182/88721

A follow-up comment from another contributor notes: "I have debugged the code and removing the [block at `WebGLRenderer.js#L2524-L2546`] restores the texture limit. However, this code block was added to fix breakage on Android, see #32303. After a closer look, the texture uniform update at this point is incorrect since it results in duplicate texture units and texture uploads for each shadow casting light. They are updated here and in [line 2643]. One update should be sufficient so we must remove the map uniforms from the material uniform list."

A later comment reframes the issue toward `WebGPURenderer`: "The reason why `WebGPURenderer` supports less shadow casting lights is because it uses for each lights two textures. One for the depth comparison (the depth texture), another one for the shadow color. The latter one is not supported in `WebGLRenderer` and the reason for the discrepancy… When the developer does not make use of colored shadows, it would be better to free the texture units so they can be used for other things (e.g. more shadow casting lights)."

## Expected Correct Output
A scene with ~15 shadow-casting lights (or however many the device's `GL_MAX_TEXTURE_IMAGE_UNITS` / WebGPU `maxSampledTexturesPerShaderStage` budget allows) should render with all lights contributing shadows, matching r181's behaviour and `WebGLRenderer`'s behaviour.

## Actual Broken Output
Only ~5 of the 15 shadow-casting lights produce shadows before the sampled-texture budget is exhausted. Excess lights either fail silently or produce a shader-binding validation error. The effective shadow-light cap in `WebGPURenderer` is halved relative to `WebGLRenderer` at the same revision, and halved again relative to r181's `WebGPURenderer`.

## Ground Truth
`WebGPURenderer`'s shadow pipeline (`ShadowNode.js`) allocates **two** sampled textures per shadow-casting light — one depth texture for the standard depth-compare shadow test, and one additional color texture that carries the "colored shadow" tint sampled in `ShadowNode.js#L538`:

> The reason why `WebGPURenderer` supports less shadow casting lights is because it uses for each lights two textures. One for the depth comparison (the depth texture), another one for the shadow color. The latter one is not supported in `WebGLRenderer` and the reason for the discrepancy.

Because every shadow light unconditionally consumes two bind-point slots, the number of shadow lights that fit in the fragment stage's sampled-texture budget is halved. The maintainer confirms the root cause and proposes making colored shadows optional:

> If you simplify [the `shadowOutput` line] to `const shadowOutput = mix( 1, shadowNode, shadowIntensity ).toVar();` you have the same limits as `WebGLRenderer`. So I think colored shadows should be optional.

Fixed via PR #32596, which introduces `renderer.shadowMap.color` (default `false`). When disabled, `ShadowNode` skips the color-texture allocation and the per-light sampled-texture cost drops from 2 to 1, restoring parity with `WebGLRenderer`'s shadow-light budget.

This is a distinct issue from the `WebGLRenderer` r181→r182 regression also discussed in the thread (duplicate `map` uniform update in `WebGLRenderer.js#L2524-2546` vs `L2643`); that concern is tracked separately and is not what PR #32596 fixes.

## Fix
```yaml
fix_pr_url: https://github.com/mrdoob/three.js/pull/32596
fix_sha: b103c0e4aeb7a457244d80b634fef69a1941fb64
fix_parent_sha: b103c0e4aeb7a457244d80b634fef69a1941fb64
bug_class: framework-internal
files:
  - src/nodes/lighting/ShadowNode.js
  - src/renderers/common/ShadowMap.js
change_summary: >
  Adds a `shadowMap.color` flag (default `false`) to `WebGPURenderer`. When
  disabled, `ShadowNode` skips the per-light colored-shadow texture
  allocation so each shadow-casting light consumes one sampled-texture
  bind point instead of two. This restores parity with `WebGLRenderer`'s
  shadow-light limit; developers who want tinted shadows can opt in.
```

## Upstream Snapshot
- **Repo**: https://github.com/mrdoob/three.js
- **SHA**: b103c0e4aeb7a457244d80b634fef69a1941fb64
- **Relevant Files**:
  - src/nodes/lighting/ShadowNode.js
  - src/renderers/common/ShadowMap.js
  - src/renderers/webgpu/WebGPURenderer.js
  - src/renderers/webgl-fallback/WebGLBackend.js
  - examples/webgpu_shadowmap.html

## Difficulty Rating
4/5

## Adversarial Principles
- bind-point budget exhaustion
- framework-level per-light resource multiplication
- backend parity regression (WebGPU vs WebGL)

## How OpenGPA Helps
A single-frame draw-call dump would show, for the scene-final pass, the set of sampled textures bound per shadow-casting light. An agent comparing WebGL and WebGPU captures of the same scene would immediately see **2× as many shadow-map-shaped texture bindings** on WebGPU — one depth, one color — per light. OpenGPA's texture-binding view surfaces that duplication directly, pointing at `ShadowNode`'s colored-shadow path without having to read the full shader-node graph.

## Source
- **URL**: https://github.com/mrdoob/three.js/issues/32588
- **Type**: issue
- **Date**: 2025-11-23
- **Commit SHA**: (n/a — tracked via PR #32596)
- **Attribution**: Reported by @Mugen87 / three.js community; diagnosis by @Mugen87; fix by @sunag

## Tier
snapshot

## API
opengl

## Framework
three.js

## Bug Signature
```yaml
type: unexpected_state_in_draw
spec:
  draw_selector: scene_final_pass
  state: bound_sampled_textures
  observation: per_shadow_light_texture_count == 2
  expected: per_shadow_light_texture_count == 1
```

## Predicted OpenGPA Helpfulness
- **Verdict**: yes
- **Reasoning**: The bug is fundamentally a texture-binding accounting issue. OpenGPA's per-draw-call texture-unit view exposes which samplers are bound during the scene pass, and a diff against the WebGLRenderer capture (or against r181 WebGPURenderer) immediately surfaces the doubled per-light shadow-texture count. Without OpenGPA, the agent would need to read the entire shader-node pipeline to infer the same conclusion.

## Observed OpenGPA Helpfulness
- **Verdict**: ambiguous
- **Evidence**: validation skipped (--no-validate)
