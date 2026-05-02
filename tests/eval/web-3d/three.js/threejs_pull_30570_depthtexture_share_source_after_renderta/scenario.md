# R19: depthTexture share source after RenderTarget.clone()

## User Report
Cloning a RenderTarget does not create a new Source for the new DepthTexture.

I've encountered this bug while using EffectComposer. If you pass a RenderTarget with depthTexture into EffectComposer, it will clone the depthTexture, but will not update its Source. This results in `GL_INVALID_OPERATION: Feedback loop formed between Framebuffer and active Texture` if you use passes that use depth texture.

Reproduction steps:

1. Create RenderTarget
2. Create DepthTexture for it
3. Clone RenderTarget
4. Compare sources of depth textures of new and old RenderTargets

```js
const fbo = new THREE.WebGLRenderTarget(640, 480);
fbo.depthBuffer = true;
fbo.depthTexture = new THREE.DepthTexture(640, 480);
console.log(fbo.depthTexture.source);
console.log(fbo.depthTexture.clone().source);
```

On Chrome the symptom is `GL_INVALID_OPERATION: Feedback loop formed between Framebuffer and active Texture`. On Firefox it is `drawArraysInstanced: Texture level 0 would be read by TEXTURE_2D unit 1, but written by framebuffer attachment DEPTH_ATTACHMENT, which would be illegal feedback`. Three.js r173, Chrome on Windows.

## Expected Correct Output
After the second pass the read-back center pixel should be a non-zero grey value derived from the depth texture written in pass A (clearDepth=0.5 → ~0x80), and `glGetError` should report `GL_NO_ERROR`.

## Actual Broken Output
`glGetError` after the second-pass draw reports `GL_INVALID_OPERATION` (0x0502) on drivers that enforce the feedback-loop rule, and the sampled color is undefined (commonly black 0,0,0). The framebuffer currently bound for writing (fboB) has the same GL depth texture object attached that texture unit 0 is sampling from.

## Ground Truth
The pre-r174 `RenderTarget.copy()` cloned the color texture's `Source` but left `depthTexture` handled only by `source.depthTexture.clone()`, and `DepthTexture.copy()` did not override `Texture.copy()` to create a new `Source`. `Texture.copy()` assigns `this.source = source.source`, so the cloned `DepthTexture` pointed at the same `Source` and therefore the same underlying GL texture object. When `EffectComposer` ping-ponged between its two render targets, both framebuffers had that single GL depth texture attached; any pass that also bound the depth texture to a sampler produced a feedback loop.

The fix in [PR #30570](https://github.com/mrdoob/three.js/pull/30570) (reverted) and [PR #30572](https://github.com/mrdoob/three.js/pull/30572) (merged) overrides `DepthTexture.copy()`:

```js
copy( source ) {
    super.copy( source );
    this.source = new Source( Object.assign( {}, source.image ) ); // see #30540
    this.compareFunction = source.compareFunction;
    return this;
}
```

and also clones the `Source` of each color texture inside `RenderTarget.copy()`:

> Makes sure render targets do not copy the source/image references of their textures but clone them. This makes sure the renderer detects the correct texture that should be attached to framebuffers.

See also linked issue [#22938](https://github.com/mrdoob/three.js/issues/22938) for the EffectComposer manifestation and [#20328](https://github.com/mrdoob/three.js/issues/20328) for the earlier `texture.image`-sharing bug that the Source class was originally introduced to fix.

## Difficulty Rating
3/5

## Adversarial Principles
- bind_point_collision
- cross_object_resource_sharing
- framebuffer_feedback_loop

## How OpenGPA Helps
`/api/v1/frames/current/overview` lists each FBO's attachments by GL texture ID, and each draw call's bound samplers by texture ID. A single query shows that fboB's `GL_DEPTH_ATTACHMENT` and texture unit 0 on the feedback draw call reference the same GL texture name, which is exactly the shared-Source condition — a detail the user would never see from inspecting three.js objects alone because the JS-side `DepthTexture` instances are distinct.

## Source
- **URL**: https://github.com/mrdoob/three.js/issues/30540
- **Type**: issue
- **Date**: 2025-02-27
- **Commit SHA**: (n/a)
- **Attribution**: Reported by @Usnul-style reporter on three.js (issue #30540); fix by @Mugen87 in PR #30572

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
  description: The draw call's bound sampler texture ID equals the currently bound framebuffer's depth attachment texture ID.
  sampler_unit: 0
  attachment: GL_DEPTH_ATTACHMENT
  expected_gl_error: GL_INVALID_OPERATION
```

## Upstream Snapshot
- **Repo**: https://github.com/mrdoob/three.js
- **SHA**: 2ab9aea318610820a3f5410c898eb56f8d6a9c29
- **Relevant Files**:
  - src/core/RenderTarget.js
  - src/textures/DepthTexture.js
  - src/textures/Texture.js
  - src/textures/Source.js
  - examples/jsm/postprocessing/EffectComposer.js

## Predicted OpenGPA Helpfulness
- **Verdict**: yes
- **Reasoning**: The bug reduces to "two framebuffer attachments and a sampler all reference the same GL texture name." This is a pure capture-layer observation — exactly what OpenGPA's per-draw snapshot of FBO attachments and bound texture units exposes. Without it the agent would need to trace JS-side object identity through three.js's Source/Texture wrapping, which is much harder.

## Observed OpenGPA Helpfulness
- **Verdict**: ambiguous
- **Evidence**: validation skipped (--no-validate)
