# R205: Incorrect use of depth texture attachments

## User Report
Depth-based effects (e.g. `SSAOEffect`) silently fail when added to certain pass chains in `postprocessing`.

Repro:
1. Add a `ClearPass` to the composer.
2. Add a `RenderPass` to the composer.
3. Add an `EffectPass` containing a depth-based effect such as `SSAOEffect` to the composer.
4. The effect renders without depth information — SSAO comes out flat / wrong.

The current depth texture system assumes that a depth texture can be assigned to a render target at any time. This assumption seems to be incorrect: render targets appear to be initialized once when first used, so a later `depthTexture` assignment never replaces the FBO's original basic depth buffer attachment.

Library versions:
- three: 0.120.0
- postprocessing: 6.17.1

## Expected Correct Output
Adding a depth-based effect like `SSAOEffect` after a `ClearPass` + `RenderPass` chain should produce a proper SSAO result — the effect should have access to scene depth regardless of which passes precede it.

## Actual Broken Output
The depth-based effect renders with no depth information. SSAO appears flat / featureless because the depth texture bound for sampling does not actually contain the scene's depth values.

## Ground Truth
The maintainer confirmed the diagnosis directly in the issue thread:

> The current depth texture system assumes that a depth texture can be assigned to a render target at any time. This assumption is incorrect as render targets are initialized once when they are used. Certain pass chains will cause the internal frame buffer to be initialized with a basic depth buffer attachment and the subsequent assignment of a depth texture won't have any effect.

A temporary fix shipped in `postprocessing@6.17.2` (see comment 1: "Added a temporary fix in `postprocessing@6.17.2`."), and the issue was finally resolved in [v6.39.0](https://github.com/pmndrs/postprocessing/releases/tag/v6.39.0) (see comment 6: "Should be fixed in v6.39.0."). Root cause: the `RenderPass`/`ClearPass` chain causes the underlying `WebGLRenderTarget`'s FBO to be allocated with a default depth `RenderBuffer` on first use; subsequently assigning `renderTarget.depthTexture` does not detach the renderbuffer or re-attach the depth texture to the existing FBO, so the depth texture stays empty.

## Fix
```yaml
fix_pr_url: https://github.com/pmndrs/postprocessing/releases/tag/v6.39.0
fix_sha: (auto-resolve from v6.39.0 release tag)
fix_parent_sha: (auto-resolve from v6.39.0 release tag)
bug_class: framework-internal
framework: postprocessing
framework_version: 6.17.1
files:
  - src/passes/ClearPass.js
  - src/passes/RenderPass.js
  - src/core/EffectComposer.js
change_summary: >
  Ensures depth texture attachments take effect even when a render target's
  FBO has already been initialized with a default depth renderbuffer.
  Pass chains that previously left the depth texture empty (ClearPass +
  RenderPass + depth-based EffectPass) now correctly propagate scene depth.
```

## Flywheel Cell
primary: framework-maintenance.web-3d.code-navigation
secondary:
  - framework-maintenance.web-3d.captured-literal-breadcrumb

## Difficulty Rating
4/5

## Adversarial Principles
- bug-lives-inside-framework-not-user-code
- diagnosis-requires-grep-not-pixel-comparison
- silent-failure-no-gl-error

## How OpenGPA Helps
`gpa trace` on the failing frame would show the FBO bound for the depth-based effect's sampling has its depth attachment as a `RENDERBUFFER` (not a `TEXTURE`), even though `renderTarget.depthTexture` is set on the JS side — the mismatch between the framework's intent and the actual FBO attachment is the smoking gun. A follow-up `/draw-calls/<id>/framebuffer` query reveals the depth attachment type, pointing the agent at FBO lifecycle code rather than the effect's shader.

## Source
- **URL**: https://github.com/pmndrs/postprocessing/issues/225
- **Type**: issue
- **Date**: 2021-01-15
- **Commit SHA**: (resolved in v6.39.0 release)
- **Attribution**: Reported and diagnosed by the postprocessing maintainer (@vanruesc); fix shipped in v6.17.2 (temporary) and v6.39.0 (final).

## Tier
maintainer-framing

## API
opengl

## Framework
postprocessing

## Bug Signature
```yaml
type: code_location
spec:
  expected_files:
    - src/passes/RenderPass.js
    - src/core/EffectComposer.js
  fix_commit: (auto-resolve from v6.39.0 release tag)
```

## Predicted OpenGPA Helpfulness
- **Verdict**: yes
- **Reasoning**: GPA's framebuffer-attachment introspection directly reveals that the depth attachment is a renderbuffer rather than the expected depth texture, redirecting the agent away from shader-level debugging and toward the render-target initialization lifecycle inside `postprocessing`'s pass classes.