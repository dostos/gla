# R213: SoftShadows broken with three.js r182 (unpackRGBAToDepth removed)

## User Report
Upgrading three.js from 0.181.0 to 0.182.0 with `@react-three/drei` 10.7.7 and `@react-three/fiber` 9.4.2, dropping `<SoftShadows />` into a `<Canvas shadows>` scene now throws a shader compile error and shadows render black/invalid:

```
THREE.WebGLProgram: Shader Error 0 - VALIDATE_STATUS false
Material Type: MeshStandardMaterial

FRAGMENT
ERROR: 0:1304: 'unpackRGBAToDepth' : no matching overloaded function found
```

Reverting to three 0.181.0 makes it work again. Reproduction is just:

```jsx
<Canvas shadows>
  <SoftShadows />
  {/* any scene casting shadows */}
</Canvas>
```

The reporter notes that three.js r182 modernized shadow mapping (PRs #32181, #32303, #32407, #32443) and switched from RGBA-packed depth to native depth textures, which appears to have removed the `unpackRGBAToDepth()` helper that drei's PCSS shader still calls. They suggest replacing the call with a direct `texture2D(shadowMap, uv + offset).r` sample, but want confirmation from maintainers and a released fix.

Environment: node 24.10.0, npm 11.6.4.

## Expected Correct Output
With `<SoftShadows />` mounted on three r182, the program links cleanly and the scene renders soft (PCSS) shadow penumbrae as it does on r181.

## Actual Broken Output
Shader compilation/link fails with `'unpackRGBAToDepth' : no matching overloaded function found` at line 1304 of the generated `MeshStandardMaterial` fragment shader. Anything the SoftShadows-injected program touches falls back / renders incorrectly; downstream materials log the same `VALIDATE_STATUS false` error.

## Ground Truth
The drei PCSS soft-shadows shader injects a depth-unpack call against the shadow map:

> `depth = unpackRGBAToDepth( texture2D( shadowMap, uv + offset));`

three.js r182 removed `unpackRGBAToDepth` from its shader chunk library when it switched shadow maps from RGBA-packed depth to native depth textures (the linked three.js PRs #32181, #32303, #32407, #32443 land that switch). drei's `<SoftShadows />` PCSS shader, defined in `src/core/softShadows.tsx`, never adopted the new convention, so its injected shader chunk references a function the runtime no longer provides — the fragment shader fails to compile and any material the soft-shadows pass touches errors out at link time.

A drei maintainer confirms the fix exists for the legacy (WebGL2) renderer, with WebGPU still pending tracked in drei issue #2664:

> "Soft Shadows is REALLY hard... I have fixed this for legacy to match 182 but it will be a bit before its done in webgpu. To track webgpu see #2664."

The fix in `src/core/softShadows.tsx` swaps the packed-depth read for a direct `.r` sample of the depth texture (`depth = texture2D(shadowMap, uv + offset).r;`), matching three r182's native-depth shadow-map layout. See https://github.com/pmndrs/drei/issues/2583 for the upstream thread.

## Fix
```yaml
fix_pr_url: (auto-resolve from drei issue #2583 — maintainer landed a "legacy" fix but did not link the merge PR in-thread)
fix_sha: (auto-resolve)
fix_parent_sha: (auto-resolve)
bug_class: legacy
framework: drei
framework_version: 10.7.7
files: []
change_summary: >
  drei's SoftShadows PCSS shader calls three.js's removed
  unpackRGBAToDepth() helper; the maintainer-confirmed fix updates the
  injected GLSL in src/core/softShadows.tsx to sample the new native
  depth texture directly (`texture2D(shadowMap, uv + offset).r`) so the
  fragment shader links on three r182. Fix PR was not surfaced in the
  upstream thread, so the scenario is retained as a legacy bug-pattern
  reference.
```

## Flywheel Cell
primary: framework-maintenance.web-3d.code-navigation
secondary:
  - framework-maintenance.web-3d.captured-literal-breadcrumb
  - framework-maintenance.web-3d.shader-compile-error

## Difficulty Rating
3/5

## Adversarial Principles
- bug-lives-inside-framework-not-user-code
- shader-error-message-names-the-missing-symbol-but-not-the-fix-site
- diagnosis-requires-grep-not-pixel-comparison
- cross-package-version-skew-three-vs-drei

## How OpenGPA Helps
`gpa trace` on the failing frame surfaces the `glLinkProgram`/`glGetProgramiv` failure with the captured fragment-shader source — `/programs/<id>/source` exposes the exact GLSL string that names `unpackRGBAToDepth`, letting the agent grep drei's source for that literal and land directly on `src/core/softShadows.tsx` rather than guessing among shadow-related chunks. `/programs/<id>/uniforms` further confirms the offending program is the SoftShadows-injected MeshStandardMaterial variant rather than three's own ShadowMaterial.

## Source
- **URL**: https://github.com/pmndrs/drei/issues/2583
- **Type**: issue
- **Date**: 2026-04-27
- **Commit SHA**: (auto-resolve — fix landed in drei "legacy" path; PR not cited in thread)
- **Attribution**: Reported on pmndrs/drei #2583; legacy fix acknowledged by @DennisSmolek in-thread; webgpu work tracked in drei #2664.

## Tier
maintainer-framing

## API
opengl

## Framework
drei

## Bug Signature
```yaml
type: code_location
spec:
  expected_files:
    - src/core/softShadows.tsx
  fix_commit: (auto-resolve)
```

## Predicted OpenGPA Helpfulness
- **Verdict**: yes
- **Reasoning**: The captured fragment-shader source (via `/programs/<id>/source`) contains the literal `unpackRGBAToDepth` call drei injects. An agent with that captured string can grep drei's repo for the exact symbol and land on `src/core/softShadows.tsx` deterministically, instead of having to guess across three.js's many shadow-related shader chunks. Without GPA, the only signal is the runtime error message — which names the missing function but not the package or file that injected it.