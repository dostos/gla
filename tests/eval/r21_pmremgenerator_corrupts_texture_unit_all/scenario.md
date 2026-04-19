# R21: PMREMGenerator corrupts texture-unit allocator, sampler2DShadow lands on RGBA16F

## User Report
### Description

When `scene.environment` is an equirectangular HDR texture and shadow maps are enabled, the **first** `renderer.render()` triggers `PMREMGenerator.fromEquirectangular()` inside `setProgram()`. PMREMGenerator renders RGBA16F cubemap faces using the **same renderer**, corrupting the shared texture-unit counter in `WebGLTextures`. Shadow map uniform pre-allocation then gets wrong unit offsets, and `sampler2DShadow` finds an RGBA16F texture on its unit:

```
GL_INVALID_OPERATION: glDrawElements: Texture bound to texture unit 0
with internal format GL_RGBA16F_EXT is not compatible with sampler type
GL_SAMPLER_2D_SHADOW_EXT
```

This bug fires on the **first frame only** — PMREMGenerator caches its result, so subsequent frames are clean.

### Browser / OS

- **Android Chrome 133 (Qualcomm Adreno 740) — reproduces consistently**
- Desktop Chrome (NVIDIA/AMD) — errors occur but are silently handled by lenient drivers

### Root cause analysis

The call chain during the first `renderer.render(scene, camera)`:

```
renderer.render(scene, camera)
  -> renderScene()
    -> setProgram(material) [per object]
      -> textures.resetTextureUnits()          // counter = 0
      -> environments.get(envTex, usePMREM=true)
        -> PMREMGenerator.fromEquirectangular(envTex)
          -> [internal renders of cubemap faces]
          -> each calls setProgram() -> resetTextureUnits()
          -> leaves RGBA16F textures bound on various units
          -> texture-unit counter left at value N
        <- returns PMREM cubemap (cached for future frames)
      -> allocateTextureUnit() returns N (corrupted, should be 0)
      -> ... continues binding uniforms with wrong unit offsets ...
    -> shadow map uniform pre-allocation
      -> allocateTextureUnit() returns N+M instead of correct value
      -> shadow DepthTexture bound to unit N+M
      -> unit 0 still has RGBA16F from PMREMGenerator
      -> sampler2DShadow on unit 0 hits the RGBA16F texture
      -> GL_INVALID_OPERATION
```

**Key details from Three.js source (r183):**

- `WebGLRenderer.js` line 2271: `textures.resetTextureUnits()` — resets counter to 0
- `WebGLRenderer.js` line 2277: `environments.get(envTexture, usePMREM=true)` — triggers PMREMGenerator
- `WebGLTextures.js`: `resetTextureUnits()` only resets the counter, not the actual GL texture bindings
- `WebGLRenderer.js` lines 2525-2533: Shadow map uniform pre-allocation uses `allocateTextureUnit()` which returns the corrupted counter value
- PMREMGenerator borrows the parent renderer and calls `renderer.render()` internally, which calls `setProgram()` -> `resetTextureUnits()`, corrupting the shared counter

### Why desktop may not show errors

- Desktop GPU drivers (NVIDIA, AMD) are more lenient about transient texture format mismatches.
- Mobile GPU drivers (Qualcomm Adreno, ARM Mali, Apple GPU) enforce strict GL spec compliance.

### Suggested fix

In `WebGLEnvironments.get()` (or in `setProgram()` around the `environments.get()` call), save and restore the texture-unit counter:

```javascript
const savedTextureUnit = textures.getCurrentTextureUnit();
const envMap = pmremGenerator.fromEquirectangular(texture);
textures.resetTextureUnits();
```

### Workaround

Do a single render **without shadows** before the first render with shadows + environment map. This triggers PMREMGenerator in isolation, so the PMREM result is cached before shadows are enabled.

### Reproduction steps

1. Create a scene with a `DirectionalLight` with `castShadow = true`
2. Set `scene.environment` to an equirectangular texture with `EquirectangularReflectionMapping` and `HalfFloatType`
3. Enable `renderer.shadowMap.enabled = true`
4. Call `renderer.render(scene, camera)` (the **first** call triggers PMREMGenerator)
5. Open on an **Android device** with Chrome — the GL error appears on the first frame only

### Version

r183 (0.183.1), Mobile, Chrome, Android.

## Expected Correct Output
First frame draws the lit, shadowed scene with no GL errors. The
`sampler2DShadow` uniform resolves to a depth texture and depth-compare
sampling produces a valid shadow factor.

## Actual Broken Output
First frame raises `GL_INVALID_OPERATION` on the draw call. On strict mobile
drivers (Adreno, Mali, Apple GPU) the shadow lookup is dropped and shadows
render incorrectly; on lenient desktop drivers (NVIDIA/AMD) the error is
silently swallowed and the visible output is mostly correct, masking the
underlying state corruption. Subsequent frames are clean because the PMREM
result is cached and the nested render no longer happens.

## Ground Truth
On the first `renderer.render()` call with both `scene.environment` (an
equirectangular HDR texture) and shadow maps enabled, Three.js's
`PMREMGenerator.fromEquirectangular()` runs *inside* `setProgram()`. The PMREM
pass borrows the parent renderer and issues nested `renderer.render()` calls,
which call `textures.resetTextureUnits()` on the **shared** texture-unit
allocator. When the outer render resumes, subsequent `allocateTextureUnit()`
calls return offsets that no longer match the actual GL bindings the PMREM
work left behind. The shadow map's `sampler2DShadow` uniform ends up pointing
at a unit that still has an `RGBA16F` PMREM cube-face texture bound on it.
The first draw call after the shadow uniforms are wired then fails with
`GL_INVALID_OPERATION: Texture bound to texture unit 0 with internal format
GL_RGBA16F_EXT is not compatible with sampler type GL_SAMPLER_2D_SHADOW_EXT`.

The reporter traced the call chain through Three.js r183 and the maintainer
confirmed the diagnosis. From the issue:

> PMREMGenerator borrows the parent renderer and calls `renderer.render()`
> internally, which calls `setProgram()` -> `resetTextureUnits()`,
> corrupting the shared counter

> `WebGLTextures`: `resetTextureUnits()` only resets the counter, not the
> actual GL texture bindings

The fix requires saving and restoring the texture-unit counter across the
nested render. Maintainer @Mugen87 pointed at the existing render-state
stack as the natural carrier:

> If wonder if we could simply request the current texture unit from
> `WebGLTextures` and put it in the current render state right at the
> beginning of the render. When finished, we use the value to restore the
> texture unit.

The reporter prototyped exactly this in comment 2 (the "v2" patch adds
`getTextureUnits()`/`setTextureUnits()` on `WebGLTextures` and
saves/restores around `renderStateStack.push/pop`), and the maintainer
greenlit a PR in comment 3.

## Difficulty Rating
4/5

## Adversarial Principles
- driver_lenience_mask: the bug is invisible on the desktop GPUs most devs
  test on; only strict mobile drivers surface the error.
- shared_mutable_state_across_nested_calls: an allocator counter is reset
  inside a nested call but the bindings it accounts for are not, leaving the
  outer caller with a stale view of GL state.
- error_message_points_at_the_victim_not_the_culprit: the GL error names the
  shadow draw, but the actual fault was committed earlier by an unrelated
  PMREM pass.
- first_frame_only: the symptom self-heals after one frame because the
  triggering work is cached, making the bug easy to dismiss as transient.

## How OpenGPA Helps
Querying the failing draw call's bound texture units reveals that the
uniform declared as `sampler2DShadow` resolves to a texture unit whose
currently bound texture has internal format `RGBA16F` rather than a depth
format. That single cross-reference (uniform sampler type vs. bound
texture's internal format on the assigned unit) is exactly what the GL
error message gestures at but does not surface in application code.

## Source
- **URL**: https://github.com/mrdoob/three.js/issues/33207
- **Type**: issue
- **Date**: 2026-04-19
- **Commit SHA**: (n/a)
- **Attribution**: Reported by @SSCare; diagnosis confirmed by @Mugen87

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
  draw_call_index: 0
  expectation: |
    For every active sampler uniform on the bound program, the texture
    bound on the uniform's assigned texture unit must have an internal
    format compatible with the sampler's GLSL type. Specifically: a
    sampler2DShadow uniform requires a texture with a depth internal
    format (e.g. GL_DEPTH_COMPONENT16/24/32F) and
    GL_TEXTURE_COMPARE_MODE = GL_COMPARE_REF_TO_TEXTURE.
  observed: |
    Uniform `uShadow` (GLSL type sampler2DShadow) is assigned texture
    unit 0; the texture bound on unit 0 is a 2D texture with internal
    format GL_RGBA16F. The draw raises GL_INVALID_OPERATION.
```

## Upstream Snapshot
- **Repo**: https://github.com/mrdoob/three.js
- **SHA**: 86795078cefe4fc2027066d73681fc71a1863931
- **Relevant Files**:
  - src/renderers/WebGLRenderer.js
  - src/renderers/webgl/WebGLTextures.js
  - src/renderers/webgl/WebGLRenderStates.js
  - src/renderers/webgl/WebGLEnvironments.js
  - src/extras/PMREMGenerator.js

## Predicted OpenGPA Helpfulness
- **Verdict**: yes
- **Reasoning**: The bug's root cause maps cleanly onto a single per-draw
  cross-reference: sampler-uniform GLSL type vs. bound-texture internal
  format on the uniform's assigned texture unit. OpenGPA already exposes
  per-draw uniform values and per-unit texture bindings through Tier 1
  capture, and an agent that asks "for each sampler uniform, what's the
  format of the texture on its assigned unit?" lands directly on the
  mismatch. The application-level error message ("GL_INVALID_OPERATION on
  draw") gives no hint about which uniform or which unit; OpenGPA's
  structured view does.

## Observed OpenGPA Helpfulness
- **Verdict**: ambiguous
- **Evidence**: validation skipped (--no-validate)
