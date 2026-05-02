# R54_BLACK_SQUARES_WHEN_RENDERING_GLASS_MA: Black squares on glass materials with directional light

## User Report
When I load the AnisotropyBarnLamp.glb model using the webgl_loaders_gltf
example and then add a DirectionalLight to the scene, small black squares
appear on the glass material. I tried using SpotLight and PointLight as
well, and the same issue occurs. However, adding only an AmbientLight does
not cause this problem. If no light sources are added to the scene, the
issue does not appear at all. Additionally, when I increase the roughness
of the glass material, the black squares become larger until they cover
the entire mesh.

Reproduction steps:
1. add AnisotropyBarnLamp.glb Model
2. add DirectionalLight

Version: r183. Browser: Chrome. OS: Linux.

## Expected Correct Output
The anisotropic glass surface, lit by a DirectionalLight of reasonable
intensity, should shade smoothly. The center pixel of the framebuffer —
covering a portion of the anisotropic highlight — should land in a
well-defined grey/blueish range, `(70, 80, 100)` ± ~30 per channel. No
region of the surface should read as pure black `(0, 0, 0)`.

## Actual Broken Output
Scattered fragments across the anisotropic surface read as pure black
`(0, 0, 0)` — the "black squares" the reporter describes. As `roughness`
rises, the black region grows until the whole surface is black. In a
captured frame, sampling inside one of the black patches reads back
`(0, 0, 0)` while neighbouring pixels return finite colors; the
intermediate floating-point color buffer (where one exists) contains
`+Inf` / NaN at those pixels which the final write-to-LDR clamps to 0.

## Ground Truth
The PR that caused this regression (#32330, earlier r182 refactor) had
removed a `saturate()` wrap around the anisotropic visibility term
`V = 0.5 / (gv + gl)` but did **not** port the division-by-zero guard that
its non-anisotropic sibling `V_GGX_SmithCorrelated()` uses. With no guard,
when `gv + gl ≈ 0` — which occurs for geometry whose normal, tangent and
bitangent configuration drives both geometric-shadowing factors to zero —
the shader computes `0.5 / 0.0 = +Inf`, multiplied into the BRDF, and the
final tonemap clamps to a black pixel. The reporter's symptoms line up
exactly:

- Only appears with a direct light (`DirectionalLight`, `SpotLight`,
  `PointLight`). `AmbientLight` doesn't hit the anisotropic specular path,
  so it's unaffected.
- Grows with roughness. Larger `alphaT` / `alphaB` widen the region where
  `gv + gl` drops below floating-point precision.

The maintainer diagnosis in PR #33205 says verbatim:

> Removing the `saturate()` was right but it was missed to introduce the
> same guard as `V_GGX_SmithCorrelated()` to prevent division through `0`.
> That produces `NaN` values and the reported black pixels.

The fix is a two-line shader change in exactly the place where the write
happens:

- `src/nodes/functions/BSDF/V_GGX_SmithCorrelated_Anisotropic.js`: wrap the
  division with `EPSILON` as the denominator's minimum.
- `src/renderers/shaders/ShaderChunk/lights_physical_pars_fragment.glsl.js`:
  replace `float v = 0.5 / ( gv + gl );` with
  `return 0.5 / max( gv + gl, EPSILON );`

The minimal GL repro in `main.c` stands up the same pathological `gv + gl`
configuration. It uploads per-fragment `alphaT` / `alphaB` / tangent-space
vectors that drive both visibility terms to zero, and writes
`vec3 v = 0.5 / ( gv + gl )` — producing `+Inf` which the LDR output
clamps to black. The fixed version would be `max(gv+gl, 1e-6)` instead.

## Fix
```yaml
fix_pr_url: https://github.com/mrdoob/three.js/pull/33205
fix_sha: 7716cd9415b12c9f29596ca838a7a99814b82787
fix_parent_sha: bfe332d9ee7016ab36dfb79826d421d4487058f4
bug_class: framework-internal
files:
  - src/nodes/functions/BSDF/V_GGX_SmithCorrelated_Anisotropic.js
  - src/renderers/shaders/ShaderChunk/lights_physical_pars_fragment.glsl.js
change_summary: >
  Guard the anisotropic visibility-term division `0.5 / ( gv + gl )` against
  `gv + gl` being zero by clamping the denominator to at least `EPSILON` —
  matching what `V_GGX_SmithCorrelated()` already does for the isotropic
  path. This prevents the BRDF from producing `+Inf` / `NaN` values that
  later tonemap to black pixels on anisotropic materials under direct
  lights.
```

### Captured-literal breadcrumb (for GPA trace validation)
At reproduction time, the per-fragment visibility coefficient `v` written by
the anisotropic BRDF reads back as `+Inf` (HDR buffer) or `0` (after LDR
clamp, for fragments inside a black square). The correct value would be a
small positive finite scalar ~`0.1–10`. The write-site literal is the
constant `0.5` in `0.5 / ( gv + gl )` inside
`src/renderers/shaders/ShaderChunk/lights_physical_pars_fragment.glsl.js`
(within `V_GGX_SmithCorrelated_Anisotropic`), and the analogous
`div( float(0.5), ... )` in
`src/nodes/functions/BSDF/V_GGX_SmithCorrelated_Anisotropic.js`. `gpa trace
value 0.5` over the shader chunk sources, narrowed by context
`V_GGX_Smith` or `alphaT`, surfaces exactly these two files as the fix
candidates. Alternatively, `gpa trace value Inf` (or `+inf`) on captured
HDR framebuffer contents pinpoints the first draw call whose output
contains `+Inf`, whose fragment shader source — when dumped — contains
the same `0.5 / ( gv + gl )` line.

## Upstream Snapshot
- **Repo**: https://github.com/mrdoob/three.js
- **SHA**: bfe332d9ee7016ab36dfb79826d421d4487058f4
- **Relevant Files**:
  - src/nodes/functions/BSDF/V_GGX_SmithCorrelated_Anisotropic.js
  - src/renderers/shaders/ShaderChunk/lights_physical_pars_fragment.glsl.js
  - src/nodes/math/MathNode.js
  - src/renderers/shaders/ShaderChunk/lights_physical_fragment.glsl.js

## Difficulty Rating
4/5

## Adversarial Principles
- div-by-zero-to-inf-propagation
- regression-from-prior-refactor
- only-triggers-with-direct-light
- hdr-nan-clamped-to-zero

## How OpenGPA Helps
Reading back an HDR intermediate framebuffer reveals `+Inf` at the black
fragments — an immediate hint that a shader produced a division by zero.
Dumping the active fragment program at that draw call shows the bare
`0.5 / ( gv + gl )` site that lacks an `EPSILON` guard. A single
`gpa trace value 0.5` query (filtered to shader sources that also mention
anisotropy / `gv` / `gl`) points the agent at the two fix files without
requiring a top-down read of the entire PBR shader graph.

## Source
- **URL**: https://github.com/mrdoob/three.js/issues/33201
- **Type**: issue
- **Date**: 2026-03-17
- **Commit SHA**: 7716cd9415b12c9f29596ca838a7a99814b82787
- **Attribution**: Reported by @tokyo-studio (three.js #33201); diagnosed and fixed by @Mugen87 in PR #33205.

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
  expected_rgb: [70, 80, 100]
  actual_rgb:   [0, 0, 0]
  tolerance: 32
  note: >
    Anisotropic-glass fragment in the center of the framebuffer. Expected a
    finite mid-grey color from the visibility-weighted BRDF; broken path
    writes +Inf (or NaN) which tonemaps to pure black.
```

## Predicted OpenGPA Helpfulness
- **Verdict**: yes
- **Reasoning**: The symptom (black pixels on glass under direct light)
  gives no source-file hint. The root cause is a single divide-by-zero in
  a named shader chunk. An HDR-framebuffer read plus a trace on the
  literal `0.5` constrains the search to exactly the two files in the fix
  — the canonical captured-literal-breadcrumb pattern.

## Observed OpenGPA Helpfulness
- **Verdict**: ambiguous
- **Evidence**: validation skipped (--no-validate)
