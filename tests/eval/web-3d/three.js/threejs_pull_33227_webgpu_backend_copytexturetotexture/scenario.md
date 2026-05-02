# R2: WebGPURenderer.copyTextureToTexture format errors with many simultaneous textures

## User Report
Hello, I have searched by using many different formats but I'm still stuck.

Reproduction steps:
1. Use the WebGPU renderer
2. Call `renderer.copyTextureToTexture( dataTexture, diffuseMap, null, position );`
3. With `forceWebGL: true`
4. I get format errors

In `forceWebGL` mode I had to change the call to `renderer.backend.copyTextureToTexture( dataTexture, diffuseMap, null, position );` — that worked around one issue. But in my actual game I still see many errors.

I tried to reproduce the bug with a basic three.js example and could not — it works fine there. In my real app I am creating 64 textures at the same time and using a piece of canvas image as the data source. I noticed the meshes/materials need to be added to the scene with some delay before any update — without the delay WebGL throws errors (WebGPU does not seem to throw in that case).

Three.js dev (last). No browser/OS info given. Console screenshots show INVALID_OPERATION / format-mismatch warnings around `texSubImage2D` / `copyTexSubImage2D` paths.

Hypothesis from the reporter (possibly wrong): the textures aren't fully created at the time `copyTextureToTexture` first runs, and only become valid a frame or two later.

## Expected Correct Output
`renderer.copyTextureToTexture( dataTexture, diffuseMap, null, position )` should succeed — copying the small `DataTexture` patch onto the larger sRGB diffuse map without console errors, regardless of whether 1 or 64 textures are being initialised in the same frame, and regardless of whether the WebGPU renderer is using its native WebGPU backend or the WebGL2 fallback (`forceWebGL: true`).

## Actual Broken Output
With `forceWebGL: true` and ~64 textures created in the same tick, `copyTextureToTexture` raises GL format / `INVALID_OPERATION` errors during the copy. The same code path is silent on the native WebGPU backend. Calling `renderer.backend.copyTextureToTexture(...)` directly avoids one error in `forceWebGL` mode but other format errors persist until the user manually defers the first `update()` by a frame.

## Ground Truth
This is a **consumer-misuse** scenario at the user's app level (the reporter explicitly closes the thread with `mm yes is a bug from my side ... texture seam's not create directly ? but after is work` and `mesh and material should be add to scene with some delay before any update`), but the maintainer (@Mugen87) used the thread to land a closely-related dev-branch fix for the WebGPU renderer's WebGL2 fallback:

> I have lately correct this on dev here: https://github.com/mrdoob/three.js/pull/33227/changes

PR #33227 ("Renderers: Cache pixel storage parameters") rewrites how `UNPACK_FLIP_Y_WEBGL`, `UNPACK_PREMULTIPLY_ALPHA_WEBGL`, `UNPACK_ALIGNMENT`, and `UNPACK_COLORSPACE_CONVERSION_WEBGL` are applied:

> I've realized today setting pixel storage modes in WebGL 2 is actually a global setting that affects all _subsequent_ texture operations. Because of that, we can cache it in `WebGLState`. This is now in done in `WebGLRenderer` and the WebGL 2 backend of `WebGPURenderer`.

The PR introduces `state.getParameter()` to read back cached values rather than calling `gl.getParameter()` (which can flush the GL queue). Without that caching, when many textures are uploaded back-to-back and then copied via `copyTextureToTexture`, the global pixel-storage state from the most recent `texSubImage2D` upload silently leaks into the framebuffer-blit copy path inside `WebGLTextureUtils.copyTextureToTexture`, producing the format / colour-space / flipY mismatches the reporter saw. PR fixes #33223.

## Fix
```yaml
fix_pr_url: https://github.com/mrdoob/three.js/pull/33227
fix_sha: c6167f9077245c7deab47214ee4e7684d301ed4f
fix_parent_sha: c6167f9077245c7deab47214ee4e7684d301ed4f
bug_class: consumer-misuse
framework: three.js
framework_version: dev
files:
  - src/renderers/WebGLRenderer.js
  - src/renderers/webgl-fallback/utils/WebGLState.js
  - src/renderers/webgl-fallback/utils/WebGLTextureUtils.js
  - src/renderers/webgl/WebGLState.js
  - src/renderers/webgl/WebGLTextures.js
change_summary: >
  Cache WebGL2 pixel-storage parameters (UNPACK_FLIP_Y_WEBGL,
  UNPACK_PREMULTIPLY_ALPHA_WEBGL, UNPACK_ALIGNMENT,
  UNPACK_COLORSPACE_CONVERSION_WEBGL) in WebGLState for both the
  classic WebGLRenderer and the WebGPURenderer's WebGL2 fallback,
  and route reads through state.getParameter() so back-to-back
  texture uploads no longer leak global unpack state into the
  copyTextureToTexture blit path.
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
- symptom-is-stateful-not-deterministic-on-minimal-repro
- consumer-misuse-shadowing-real-framework-bug

## How OpenGPA Helps
A `gpa trace` of the WebGL2 fallback path captures every `pixelStorei` call and every `texSubImage2D` / `copyTexSubImage2D` / framebuffer blit in order — making it visually obvious that `UNPACK_FLIP_Y_WEBGL=true` and a non-default `UNPACK_COLORSPACE_CONVERSION_WEBGL` set during the last DataTexture upload are still in effect when `copyTextureToTexture` later binds its scratch source/destination framebuffers. The `/uniforms` and per-draw-call state diff between the failing copy and the working copy points the agent straight at "global pixel-storage state was not reset" — which is exactly the invariant PR #33227 fixes by caching those modes in `WebGLState`.

## Source
- **URL**: https://github.com/mrdoob/three.js/issues/33244
- **Type**: issue
- **Date**: 2026-04-29
- **Commit SHA**: c6167f9077245c7deab47214ee4e7684d301ed4f
- **Attribution**: Reported by the issue author; diagnosed and fixed by @Mugen87 in PR #33227 (closes #33223; referenced from #33244).

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
    - src/renderers/webgl-fallback/utils/WebGLState.js
    - src/renderers/webgl-fallback/utils/WebGLTextureUtils.js
    - src/renderers/webgl/WebGLState.js
    - src/renderers/webgl/WebGLTextures.js
    - src/renderers/WebGLRenderer.js
  fix_commit: c6167f9077245c7deab47214ee4e7684d301ed4f
```

## Predicted OpenGPA Helpfulness
- **Verdict**: yes
- **Reasoning**: The root cause is a global GL state leak (`pixelStorei` modes persisting across texture operations) — exactly the class of bug a per-call GL trace surfaces immediately. An agent reading source alone has to reason about which `gl.pixelStorei` calls survive between `setTextureParameters`, `uploadTexture`, and `copyTextureToTexture`; an agent reading a GPA trace sees the sticky unpack state directly in the captured call sequence and is led to `WebGLState` / `WebGLTextureUtils` without guessing.

## Observed OpenGPA Helpfulness
- **Verdict**: ambiguous
- **Evidence**: validation skipped (--no-validate)
