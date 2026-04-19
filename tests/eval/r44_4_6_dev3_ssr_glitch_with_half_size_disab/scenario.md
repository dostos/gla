# R44_4_6_DEV3_SSR_GLITCH_WITH_HALF_SIZE_DISAB: Full-size SSR corrupted by unsanitized NaN in reflection buffer base mip

## User Report
### Tested versions

4.6-dev3

### System information

Linux - Nvidia RTX 4060 driver 580

### Issue description

With the new SSR overhaul #111210 which is amazing!! but if i disable the "half size" in the project settings it starts glitching

### Steps to reproduce

https://github.com/user-attachments/assets/5345d494-5c6f-4a47-b49b-b613dc62dfa5

### Minimal reproduction project (MRP)

N/A

## Expected Correct Output
A uniformly blue reflection buffer (the scene color) with, at worst, a single-pixel darkening at the center where the material wrote NaN — the NaN should be sanitized at every stage including the base level.

## Actual Broken Output
A roughly 3x3 pixel black/garbage blotch around the center, caused by bilinear filtering spreading the unsanitized NaN sample to its neighbors, visually matching the "glitch" blobs shown in the reporter's video.

## Ground Truth
When Screen-Space Reflections run at full resolution in Godot 4.6-dev3, a single pixel that emits NaN from a scene material propagates across the reflection output and produces flickering/black glitches. The problem disappears with "half size" enabled because the half-resolution path discards the NaN before it reaches the mip chain.

The reporter's scene contains a material that writes NaN into the color buffer consumed by SSR. A developer confirms: `> The material seems to write a NaN pixel which propagates really quickly with SSR due to infinite bounces it does.` The fix author then explains the exact root cause: `> It already sanitizes when computing. Mipmaps. I guess I just missed adding the sanitization code for the base level` — referring to the `isnan` guard in `servers/rendering/renderer_rd/shaders/effects/copy.glsl#L86` which runs only on mip downsample, leaving the base level unprotected. The SSR overhaul PR #111210 introduced the Gaussian mip chain but did not apply the guard symmetrically across all levels.

## Difficulty Rating
4/5

## Adversarial Principles
- asymmetric_sanitization_across_mip_levels
- nan_propagation_via_linear_filtering
- single_pixel_defect_amplified_by_multi_pass_pipeline
- regression_introduced_by_recent_overhaul

## How OpenGPA Helps
An OpenGPA query that inspects the contents of each mip level of the SSR reflection target (or diffs expected-vs-observed colors in a central region) would reveal NaN values present at level 0 but absent at levels ≥ 1, immediately localizing the missing sanitization to the base-level write rather than the downsample passes.

## Source
- **URL**: https://github.com/godotengine/godot/issues/112418
- **Type**: issue
- **Date**: 2026-04-18
- **Commit SHA**: (n/a)
- **Attribution**: Reported by Godot user; root cause identified in comment thread citing copy.glsl#L86 and PR #111210

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
  region: {x: 28, y: 28, w: 8, h: 8}
  expected_rgb_approx: [51, 128, 204]
  tolerance: 20
  forbidden_rgb_approx: [0, 0, 0]
  rationale: center region should remain scene-blue; any near-black pixels indicate NaN leaked from the unsanitized base mip
```

## Upstream Snapshot
- **Repo**: https://github.com/godotengine/godot
- **SHA**: e6aa06d3de372513bedb036d2adb1052a9b4b87f
- **Relevant Files**:
  - servers/rendering/renderer_rd/shaders/effects/copy.glsl  # base of fix PR #112732 (sanitize INF/NaN in copy_to_rect)
  - servers/rendering/renderer_rd/effects/copy_effects.cpp
  - servers/rendering/renderer_rd/effects/ss_effects.cpp

## Predicted OpenGPA Helpfulness
- **Verdict**: yes
- **Reasoning**: The bug is a classic numeric-precision defect that is invisible in shader source review (each pass "looks fine") but trivial to spot by inspecting intermediate render targets: level 0 contains NaN, levels 1+ do not. OpenGPA's ability to dump and compare texture-level contents turns a multi-hour hunt into a one-query answer.

## Observed OpenGPA Helpfulness
- **Verdict**: ambiguous
- **Evidence**: validation skipped (--no-validate)
