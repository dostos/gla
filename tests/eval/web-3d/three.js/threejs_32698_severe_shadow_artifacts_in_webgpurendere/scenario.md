# R2: Severe shadow artifacts in WebGPURenderer compared to WebGLRenderer

## User Report

For the same scene `WebGPURenderer` shows severe shadow acne artifacts compared to `WebGLRenderer`.

Both have identical settings regarding:
- Shadow map resolution (1024)
- Shadow map camera near / far
- Render camera near / far
- Shadow bias (0)
- Normal bias (0)

WebGPURenderer shows severe stippled shadow artifacts on lit surfaces. WebGLRenderer renders the same scene correctly with clean shadows.

Live examples:
- [WebGPURenderer (bugged)](https://jsfiddle.net/TobiasNoell/jprxayeb/23/)
- [WebGLRenderer (correct)](https://jsfiddle.net/TobiasNoell/6hj3ear9/)

Version: r182 — Desktop Chrome, Windows

## Ground Truth

The shadow-map depth pass runs with the same face-culling configuration as the main lit pass (`glCullFace(GL_BACK)`), so the depth target is populated with **front-face** depths of the caster. In the subsequent lit pass, the shadow comparison for those same front-facing fragments reduces to "my depth vs. a depth recorded from me" — the two values are numerically near-identical, and the sign of their difference becomes dominated by rasterization and projection noise. The result is pervasive shadow acne on surfaces that are geometrically lit.

The reporter, after a day of investigation, identified the exact root cause:

> It took me all day but I have eventually found the root cause for the severe shadow acne: `WebGPURenderer` did not configured the `side` property of the shadow materials correctly. All shadow map types were wrong except for VSM. This fix makes a huge difference in shadow precision.

And the linked fix PR #32705:

> In `WebGPURenderer`, the shadow side wasn't configured correctly which was the main reasons for the extreme shadow acne.

The fix inverts the material `side` for the shadow pass so that the depth target captures the **back** faces relative to the light, not the front faces. Once the shadow map stores back-face depths, front-face fragments in the lit pass have strictly smaller light-space depth than the stored value and are correctly lit.

Additionally, shadow bias was masking the symptom in most existing examples, which is why the bug went undiagnosed for so long.

## Expected Correct Output
A rotated cube lit by a single directional light, where faces oriented toward the light appear as smooth, uniformly bright regions. The probe patch on the lit top face is overwhelmingly bright pixels.

## Actual Broken Output
The lit faces of the cube are speckled with stippled dark pixels — classic shadow acne. The probe patch contains a bimodal mix of bright (correctly lit) and dark (incorrectly self-shadowed) pixels, even though no bias, no VSM, and no PCF softening are involved.

## Difficulty Rating
4/5

## Adversarial Principles
- same-pass-both-directions (shadow and lit passes share a state that must differ)
- z-fight-degenerates-to-noise (comparing a depth against itself amplifies subpixel/projection noise)
- bias-masks-root-cause (the usual "just add shadow bias" workaround hides the true bug)
- no-gl-error (culling the wrong face is perfectly legal API usage — nothing raises an error)

## How OpenGPA Helps
A per-draw state query like "for the draw that wrote the depth-attachment of FBO `sFbo`, what was `GL_CULL_FACE_MODE` and what was the min/max depth of the rasterized fragments? Then compare against the `GL_CULL_FACE_MODE` of the lit-pass draws that sample that texture." immediately surfaces that both passes used `GL_BACK` and that the shadow map's depth range matches the lit draws' front-face depth range — the signature of wrong-side shadow capture. An agent without OpenGPA is left to guess between bias, near/far, precision, and sampler filtering.

## Source
- **URL**: https://github.com/mrdoob/three.js/issues/32698
- **Type**: issue
- **Date**: 2025-10-29
- **Commit SHA**: 5e01df88482b754e607750eb981e9501bc5bfbc7
- **Attribution**: Reported by @TobiasNoell; root cause found and fixed by @Mugen87 in PR #32705

## Tier
core

## API
opengl

## Framework
none

## Bug Signature
```yaml
type: color_histogram_in_region
spec:
  region: "32x32 patch centered at (W/2, 3H/5) on the lit top face of the cube"
  expected_distribution: "overwhelmingly bright (R>160) pixels; <50 dark (R<80) pixels"
  actual_distribution: "bimodal — many bright pixels interleaved with many dark (R<80) pixels, producing stippled acne"
  tolerance: "bug present when dark-pixel count > 50 in a 1024-pixel probe patch"
```

## Upstream Snapshot
- **Repo**: https://github.com/mrdoob/three.js
- **SHA**: dca4d8bf512b02e15cc7e43d430a91c345140cbe
- **Relevant Files**:
  - src/renderers/common/Renderer.js  # base of fix PR #32705 (shadow side selection)
  - src/renderers/common/ShadowMap.js
  - src/materials/MeshDepthMaterial.js

## Predicted OpenGPA Helpfulness
- **Verdict**: yes
- **Reasoning**: The bug is purely a per-pass state mismatch — `GL_CULL_FACE_MODE` during the shadow-FBO draw vs. the lit draws that sample the resulting depth texture. OpenGPA's per-draw state snapshot plus depth-range stats directly expose that the shadow-map draw captured front-face depths, turning the shadow compare into a degenerate self-comparison. A code-only agent must span renderer, shadow-material, and pass-management logic to notice the missing side inversion, which is exactly why the upstream reporter needed a full day and a SpectorJS diff to find it.

## Observed OpenGPA Helpfulness
- **Verdict**: ambiguous
- **Evidence**: validation skipped (--no-validate)
