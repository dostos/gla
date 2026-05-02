# R36_GODOT_4_6_BREAKING_SCREEN_SPACE_FOG_SHAD: Godot 4.6 screen-space fog quad + volumetric fog half-screen tint

## User Report

I started a new 4.6 fresh project and checked the world environment node. Without it the Sky3D plugin looks fine, but with Sky3D having the volumetric fog option enabled it still looked completely normal — until we add a camera and rotate it. In the camera perspective the weird artifact of half the screen getting a tint of some sort appears. This goes away when volumetric fog is disabled; the fog option still works normally.

When screen-space fog from SkyDome is enabled this issue occurs, and when the volumetric fog is disabled from the env node the artifact disappears. If the screen-space fog is not enabled at all, then even with volumetric fog + fog enabled on the world env under Sky3D, there are no artifacts.

This issue never occurred before 4.6 — all earlier versions (4.5.1 and before) work absolutely fine. After 4.6 it seems the screen-space fog shader for Sky3D is broken. Same result with D3D12 or Vulkan.

Tested: reproducible in 4.6 stable and 4.6.1.rc1; not reproducible in 4.5.1 and earlier.

Relevant Sky3D sources:
- Screen-space fog shader: `addons/sky_3d/shaders/AtmFog.gdshader`
- Fog quad mesh creation: `addons/sky_3d/src/SkyDome.gd` lines 72–87

## Expected Correct Output

With Sky3D's screen-space fog quad shader and Godot's volumetric fog both enabled, the fog should tint the sky uniformly across the view regardless of whether the camera is angled toward +Y (up) or -Y (down), matching the Godot 4.5.x behavior.

## Actual Broken Output

A discrete half-screen tint artifact appears: the fog renders correctly on one hemisphere of the view (e.g. looking -Y / down) and breaks on the other (+Y / up), producing a visible split in fog color across the frame. The split is tied to enabling both volumetric fog and the screen-space fog quad together — disabling either restores a clean frame.

## Ground Truth

This is an unresolved Godot 4.6 regression. The upstream thread does not yet contain a maintainer-authored root-cause diagnosis or a merged fix PR; the observable symptom and the localizing conditions are what upstream evidence supports.

Quoted from the linked open issue [godotengine/godot#116038](https://github.com/godotengine/godot/issues/116038):

> 4.6 broke Sky3D. Specifically, when volumetric fog is enabled and our screen space fog shader on a quad mesh is enabled, our fog only renders properly on half of the sky when looking at -Y and breaks on +Y. We have to disable either volumetric fog or our screen space fog. Same results with d3d12 or vulkan.

Further constraints from [this issue (#116040)](https://github.com/godotengine/godot/issues/116040) and the downstream [TokisanGames/Sky3D#105](https://github.com/TokisanGames/Sky3D/issues/105):

> This issue never occurred before 4.6 all earlier versions work absolutely fine

> the screen space fog shader now breaks in 4.6 and 4.6.1 rc1

What the upstream thread establishes:
1. The regression range is 4.6 stable / 4.6.1.rc1 vs. 4.5.1 and earlier — so the change is within Godot's 4.6 renderer, not in Sky3D.
2. The trigger requires **both** Godot's volumetric fog pass **and** Sky3D's screen-space fog quad (`AtmFog.gdshader` rendered on a quad created in `SkyDome.gd#L72-L87`). Disabling either eliminates the artifact.
3. The artifact is orientation-dependent (+Y vs -Y view direction), consistent with state that depends on view/projection or a screen-space pass whose inputs change when the camera rotates.
4. API-independent (reproduces on both D3D12 and Vulkan), which rules out a single-backend driver bug and points at shared Godot rendering logic.

A root cause citation (specific volumetric-fog pass change, uniform, or render target mutation) is not available in upstream at drafting time; no fix PR or maintainer comment has been posted that a verbatim quote could be drawn from. Any root-cause claim beyond the above would be speculation.

## Difficulty Rating

4/5

## Adversarial Principles

- regression_between_versions
- multi_feature_interaction
- orientation_dependent_artifact
- no_upstream_diagnosis

## How OpenGPA Helps

An agent given access to OpenGPA can diff frame-level render-pass structure between the volumetric-fog-on and volumetric-fog-off captures, inspect the screen-space fog quad draw call's bound textures and uniforms, and check which pass writes the non-tinted half of the framebuffer — surfacing the pass/state divergence that upstream has not yet characterized.

## Source

- **URL**: https://github.com/godotengine/godot/issues/116040
- **Type**: issue
- **Date**: 2026-04-20
- **Commit SHA**: (n/a)
- **Attribution**: Reported by @raj-kesh-k; linked report by @TokisanGames / @cory in godotengine/godot#116038 and TokisanGames/Sky3D#105

## Upstream Snapshot

- **Repo**: https://github.com/TokisanGames/Sky3D
- **SHA**: (auto-resolve from commit main)
- **Relevant Files**:
  - addons/sky_3d/shaders/AtmFog.gdshader
  - addons/sky_3d/shaders/SkyMaterial.gdshader
  - addons/sky_3d/src/SkyDome.gd

## Tier

snapshot

## API

opengl

## Framework

godot

## Bug Signature

```yaml
type: color_histogram_in_region
spec:
  region: upper_half_screen
  expected_dominant_rgb_approx: [204, 179, 140]
  divergence_from_lower_half_rgb_delta_min: 40
```

## Predicted OpenGPA Helpfulness

- **Verdict**: ambiguous
- **Reasoning**: The artifact is clearly visible in the framebuffer, so OpenGPA's frame-level queries (pass list, draw-call bindings, per-region pixel histograms) can isolate which pass differs between the two halves and whether the screen-space fog quad draw sees different bound resources when volumetric fog is on. However, pinpointing the actual Godot 4.6 code change requires reading the engine's renderer source; OpenGPA narrows the search to a specific pass/uniform but does not close the gap to the changed line, especially given no upstream diagnosis exists yet to validate against.

## Observed OpenGPA Helpfulness
- **Verdict**: ambiguous
- **Evidence**: validation skipped (--no-validate)
