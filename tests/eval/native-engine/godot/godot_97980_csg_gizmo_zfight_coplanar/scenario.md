# R22_CSG_GIZMO_ZFIGHT_COPLANAR: CSG selection gizmo Z-fights with mesh due to coplanar faces

## User Report
### Tested versions

I only testing with godot 4.3

### System information

mac os 15.0.1 Godot 4.3

### Issue description

Some materials cause graphics issue that are hard to work around.

(image attached)

### Steps to reproduce

the issues have happed when things involve transparency. In the photo included it is created with CSG volumes. When working with one the graphics issues happen. The artifacts are high frequency and hard to work with.

### Minimal reproduction project (MRP)

issue.zip (attached). Rotating around scene shows graphic issues. Could be around z fighting issues.

## Expected Correct Output
The selected face should be covered by a single solid color — the gizmo overlay — because the gizmo is intended to visibly mark the selected CSG shape. (After the fix, this is achieved by pushing the gizmo slightly toward the camera via a per-material depth offset.)

## Actual Broken Output
The face shows a high-frequency interference pattern mixing the mesh color and the gizmo color. When the camera moves, the pattern shimmers — which is what users experience as unpleasant flicker.

## Ground Truth
Two draw calls render geometry that shares identical corner positions on a single plane — the CSG mesh face and its selection/collision-debug gizmo. Both use the same depth test (`GL_LESS`) with no depth bias, so the rasterizer's per-triangle depth interpolation along different diagonal splits produces sub-ULP-scale z differences per pixel. The result is the classic Z-fighting speckle: sometimes the mesh color wins the depth test, sometimes the gizmo color wins.

The CSG selection gizmo is built from the same vertex data as the CSG mesh itself, so every gizmo face is exactly coplanar with a mesh face. With both draws using the same depth test and no depth bias, the GPU's depth interpolation — which is defined per-triangle, not per-plane — produces different per-pixel z values between the two draws whenever the triangulation differs or the rasterizer takes a different path through the two primitives. Godot maintainer `@bruvzg` diagnosed this directly in the issue thread:

> it's likely caused by selection and shape having face in the same plane (both are generated from the same data, so this is expected, we probably should add some offset to the selection).

The fix landed as PR #100211 ("Add Depth Offset property to BaseMaterial3D and fix collision shape gizmo flicker"), which adds a per-material depth offset so the gizmo's rasterized depth is pushed slightly toward the camera, breaking coplanarity and eliminating the fight. The same PR closes the consolidated issue #99184.

## Difficulty Rating
3/5

## Adversarial Principles
- coplanar_face_z_fighting
- triangulation_dependent_depth_interpolation
- hardware_deterministic_but_content_addressed_artifact

## How OpenGPA Helps
Listing the frame's draw calls shows two draws whose vertex positions span the same 4 corners on the same plane, with identical depth state (`GL_LESS`, no `glPolygonOffset`, no depth bias). That mechanical signature — "two overlapping draws on the same plane, one trying to overpaint the other without depth separation" — is the textbook coplanar Z-fighting setup. An agent looking only at a screenshot sees "shimmering" and must guess the cause; an agent with access to OpenGPA's per-draw vertex positions and depth state can name the root cause deterministically.

## Source
- **URL**: https://github.com/godotengine/godot/issues/97980
- **Type**: issue
- **Date**: 2024-10-08
- **Commit SHA**: (n/a)
- **Attribution**: Reported by @chancemcdonaldsims; diagnosed in-thread by @bruvzg; consolidated into #99184; fixed by PR #100211 (@Calinou).

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
  region: {x: 200, y: 150, w: 400, h: 300}
  note: "region lies strictly inside both coplanar quads"
  expected_single_dominant_color: {r: 0, g: 255, b: 0}
  broken_indicator:
    two_colors_present:
      - {r: 255, g: 0, b: 0}
      - {r: 0, g: 255, b: 0}
    each_fraction_min: 0.05
```

## Upstream Snapshot
- **Repo**: https://github.com/godotengine/godot
- **SHA**: e42def12d0475e34e05ffd872eb12c88e0688fbf
- **Relevant Files**:
  - editor/plugins/gizmos/csg_gizmo_plugin.cpp  # default-branch SHA at issue close; fix via PR #100211 (add depth offset); (inferred)
  - scene/resources/material.cpp
  - modules/csg/csg_shape.cpp

## Predicted OpenGPA Helpfulness
- **Verdict**: yes
- **Reasoning**: The root cause is entirely in the captured GL state — two draws with matching vertex positions, same depth function, no depth offset. OpenGPA's Tier 1 raw capture exposes exactly those facts without any heuristics, so an agent can diagnose "coplanar Z-fight, add depth offset or polygon offset" directly rather than speculating from pixels.

## Observed OpenGPA Helpfulness
- **Verdict**: ambiguous
- **Evidence**: validation skipped (--no-validate)
