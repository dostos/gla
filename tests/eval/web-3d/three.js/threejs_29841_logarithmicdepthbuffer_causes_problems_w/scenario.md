# R1: logarithmicDepthBuffer breaks transparent draw order with EffectComposer on Intel UHD

## User Report
Setting `logarithmicDepthBuffer: true` on `THREE.WebGLRenderer` and rendering
through an `EffectComposer` with a `RenderPass` causes transparent objects to
disappear when an opaque object is positioned behind them — but only on some
Windows machines (reproduced on Intel UHD Graphics, i5-10210U, Windows 10,
Chrome/Edge). On most devices (e.g. macOS M2 Pro) the same scene renders
correctly with the green transparent sphere visible in front of the red opaque
sphere.

If we skip `EffectComposer` and render directly to the default framebuffer the
result is correct everywhere — so the bug only shows up with the off-screen
render target path.

Repro:

1. `new THREE.WebGLRenderer({ logarithmicDepthBuffer: true })`
2. Build a scene with a small opaque red sphere and a larger transparent green
   sphere in front of it (`transparent: true, opacity: 0.5`).
3. Wrap rendering in `new EffectComposer(renderer)` with a `RenderPass` and an
   `OutputPass`.
4. `composer.render()` per frame.

Affected: three.js r170 (also reproduced on r180 by another reporter on Intel
UHD 620 / 630). Possibly a `gl_FragDepth` precision or GPU-driver interaction.

Live fiddle: https://jsfiddle.net/2tmf7xj9/

## Expected Correct Output
The transparent green sphere should be visible in the foreground, blended over
the opaque red sphere behind it — the same result you see on most GPUs and
when rendering directly to the canvas without `EffectComposer`.

## Actual Broken Output
On affected Intel UHD devices the transparent sphere vanishes — only the
opaque sphere is drawn. The transparent draw appears to be depth-rejected
against itself or against the framebuffer's logarithmic depth contents.

## Ground Truth
The maintainer could not reproduce on macOS M2 Pro and acknowledged the bug
is GPU/driver-specific:

> It's hard to pinpoint the issue but maybe there are problems with
> `gl_FragDepth` on these devices.

No fix PR landed against `logarithmicDepthBuffer` for this report. Instead
the maintainer steered users to a reversed-depth-buffer workflow and
signaled deprecation:

> Consider a reversed depth buffer as a better alternative compared to
> logarithmic depth buffer. Unlike logarithmic depth buffer, it does not
> require custom vertex/fragment shader code and does not prevent GPU
> optimizations like early-z testing. At some point, three.js is going to
> deprecate logarithmic depth buffer and remove it from the library.

Source: https://github.com/mrdoob/three.js/issues/29841 (comments by
@Mugen87). Examples cited: `webgl_reversed_depth_buffer` and
`webgpu_reversed_depth_buffer`.

The root cause lives in three.js's `logdepthbuf` shader chunks
(`logdepthbuf_pars_fragment.glsl.js`, `logdepthbuf_fragment.glsl.js`) which
write `gl_FragDepth` from a per-fragment log of `vFragDepth`. On affected
Intel UHD drivers this output interacts incorrectly with the depth buffer
attached to the off-screen `WebGLRenderTarget` used by `EffectComposer`'s
`RenderPass`, breaking depth-test ordering for transparent draws. No upstream
fix to the chunks themselves was merged — the issue is treated as a
deprecation candidate rather than a patchable framework bug.

## Fix
```yaml
fix_pr_url: (none — no upstream fix PR; maintainer recommends reversed-depth workflow and signals deprecation of logarithmicDepthBuffer)
fix_sha: (none)
fix_parent_sha: (none)
bug_class: legacy
framework: three.js
framework_version: r170
files: []
change_summary: >
  Fix PR not resolvable from the issue thread alone. Maintainer
  acknowledged a likely gl_FragDepth interaction in the logdepthbuf
  shader chunks on Intel UHD drivers when used with EffectComposer's
  off-screen render target, but recommended a reversed depth buffer
  workflow (and signaled future deprecation of logarithmicDepthBuffer)
  instead of patching the affected shader path. Scenario retained as a
  legacy bug-pattern reference.
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
- gpu-driver-dependent-symptom-not-reproducible-on-dev-machine
- no-clean-fix-pr-only-deprecation-guidance

## How OpenGPA Helps
A `gpa trace` of the broken frame would expose two diagnostic signals the user
can't see from JS: (1) the `RenderPass` draws into a `WebGLRenderTarget` whose
depth attachment is being written via `gl_FragDepth` from three.js's
`logdepthbuf_fragment` chunk — `/draws/<id>/uniforms` and the captured
fragment shader source pin the chunk that owns the write; (2) the transparent
draw's depth-test outcome and `gl_FragDepth` output can be compared against
the opaque draw's stored depth via `/draws/<id>/depth_samples`, showing
whether the transparency is being rejected by depth test (driver-precision
bug) versus alpha-blended into background (a state bug). That distinguishes
"logdepthbuf chunk on this driver" from "EffectComposer state mismatch."

## Source
- **URL**: https://github.com/mrdoob/three.js/issues/29841
- **Type**: issue
- **Date**: 2024-11-04
- **Commit SHA**: (none — no fix PR)
- **Attribution**: Reported in three.js issue #29841; maintainer commentary by @Mugen87 recommending reversed depth buffer workaround.

## Tier
maintainer-framing

## API
opengl

## Framework
three.js

## Bug Signature
```yaml
type: code_location
spec:
  expected_files:
    - src/renderers/shaders/ShaderChunk/logdepthbuf_fragment.glsl.js
    - src/renderers/shaders/ShaderChunk/logdepthbuf_pars_fragment.glsl.js
  fix_commit: (none)
```

## Predicted OpenGPA Helpfulness
- **Verdict**: partial
- **Reasoning**: GPA can localize the suspect shader chunk by surfacing the captured fragment shader source for the transparent draw and showing that `gl_FragDepth` is being written from the `logdepthbuf` snippet. That points an agent at `src/renderers/shaders/ShaderChunk/logdepthbuf_*` for the diagnosis. However, because no fix PR exists upstream — the resolution is "switch to reversed depth buffer" — the agent's reward signal is bounded: it can correctly identify the affected chunk and the workaround, but cannot match a merged-files list from a fix PR.

## Observed OpenGPA Helpfulness
- **Verdict**: ambiguous
- **Evidence**: validation skipped (--no-validate)
