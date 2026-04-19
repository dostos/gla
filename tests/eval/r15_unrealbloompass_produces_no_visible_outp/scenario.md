# R15: UnrealBloomPass produces no visible output on 3d-force-graph

## User Report
### Problem

The 3D force graph in the KB Synthesis tab should have a neon bloom/glow effect via Three.js `UnrealBloomPass`, matching the [official 3d-force-graph bloom example](https://vasturiano.github.io/3d-force-graph/example/bloom-effect/). The graph renders and centers correctly, but the bloom effect is completely invisible regardless of approach.

### Environment

- **3d-force-graph**: v1.80.0 (UMD build, bundles Three.js r183)
- **Three.js**: v0.183.2 (r183)
- **Browser**: Chrome (macOS)

### What Works

- 3D graph renders correctly with proper node colors
- `graph.postProcessingComposer()` returns a valid EffectComposer
- **Custom test pass (red overlay) works** — proves the EffectComposer pipeline itself is functional. A simple pass that does `gl.clearColor(1, 0, 0, 0.3); gl.clear(gl.COLOR_BUFFER_BIT)` successfully tints the scene red.

### What Doesn't Work

- UnrealBloomPass produces zero visible output in every configuration tested
- The scene renders as if no bloom pass exists (original scene visible, no glow)

### Approaches Tried (All Failed)

1. esbuild bloom-only bundle (split architecture)
2. Unified esbuild bundle (single THREE instance)
3. Importmap + raw vendored source files (no bundling)
4. esm.sh CDN (exact official example pattern)
5. `new ForceGraph3D(el)` vs `ForceGraph3D()(el)`
6. Various bloom parameter combinations (strength 2, 3, 4, 10; threshold 0)
7. Custom nodeThreeObject meshes

### Debugging Findings

1. **EffectComposer pipeline works**: A custom pass that uses raw WebGL produces visible output through the same `graph.postProcessingComposer()`.

2. **UnrealBloomPass.render() IS called**: Debug logging inside the bloom pass confirms `render()` fires every frame with correct parameters (`renderToScreen: true`, correct buffer dimensions, `gl.getError() === 0`).

3. **No WebGL errors**: `gl.getError()` returns 0 after bloom rendering. No shader compilation errors visible in console.

4. **The issue is inside UnrealBloomPass's internal rendering**: UnrealBloomPass uses `FullScreenQuad.render(renderer)` which calls `renderer.render(mesh, camera)` with ShaderMaterial-based full-screen quads for the high-pass filter, blur passes, and final composite. These internal `renderer.render()` calls produce no visible output, while direct GL calls to the same context work fine.

### Possible Root Causes (Untested)

- **ShaderMaterial compilation failure**: Three.js doesn't throw on shader compilation errors — it logs warnings and silently produces no draw output. The bloom pass's internal ShaderMaterials (LuminosityHighPassShader, separable blur, composite) might fail to compile for a reason not caught by `gl.getError()`. Need to check `renderer.info.programs` or `gl.getProgramInfoLog()`.
- **FullScreenQuad `renderer.render(mesh, camera)` incompatibility**: The FullScreenQuad helper calls `renderer.render(this._mesh, _camera)` where the mesh and camera are from a different THREE instance than the renderer.
- **`three.module.min.js` missing side effects**: Three.js's `package.json` declares `"sideEffects": false`, allowing bundlers to tree-shake aggressively.
- **Browser/GPU-specific issue**: Possibly related to HalfFloatType render targets or specific WebGL extensions.

## Expected Correct Output
Scene rendered with a visible neon glow added to bright nodes — matching the
official 3d-force-graph bloom example.

## Actual Broken Output
Scene rendered identically to a no-bloom configuration. The fullscreen quad
draw is issued, no GL error is raised, but no pixels in the final framebuffer
reflect the bloom pass's contribution.

## Ground Truth
A post-processing bloom pass is wired into the EffectComposer pipeline, the
pass's `render()` is called every frame, the fullscreen quad draw call issues
without errors (`gl.getError() === 0`), but the framebuffer shows no glow.
The underlying scene renders correctly; only the bloom contribution is
missing.

The reporter's debugging localizes the failure to UnrealBloomPass's internal
fullscreen-quad rendering: the pass's outer pipeline is functional (a custom
red-overlay pass through the same composer works), but the bloom-internal
draws produce no output.

> A custom test pass (red overlay) works — proves the EffectComposer pipeline
> itself is functional.

> UnrealBloomPass.render() IS called: Debug logging inside the bloom pass
> confirms render() fires every frame with correct parameters
> (renderToScreen: true, correct buffer dimensions, gl.getError() === 0).

> The issue is inside UnrealBloomPass's internal rendering: UnrealBloomPass
> uses FullScreenQuad.render(renderer) which calls renderer.render(mesh,
> camera) with ShaderMaterial-based full-screen quads ... These internal
> renderer.render() calls produce no visible output, while direct GL calls
> to the same context work fine.

The most likely failure mode the reporter identifies is silent shader-program
breakage in those internal ShaderMaterials, undetected because the WebGL
error surface does not reflect it:

> Three.js doesn't throw on shader compilation errors — it logs warnings and
> silently produces no draw output. The bloom pass's internal ShaderMaterials
> (LuminosityHighPassShader, separable blur, composite) might fail to compile
> for a reason not caught by gl.getError(). Need to check
> renderer.info.programs or gl.getProgramInfoLog().

The thread has no maintainer fix or confirmed root cause; the diagnosis above
is the reporter's localization based on direct instrumentation. The class of
bug — "fullscreen post-process draw issues, no GL error, no visible
framebuffer change" — is what this scenario reproduces in raw GL.

## Difficulty Rating
4/5

## Adversarial Principles
- silent_shader_failure
- post_process_pipeline_invisible_break
- glerror_zero_but_no_output

## How OpenGPA Helps
Querying the draw-call list shows the fullscreen-quad bloom draw was issued
with the expected program and viewport, while a framebuffer dominant-color
query shows the post-bloom framebuffer is identical to the pre-bloom
framebuffer. Inspecting the program's link/info log via OpenGPA exposes the
silent shader breakage that `glGetError` does not surface.

## Source
- **URL**: https://github.com/daronyondem/agent-cockpit/issues/142
- **Type**: issue
- **Date**: 2026-04-19
- **Commit SHA**: (n/a)
- **Attribution**: Reported in agent-cockpit issue #142

## Tier
core

## API
opengl

## Framework
none

## Bug Signature
```yaml
type: framebuffer_dominant_color
spec:
  region: full
  expected_distinct_from: pre_pass_framebuffer
  observed: identical_to_pre_pass_framebuffer
  pass_name: bloom
```

## Predicted OpenGPA Helpfulness
- **Verdict**: yes
- **Reasoning**: The bug is precisely the kind of "draw call issued, no GL
  error, no visible effect" failure that a raw-fact graphics debugger
  illuminates. OpenGPA's per-draw program info log + before/after framebuffer
  comparison turn an invisible silent failure into a concrete, queryable
  fact.

## Observed OpenGPA Helpfulness
- **Verdict**: ambiguous
- **Evidence**: validation skipped (--no-validate)
