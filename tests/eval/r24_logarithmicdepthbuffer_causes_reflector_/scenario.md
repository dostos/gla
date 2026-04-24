# R24: logarithmicDepthBuffer causes Reflector to be rendered incorrectly

## User Report
When rendering a scene with a Reflector that has an opaque surface behind it, the surface gets rendered after the reflector and overwrites it, seemingly neglecting the depth buffer (that is set correctly).

This was caused in a giant project that is not open source and therefore it ranges from very complicated to impossible to reproduce the exact scene. The reason for using `logarithmicDepthBuffer` was that I was encountering z-fighting earlier and the logarithmicDepthBuffer took care of it quite swiftly. Therefore it caused quite a headache to figure this out as the cause of my problem.

Expected: `logarithmicDepthBuffer` probably shouldn't change the render-order for Reflector specifically. (I understand the logarithmicDepthBuffer is supposed to change the render order, however as it works with solid materials in the same range and only fails on the Reflector, I think this is caused by an unwanted prioritization somewhere.)

With `logarithmicDepthBuffer = false` the slanted mirror traverses the cabin and reflects the floor, back wall and right side wall correctly. With `logarithmicDepthBuffer = true` and EVERYTHING else identical, in the center the opaque mesh is drawn OVER/AFTER the mirror, overwriting it. The outside of the door (no opaque mesh behind the reflector) and the section over the back wall render correctly. Only Reflector objects are affected.

This is for sure not a problem with render order or disabled depthWrite, as the only thing that changed between the two pictures is the logarithmicDepthBuffer value.

Platform: Desktop, Windows, Chrome/Firefox, three.js r129.

## Expected Correct Output
The reflector quad (closer to the camera at z=-3) should occlude the opaque wall behind it (at z=-5). The center pixel of the framebuffer should be red (the reflector color).

## Actual Broken Output
The opaque wall behind the reflector punches through and is visible at the center of the screen. The center pixel reads as blue (the wall color) even though the wall was drawn first and the reflector is geometrically in front.

## Ground Truth
The opaque world geometry uses a shader pipeline that overrides `gl_FragDepth` with the logarithmic-depth encoding (`gl_FragDepth = log2(1.0 + w) / log2(far + 1.0)`). The reflector surface shader does not — it leaves `gl_FragDepth` at the default `gl_FragCoord.z`, which is the standard perspective-divided NDC depth.

The two encodings produce values on completely different scales for the same view-space distance. With near=0.1 / far=1000, a point at z=-5 written through the log encoding lands near 0.26, while a point at z=-3 written with the default encoding lands near 0.97. With `GL_LESS`, the smaller (log-encoded wall) value wins, so subsequent reflector fragments at the closer distance fail the depth test and are discarded. The bug only triggers when there is opaque geometry behind the reflector that has already written log-encoded depth values into the depth buffer; in regions with no opaque mesh behind the reflector, the framebuffer depth is still the cleared default and the reflector is visible normally.

The maintainer (Mugen87) confirms this in the issue thread:

> I guess the problem is that `Reflector` does not include the `logdepthbuf*` shader chunks. Do you mind checking if the following reflector shader solves the issue?

Adding `#include <logdepthbuf_pars_vertex>` / `<logdepthbuf_vertex>` to the vertex stage and `#include <logdepthbuf_pars_fragment>` / `<logdepthbuf_fragment>` to the fragment stage of `Reflector.ReflectorShader` makes the reflector write its depth in the same encoding as the rest of the scene, restoring correct depth comparison. The reporter confirmed in the next comment that the patched shader resolves the issue. Fix landed in PR #21983 (commit 028fb95).

## Fix
```yaml
fix_pr_url: https://github.com/mrdoob/three.js/pull/21983
fix_sha: 028fb95b4774cb49d06544cab98f2147f1fbd533
fix_parent_sha: 2383c1c0e48c3a966926f28a5acdb4b09f5dd35e
bug_class: framework-internal
files:
  - examples/js/objects/Reflector.js
  - examples/jsm/objects/Reflector.js
change_summary: >
  Adds the `logdepthbuf_pars_vertex`, `logdepthbuf_vertex`,
  `logdepthbuf_pars_fragment`, and `logdepthbuf_fragment` shader chunk
  includes to `Reflector.ReflectorShader` so that, when
  `WebGLRenderer.logarithmicDepthBuffer = true`, the reflector surface
  writes `gl_FragDepth` using the same logarithmic encoding as every
  other built-in material — instead of leaving it at the default
  `gl_FragCoord.z`. PR title: "Reflector: Add support for logarithmic
  depth buffer."
```

## Difficulty Rating
4/5

## Adversarial Principles
- effect-only-with-renderer-flag
- shader-only-bug-no-CPU-trace
- depth-encoding-mismatch
- silent-correctness-failure-without-error

## How OpenGPA Helps
A query that dumps the per-draw-call fragment shader sources alongside the depth-buffer values they write would immediately reveal that the world-geometry draw writes a remapped `gl_FragDepth` while the reflector draw does not. A `get_pixel(depth)` lookup on the wall region versus the reflector region would show two depth values whose ordering is inconsistent with the geometry's view-space z, pointing the agent at a depth-encoding mismatch between materials.

## Source
- **URL**: https://github.com/mrdoob/three.js/issues/21980
- **Type**: issue
- **Date**: 2021-06-13
- **Commit SHA**: 028fb95b4774cb49d06544cab98f2147f1fbd533
- **Attribution**: Reported by issue reporter; diagnosis and fix by @Mugen87

## Upstream Snapshot
- **Repo**: https://github.com/mrdoob/three.js
- **SHA**: 2383c1c0e48c3a966926f28a5acdb4b09f5dd35e
- **Relevant Files**:
  - examples/jsm/objects/Reflector.js
  - examples/js/objects/Reflector.js
  - src/renderers/shaders/ShaderChunk/logdepthbuf_pars_vertex.glsl.js
  - src/renderers/shaders/ShaderChunk/logdepthbuf_vertex.glsl.js
  - src/renderers/shaders/ShaderChunk/logdepthbuf_pars_fragment.glsl.js
  - src/renderers/shaders/ShaderChunk/logdepthbuf_fragment.glsl.js
  - src/renderers/WebGLRenderer.js

## Tier
core

## API
opengl

## Framework
none

## Bug Signature
```yaml
type: unexpected_color
spec:
  region: { x: 128, y: 128, w: 1, h: 1 }
  expected_rgb: [230, 26, 26]
  actual_rgb:   [26, 51, 230]
  tolerance: 16
```

## Predicted OpenGPA Helpfulness
- **Verdict**: yes
- **Reasoning**: The root cause is purely a shader-stage depth-encoding mismatch between two draw calls. OpenGPA's per-draw-call shader source dump plus depth-buffer pixel lookup directly surface the mismatch — much faster than reading three.js' shader-chunk plumbing top-down to discover that one material opted out of the log-depth chunks.

## Observed OpenGPA Helpfulness
- **Verdict**: ambiguous
- **Evidence**: validation skipped (--no-validate)
