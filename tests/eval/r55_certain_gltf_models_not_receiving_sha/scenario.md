# R55_CERTAIN_GLTF_MODELS_NOT_RECEIVING_SHA: Certain GLTF models do not receive shadows on Windows

## User Report
Minecraft Education edition has a tool for exporting .GLB files directly from
the game, but the resulting GLB file won't receive shadows when displayed
using three.js on Windows devices.

This issue occurs when using Windows browsers (Firefox, Chrome, Edge), but
not when using MacOS browsers (Chrome, Firefox, and Safari). See the original
thread on discourse.threejs.org for more information.

Steps to reproduce the behavior:
1. Go to the demo website (minecraft GLB hosted on Cloudflare Pages).
2. Note that on Windows, the red sphere does not cast a shadow onto the
   Minecraft model.

Expected behavior: The red sphere should cast a shadow onto the 3D model.

Version: r148. Screenshot: Windows users don't see the sphere shadow.

## Expected Correct Output
On a textured Minecraft-style scene where a caster sphere is placed between
a directional light and a large receiver plane, the receiver should show a
visible dark spot under the caster. A pixel sampled inside that spot (say,
screen coordinates near the centre of the shadow) should read substantially
darker than the ambient lit surround — typical expected brightness inside
the shadow is rgb `(30, 30, 30)` ± 20 versus `(200, 200, 200)` ± 20 outside.

## Actual Broken Output
On Windows, the receiver surface shows **no** shadow whatsoever: every pixel
under the caster reads the full lit colour, identical to surrounding pixels.
MacOS renders the same scene with the correct dark spot. Inspecting the
captured vertex-attribute state on the broken platform shows that the
receiver's `normal` attribute is absent (only `position` is present) and
the per-vertex `shadowWorldNormal` intermediate the vertex shader writes
evaluates to `(NaN, NaN, NaN)` — the normal-bias offset in the fragment
then turns the shadow-space coordinate into a random out-of-range value
that the PCF sampler clamps to fully lit.

## Ground Truth
`WebGLRenderer` pre-pends a `shadowmap_vertex` chunk that always computes

```glsl
vec3 shadowWorldNormal = inverseTransformDirection( transformedNormal, viewMatrix );
```

regardless of whether the receiver's geometry actually has a `normal`
attribute. For flat-shaded GLB exports like Minecraft Education's, the
mesh arrives with `position` but NO `normal` attribute. `transformedNormal`
then reads an uninitialized vertex attribute whose default varies by driver:
Windows drivers (Chrome/ANGLE D3D11, Firefox) return NaNs or sentinel
values for unbound attribute reads in certain paths; MacOS drivers quietly
return (0, 0, 1). `shadowWorldNormal` therefore ends up `(NaN, NaN, NaN)`
on Windows, the subsequent `shadowWorldPosition += shadowWorldNormal *
shadowNormalBias` pushes the shadow-coord out of `[0, 1]`, and the PCF
lookup returns "fully lit" — no visible shadow.

The maintainer diagnosis in PR #33391:

> Flat shading with no vertex normals can break shadows on certain devices
> since `shadowWorldNormal` might end up with `NaN` values.
> The PR fixes that by introducing a new define that detects whether a
> geometry has vertex normals or not and only then computes
> `shadowWorldNormal`. Otherwise it uses the fallback value.

The fix:
- `src/renderers/shaders/ShaderChunk/shadowmap_vertex.glsl.js` — guard the
  `shadowWorldNormal` computation behind `#ifdef HAS_NORMAL`, use the
  vec3(0) fallback otherwise.
- `src/renderers/webgl/WebGLProgram.js` — emit `#define HAS_NORMAL` when
  `parameters.vertexNormals` is true.
- `src/renderers/webgl/WebGLPrograms.js` — compute `parameters.vertexNormals
  = !! geometry.attributes.normal`.

The minimal GL repro in `main.c` emulates the same pipeline: a vertex
shader computes `shadowWorldNormal` from a normal attribute that was never
enabled; the captured attribute read yields NaNs, which flow through the
normal-bias offset into an out-of-range shadow coord and the PCF sample
returns 1.0 ("lit").

## Fix
```yaml
fix_pr_url: https://github.com/mrdoob/three.js/pull/33391
fix_sha: 740dd76c69563f8f778472350d7544ac2a88cc96
fix_parent_sha: f3fa844ba4ca59d4f1bef62daadcea720456de39
bug_class: framework-internal
files:
  - src/renderers/shaders/ShaderChunk/shadowmap_vertex.glsl.js
  - src/renderers/webgl/WebGLProgram.js
  - src/renderers/webgl/WebGLPrograms.js
change_summary: >
  Guard the `shadowWorldNormal` computation in the shadowmap vertex chunk
  behind a new `HAS_NORMAL` preprocessor define, emitted by `WebGLProgram`
  whenever the geometry actually has a `normal` attribute (detected in
  `WebGLPrograms` via `!! geometry.attributes.normal`). Meshes without
  vertex normals now use a safe fallback (`vec3( 0.0 )`) instead of
  reading an unbound attribute that returns NaN on Windows drivers and
  breaks the shadow coordinate downstream.
```

### Captured-literal breadcrumb (for GPA trace validation)
At reproduction time, the vertex-shader varying `vShadowWorldNormal`
(populated from `shadowWorldNormal`) captures as `(NaN, NaN, NaN)` on
Windows and `(0, 0, 1)` on MacOS. The wrong NaN value is produced on
line ~5 of
`src/renderers/shaders/ShaderChunk/shadowmap_vertex.glsl.js`, from
`inverseTransformDirection( transformedNormal, viewMatrix )` where
`transformedNormal` in turn originates from an unbound `normal` attribute
read. `gpa trace value NaN` on the per-draw-call varying dump surfaces
`shadowmap_vertex.glsl.js` directly. Alternatively, because the fix
conditionally emits `#define HAS_NORMAL` in `WebGLProgram.js`, a trace for
the string literal `HAS_NORMAL` would also land on the two files in the
parameter-plumbing half of the fix. The agent, upon seeing NaN in a
captured varying, should reverse-search the write-site in the compiled
shader source, land on `shadowmap_vertex.glsl.js`, and then work upward
to the `parameters.vertexNormals` plumbing in `WebGLPrograms.js` and
`WebGLProgram.js`.

## Upstream Snapshot
- **Repo**: https://github.com/mrdoob/three.js
- **SHA**: f3fa844ba4ca59d4f1bef62daadcea720456de39
- **Relevant Files**:
  - src/renderers/shaders/ShaderChunk/shadowmap_vertex.glsl.js
  - src/renderers/shaders/ShaderChunk/shadowmap_pars_vertex.glsl.js
  - src/renderers/webgl/WebGLProgram.js
  - src/renderers/webgl/WebGLPrograms.js
  - src/renderers/webgl/WebGLShadowMap.js

## Difficulty Rating
5/5

## Adversarial Principles
- platform-dependent-driver-behavior
- nan-from-unbound-vertex-attribute
- symptom-is-absence-of-shadow
- shader-ifdef-guard-missing

## How OpenGPA Helps
Dumping per-draw-call varyings at the shadow-receive draw shows
`vShadowWorldNormal = (NaN, NaN, NaN)` on broken runs and a finite vector
on working runs. A `gpa trace value NaN` on that varying immediately
identifies the vertex-shader site that produced the NaN —
`shadowmap_vertex.glsl.js` — which the fix modifies. Identifying which
preprocessor define to introduce (`HAS_NORMAL`) then falls out of a
second glance at `WebGLProgram.js`, which the agent navigates to via the
shader chunk's owning renderer.

## Source
- **URL**: https://github.com/mrdoob/three.js/issues/21483
- **Type**: issue
- **Date**: 2021-03-12
- **Commit SHA**: 740dd76c69563f8f778472350d7544ac2a88cc96
- **Attribution**: Reported by @aufyx (three.js #21483); root cause identified and fixed by @Mugen87 in PR #33391.

## Tier
snapshot

## API
opengl

## Framework
three.js

## Bug Signature
```yaml
type: unexpected_color
spec:
  region: { x: 128, y: 128, w: 1, h: 1 }
  expected_rgb: [30, 30, 30]
  actual_rgb:   [200, 200, 200]
  tolerance: 24
  note: >
    Pixel at the center of a circle where a caster sphere should project
    a shadow onto a receiver plane. Expected dark because the shadow
    sample returns occluded; broken path skips the shadow because
    shadowWorldNormal is NaN and the shadow-map lookup falls outside [0, 1].
```

## Predicted OpenGPA Helpfulness
- **Verdict**: yes
- **Reasoning**: The symptom is shadow-free output, which gives no
  source hint. The breadcrumb is a NaN in a specific varying; reverse-
  searching that captured NaN's write site routes straight to the
  shadow-chunk file that the PR modifies. Without the capture, the
  agent would have to read WebGLShadowMap.js plus all shadow shader
  chunks top-down.

## Observed OpenGPA Helpfulness
- **Verdict**: ambiguous
- **Evidence**: validation skipped (--no-validate)
