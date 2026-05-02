# R204: PixiJS filters demo freezes on iOS 18.0–18.1 after upgrade to 8.16+

## User Report
On PixiJS 8.16.0, 8.17.0, and 8.17.1 the official filters example
(https://pixijs.io/filters/examples/) is completely frozen on iOS 18.0
and 18.1 — the canvas paints once but never animates. The same demo
works fine on iOS 17, on iOS 18.2, and on every desktop browser.

Reproduction:
1. Pick any device (real hardware or iOS simulator) running iOS
   between 18.0 and 18.1.x. Safari and WKWebView both repro.
2. Load https://pixijs.io/filters/examples/ on PixiJS >= 8.16.0.
3. Observe that the filters example never animates — it paints a
   single frame and freezes there. Other PixiJS demos that don't use
   filters keep animating.

The reporter bisected this against the iOS simulator and against
PixiJS releases. PixiJS 8.15.x on iOS 18.0–18.1 works fine; 8.16.0
breaks. iOS 17 and iOS 18.2 work on all PixiJS versions.

The reporter's hypothesis (they admit they're "in a bit beyond [their]
depth"): 8.16.0 introduced a new code path that calls a helper which
sets `TEXTURE_MAX_LEVEL = 0` on every texture, including single-mip
textures. They believe this lights up an ANGLE/Metal bug in
`FramebufferMtl::syncState` (rewritten for the Apple Vision Pro / WebXR
launch) where Metal texture views with `levelCount = 1` end up on a
buggy code path and cause FBO attachment confusion — textures appear
swapped, and depending on call order the renderer either freezes or
crashes. They note that the GL default `MAX_LEVEL = 1000` does not
trigger the bug, only the explicit `0`. They are shipping a one-line
guard in production via `pnpm patch` and it resolves the freeze for
their users.

## Expected Correct Output
The filters example animates continuously on iOS 18.0–18.1, the same
way it does on every other browser and on iOS 17 / 18.2.

## Actual Broken Output
The filters example paints a single still frame and then freezes.
No further animation, no console errors, no obvious crash — the GL
command stream just stops producing visible updates. On other iOS 18.0
PixiJS apps that exercise different filter call orders the symptom
varies between freeze and outright crash.

## Ground Truth
The reporter has done the diagnosis and provided a one-file diff. From
the issue body:

> 8.16.0 introduced `_applyMipRange()` which sets `TEXTURE_MAX_LEVEL=0`
> on single-mip textures. This unfortunately triggers a bug in iOS
> 18.0–18.1's webkit: it seems that the Metal driver sometimes confuses
> which texture is attached to which FBO, causing textures to appear
> swapped, or otherwise fail in strange (but deterministic) ways,
> including "freezing" (see Filters example) or crashing depending on
> the specific order of gl calls.

> The PR that introduced the change already guards
> `_allocateEmpty2DMipChain` with `mipLevelCount > 1` — it seems to me
> like the same guard should apply to `_applyMipRange`.

The regression originated in pixijs/pixijs PR #11801 ("feat: Implement
mip level rendering support in the rendering system"). The fix is to
add a `source.mipLevelCount > 1` guard around the `_applyMipRange`
call in `src/rendering/renderers/gl/texture/GlTextureSystem.ts` (the
TS source that compiles to `GlTextureSystem.mjs` in the diff). The
reporter's production patch is reproduced verbatim in the issue body.

## Fix
```yaml
fix_pr_url: https://github.com/pixijs/pixijs/issues/11984
fix_sha: (auto-resolve from issue #11984)
fix_parent_sha: (auto-resolve from issue #11984)
bug_class: legacy
framework: pixijs
framework_version: 8.16.0
files: []
change_summary: >
  Fix PR not yet merged upstream as of issue filing — reporter has
  diagnosed the bug, identified the regression in PR #11801, and is
  shipping a `pnpm patch` in production that wraps the
  `_applyMipRange` call in `GlTextureSystem` with a
  `source.mipLevelCount > 1` guard. Scenario retained as a legacy
  bug-pattern reference; the regressing PR (#11801) and the proposed
  one-file diff are documented in the issue thread.
```

## Flywheel Cell
primary: framework-maintenance.web-3d.code-navigation
secondary:
  - framework-maintenance.web-3d.captured-literal-breadcrumb
  - framework-maintenance.web-3d.driver-bug-workaround

## Difficulty Rating
4/5

## Adversarial Principles
- bug-lives-inside-framework-not-user-code
- diagnosis-requires-cross-referencing-driver-behavior-with-framework-source
- symptom-is-platform-conditional-freeze-not-deterministic-render-error
- regressing-pr-is-known-but-fix-pr-is-not-yet-merged

## How OpenGPA Helps
A `gpa trace` capture taken on the broken iOS 18.0 build would show
the `glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MAX_LEVEL, 0)` call
landing on every single-mip texture upload — that captured literal
`0` is the breadcrumb that points the agent at `_applyMipRange` in
`GlTextureSystem`. A second trace from PixiJS 8.15.x (or with the
guard applied) would show the same uploads with no `MAX_LEVEL=0`
call, isolating the regression to that one parameter call. The
`/draws` and `/state` endpoints surface this without the agent needing
device-side Safari tooling.

## Source
- **URL**: https://github.com/pixijs/pixijs/issues/11984
- **Type**: issue
- **Date**: 2026-04-27
- **Commit SHA**: 6e59c6fd0fb031f661f4d7db99dd44f45f5e4ef1 (regressing blob referenced by reporter)
- **Attribution**: Reported and diagnosed by the issue author after iOS-version + PixiJS-version bisection; regressing change attributed to PR #11801 by @GoodBoyDigital.

## Tier
maintainer-framing

## API
opengl

## Framework
pixijs

## Bug Signature
```yaml
type: code_location
spec:
  expected_files:
    - src/rendering/renderers/gl/texture/GlTextureSystem.ts
  fix_commit: (auto-resolve from issue #11984)
  regressing_pr: 11801
  regressing_call: _applyMipRange
  captured_literal_breadcrumb:
    gl_call: glTexParameteri
    pname: GL_TEXTURE_MAX_LEVEL
    value: 0
```

## Predicted OpenGPA Helpfulness
- **Verdict**: yes
- **Reasoning**: The root cause manifests as a specific captured GL
  literal (`TEXTURE_MAX_LEVEL = 0`) emitted on every single-mip texture
  upload. OpenGPA's trace surface exposes that literal directly; a
  text-only agent reading the PixiJS source can grep for the only call
  site that emits `TEXTURE_MAX_LEVEL` (`_applyMipRange`) and confirm
  the missing `mipLevelCount > 1` guard. Without the trace, the agent
  has to reason about iOS-version-conditional ANGLE/Metal behavior
  with no on-device debugger.