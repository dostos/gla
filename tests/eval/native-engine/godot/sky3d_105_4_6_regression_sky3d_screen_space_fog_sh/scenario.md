# R27: Volumetric fog + full-screen QuadMesh screen-space fog splits screen in half

## User Report
### Tested versions

Broken in 4.6 stable.
Not fixed in 4.6.1.rc1.
4.5 and before is fine.

### System information

Godot v4.6.stable - Windows 11 - Direct3D 12 (Forward+) - dedicated NVIDIA
GeForce RTX 3070 Laptop GPU - 12th Gen Intel(R) Core(TM) i9-12900H

### Issue description

4.6 broke Sky3D. Specifically, when volumetric fog is enabled and our screen
space fog shader on a quad mesh is enabled, our fog only renders properly on
half of the sky when looking at -Y and breaks on +Y. We have to disable
either volumetric fog or our screen space fog.

Same results with d3d12 or vulkan.

Downstream issue with pictures: https://github.com/TokisanGames/Sky3D/issues/105

Screen space fog: https://github.com/TokisanGames/Sky3D/blob/main/addons/sky_3d/shaders/AtmFog.gdshader

Fog quad mesh creation: https://github.com/TokisanGames/Sky3D/blob/main/addons/sky_3d/src/SkyDome.gd#L72-L87

### Steps to reproduce

* Add Sky3D (not in asset lib) https://github.com/TokisanGames/Sky3D/
* Open the demo
* In sky3d/environment, turn on volumetric fog
* Sky3D/visibility/fog is already enabled

### Minimal reproduction project (MRP)

Open the MRP and look up and down. The WorldEnvironment is a default node
with volumetric fog enabled. _FogMeshI is the quadmesh with the screen space
shader.

## Expected Correct Output
A smooth, full-screen atmospheric fog gradient that varies continuously with
view direction, with no visible seam between the two halves of the viewport.

## Actual Broken Output
The frame shows two clearly different fog tints meeting along a straight line
through the middle of the screen. One half looks correct; the other half is
either untinted (depth read as "far") or darkly tinted (depth read as "near"),
matching the screenshots in the issue and the supersedes thread.

## Ground Truth
The bug report frames this as depth-buffer corruption rather than a shader
logic issue:

> Depth buffer appears corrupted at certain view angles when volumetric fog is enabled

— [godotengine/godot#116045](https://github.com/godotengine/godot/issues/116045),
which supersedes #116038 and adds a simpler MRP that writes raw depth to
albedo. The MRP shows the same half-screen split when volumetric fog is toggled
on, demonstrating that the artifact originates in the depth the fullscreen
QuadMesh samples, not in the Sky3D fog shader itself. Godot 4.6 introduced a
change to how the volumetric-fog pass interacts with the depth attachment used
by subsequent screen-space passes on QuadMeshes; the fullscreen QuadMesh reads
a depth value whose near/far mapping flips across a pitch-dependent boundary,
which is why the seam tracks camera orientation. The upstream ticket points to
a solution proposed in
[issue #116045 comment 3873478067](https://github.com/godotengine/godot/issues/116045#issuecomment-3873478067).

## Difficulty Rating
4/5

## Adversarial Principles
- cross-pass depth coupling (volumetric-fog pass + screen-space QuadMesh pass)
- view-direction-dependent artifact (pitch gates the seam)
- regression isolated to one engine version (4.6) across both backends
- depth attachment reused across post-process passes with subtly different
  expected near/far mapping

## How OpenGPA Helps
An agent can compare the depth texture sampled by the QuadMesh draw in the
broken frame against a known-good frame and spot the half-screen discontinuity
directly (`framebuffer_dominant_color` on the two halves, or pixel reads along
a horizontal scanline through the depth render target). Tier-1 capture exposes
the exact depth attachment bound to the screen-space fog draw, which
distinguishes "shader math is wrong" from "depth input is already split."

## Source
- **URL**: https://github.com/godotengine/godot/issues/116038
- **Type**: issue
- **Date**: 2026-04-19
- **Commit SHA**: (n/a)
- **Attribution**: Reported by Sky3D maintainers (TokisanGames); superseded by #116045

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
  region_a: { x: 0, y: 0, w: 400, h: 600 }
  region_b: { x: 400, y: 0, w: 400, h: 600 }
  expect: regions should have similar dominant color (continuous fog)
  observed: regions differ sharply, indicating half-screen depth split
```

## Upstream Snapshot
- **Repo**: https://github.com/godotengine/godot
- **SHA**: (auto-resolve from commit 4.6-stable)
- **Relevant Files**:
  - servers/rendering/renderer_rd/effects/fog.cpp
  - servers/rendering/renderer_rd/effects/fog.h
  - servers/rendering/renderer_rd/shaders/effects/volumetric_fog.glsl
  - servers/rendering/renderer_rd/forward_clustered/render_forward_clustered.cpp
  - servers/rendering/renderer_rd/storage_rd/render_buffers_rd.cpp

## Predicted OpenGPA Helpfulness
- **Verdict**: ambiguous
- **Reasoning**: OpenGPA's Tier-1 capture can clearly visualize the half-screen
  seam in the depth attachment sampled by the screen-space fog draw, which
  helps an agent localize the bug to the depth pipeline rather than the fog
  shader. However, root-causing the regression requires reading Godot's
  volumetric-fog + render-buffer bookkeeping code across several files, which
  OpenGPA does not inspect directly. The snapshot reference bridges that gap,
  but the diagnosis is genuinely engine-internal.

## Observed OpenGPA Helpfulness
- **Verdict**: ambiguous
- **Evidence**: validation skipped (--no-validate)
