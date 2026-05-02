# R202: WebGL2 device with `stencil: false` breaks depth scene grab

## User Report
When the PlayCanvas WebGL2 graphics device is created with `stencil: false` and post effects are enabled, depth scene grab stops working — framebuffers don't match during `WebglGraphicsDevice.copyRenderTarget`.

Reproduced on Edge, Chrome, and Firefox.

Steps to reproduce:
1. Load the [Post Effects](https://playcanvas.github.io/#/graphics/post-effects) example.
2. Add the line `stencil: false` to `const gfxOptions` at line 28.
3. Open the dev console.
4. Switch to WebGL2 as the active device.
5. The example breaks and the console shows warnings like:
   `[.WebGL-0x...] GL_INVALID_OPERATION: Depth/stencil buffer format combination not allowed for blit.`

This is also reproducible against the [Ground Fog](https://playcanvas.github.io/#/graphics/ground-fog) example on Firefox without enabling post effects — the depth debug view comes out fully white and Firefox warns:
`WebGL warning: blitFramebuffer: Depth buffer formats must match if selected.`

## Expected Correct Output
Depth scene grab works the same regardless of whether the device was constructed with `stencil: true` or `stencil: false`. Post-effect examples render correctly under WebGL2 with no `GL_INVALID_OPERATION` console spam, and the ground-fog depth debug view shows scene depth (not a flat white image).

## Actual Broken Output
Under WebGL2 + `stencil: false`, every depth scene grab triggers a `GL_INVALID_OPERATION: Depth/stencil buffer format combination not allowed for blit.` (Chromium) or `blitFramebuffer: Depth buffer formats must match if selected.` (Firefox). The depth target ends up unwritten, so depth-dependent passes (post effects, ground fog) render incorrectly — Firefox shows a fully white depth debug view.

## Ground Truth
The forum thread linked from the issue (`https://forum.playcanvas.com/t/depth-issues-when-enabling-a-post-process-effect/33024/20`) and the issue body itself (`https://github.com/playcanvas/engine/issues/5664`) localize the failure to `WebglGraphicsDevice.copyRenderTarget`: the engine `blitFramebuffer`s between two render targets whose depth/stencil format combination does not match when the device was created with `stencil: false`. Per the GLES3 / WebGL2 spec, `glBlitFramebuffer` requires that source and destination depth (and stencil, if selected) formats match exactly — a `DEPTH_COMPONENT*` source cannot be blitted into a `DEPTH24_STENCIL8` destination (or vice versa), which is precisely the format pairing produced when the device-level depth/stencil buffer drops the stencil component but the scene-grab target keeps the combined `DEPTH_STENCIL` attachment (or the inverse).

> `WebGL2 Graphics device creation with stencil: false breaks depth scene grab` — issue title.
> `framebuffers don't match when doing WebglGraphicsDevice.copyRenderTarget` — issue body.
> `GL_INVALID_OPERATION: Depth/stencil buffer format combination not allowed for blit.` — Chromium console.
> `blitFramebuffer: Depth buffer formats must match if selected.` — Firefox console.

The fix must reconcile the depth/stencil format chosen for the scene-grab target with the device's stencil setting (either propagate `stencil: false` into the grab target so both sides are `DEPTH_COMPONENT*`, or fall back to a non-blit copy path when formats differ).

## Fix
```yaml
fix_pr_url: (unresolved — see https://github.com/playcanvas/engine/issues/5664)
fix_sha: (auto-resolve from issue #5664)
fix_parent_sha: (auto-resolve from issue #5664)
bug_class: legacy
framework: playcanvas
framework_version: "1.65"
files: []
change_summary: >
  Fix PR not resolvable from the issue thread alone; scenario retained as
  a legacy bug-pattern reference. The bug lives in PlayCanvas WebGL2
  framebuffer-format handling: copyRenderTarget calls blitFramebuffer
  between depth attachments whose formats disagree when the device was
  created with stencil: false.
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
- spec-violation-only-visible-via-driver-error-string

## How OpenGPA Helps
A `gpa trace` capture of the failing frame surfaces the exact `glBlitFramebuffer` call that emits `GL_INVALID_OPERATION`, including the source and destination FBO attachment formats — the mismatch (e.g. `DEPTH_COMPONENT24` vs `DEPTH24_STENCIL8`) is visible directly in the captured framebuffer-attachment metadata. Querying `/frames/current/draw_calls/<id>/framebuffer` for both the source and destination targets lets the agent pinpoint which render-target construction site picked the wrong depth format, which then leads `grep` to the offending PlayCanvas source file without needing to repro the bug interactively.

## Source
- **URL**: https://github.com/playcanvas/engine/issues/5664
- **Type**: issue
- **Date**: 2023-09-21
- **Commit SHA**: (unresolved)
- **Attribution**: Reported on github.com/playcanvas/engine; diagnostic context on the PlayCanvas forum thread linked from the issue.

## Tier
maintainer-framing

## API
webgl

## Framework
playcanvas

## Bug Signature
```yaml
type: code_location
spec:
  expected_files: []
  fix_commit: (unresolved)
```

## Predicted OpenGPA Helpfulness
- **Verdict**: yes
- **Reasoning**: The failure is a driver-side `GL_INVALID_OPERATION` whose root cause is a framebuffer-attachment format mismatch — exactly the kind of low-level state OpenGPA captures verbatim per draw/blit call. Without GPA, the agent has only a console string and must reason about which of many render targets disagree; with GPA, the format pair is directly readable from the captured FBO state.