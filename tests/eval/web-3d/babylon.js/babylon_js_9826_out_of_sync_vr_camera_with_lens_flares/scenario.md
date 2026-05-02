# R200: Out of sync VR camera with lens flares

## User Report
In VR (Oculus Quest 2), lens flares appear at the wrong position for each eye. The flare is rendered to both rig cameras, but each eye sees it offset incorrectly — it feels very odd in the headset because each eye sees the flare in a different place relative to the scene.

**Repro:** https://playground.babylonjs.com/#ZEB7H6#28

**Expected:** Lens flares should appear consistently anchored to the light source for both eyes when viewed in VR.

**Actual:** Lens flares render to both eyes but their screen-space positions are computed per-rig-camera, so the flare is misaligned between the left and right eye views.

**Device:** Oculus Quest 2

**Screenshot:** https://aws1.discourse-cdn.com/business7/uploads/babylonjs/optimized/2X/0/0edfcc03e06a676912a81bd3fa3fe84ec97e5d51_2_657x500.jpeg

## Expected Correct Output
Lens flares should appear at a consistent world-anchored position when viewed through a VR headset, with both eyes seeing the flare correctly aligned with its light source.

## Actual Broken Output
Each eye sees the lens flare at a different screen-space location, producing a jarring stereoscopic mismatch — the flare appears "out of sync" between the two eye views.

## Ground Truth
The maintainer diagnosed this as a camera-selection bug in the lens flare system: screen-space positions are computed using the per-rig camera (one per eye) instead of the shared XR/parent camera. As @RaananW wrote:

> The camera that should be used to calculate the lens flare's positions is the xr camera and not the rig camera. The rig camera should only render.

> each camera has a different position and rotation, so the lens flare is positioned incorrectly when viewed in a headset (each eye sees something else, it feels very odd)

The fix is gated on broader WebXR Layers API support (linked issue #10588 — "[XR] Introduce support for WebXR Layer API"). The issue was closed as inactive without a standalone fix PR; resolution is folded into the larger Layers feature integration. See https://github.com/BabylonJS/Babylon.js/issues/9826.

## Fix
```yaml
fix_pr_url: https://github.com/BabylonJS/Babylon.js/issues/9826
fix_sha: (auto-resolve from PR #10588)
fix_parent_sha: (auto-resolve from PR #10588)
bug_class: legacy
framework: babylon.js
framework_version: 4.2
files: []
change_summary: >
  Fix PR not resolvable from the issue thread alone — issue closed as inactive
  with resolution deferred to the broader WebXR Layers API integration
  (linked #10588). Scenario retained as a legacy bug-pattern reference for
  per-rig-camera vs shared-XR-camera coordinate selection in post-processing
  effects.
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
- per-eye-stereoscopic-mismatch-not-visible-in-mono-capture
- root-cause-is-wrong-coordinate-frame-selection

## How OpenGPA Helps
A `gpa trace` capture across consecutive frames in VR mode would show two draw calls per lens flare (one per rig camera) with differing view matrices — the agent could query `/draw_calls/<id>/uniforms` to compare the projection-space positions used for each eye and observe they are computed from the rig camera's view matrix rather than the parent XR camera's. The captured per-eye uniform divergence is the literal breadcrumb pointing at "wrong camera used for lens-flare position math."

## Source
- **URL**: https://github.com/BabylonJS/Babylon.js/issues/9826
- **Type**: issue
- **Date**: 2021-01-22
- **Commit SHA**: (unresolved — deferred to #10588)
- **Attribution**: Reported by community user; diagnosed by @RaananW (Babylon.js maintainer).

## Tier
maintainer-framing

## API
opengl

## Framework
babylon.js

## Bug Signature
```yaml
type: code_location
spec:
  expected_files:
    - src/LensFlares/lensFlareSystem.ts
  fix_commit: (unresolved)
```

## Predicted OpenGPA Helpfulness
- **Verdict**: partial
- **Reasoning**: GPA can capture the per-eye draw calls and reveal that the lens flare's projected position is computed against the rig-camera view matrix (the literal symptom), which strongly hints at the camera-selection root cause. However, locating the actual fix file requires source navigation through Babylon.js's lens flare system, and the issue lacks a concrete fix PR — so GPA helps surface the diagnosis but cannot point at the specific patched lines.