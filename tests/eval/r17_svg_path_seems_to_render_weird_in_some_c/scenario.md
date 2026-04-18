# R17_SVG_PATH_SEEMS_TO_RENDER_WEIRD_IN_SOME_C: Coplanar quads z-fight at shared depth

## Bug
A foreground "SVG shape" quad and a background "ocean" quad are submitted at the same Z. Both pass the depth test against each other unpredictably, so fragments from the far quad leak through the near quad in a speckled pattern instead of the near quad cleanly occluding the far one.

## Expected Correct Output
The center region should show a solid red shape sitting cleanly on top of the dark teal ocean, with the ocean filling only the surrounding frame.

## Actual Broken Output
The shape region shows an unstable mix of red and dark teal: depth values are mathematically equal, so `GL_LESS` rejects some shape fragments and the ocean bleeds through, producing the "glitches on the shape" the reporter observed.

## Ground Truth Diagnosis
The water plane and the extruded SVG shape occupy the same plane in world space, so at rasterization their depth values collide and the depth test is effectively a tie-break. The maintainer diagnoses this directly:

> The z-fighting potentially occurs since the water and the shape are coincident (meaning they lie in the same XZ plane). Lowering the height of the water mesh should fix that.

The reporter confirmed the fix empirically by offsetting the shape along Z:

> The bigger the z translation is, the less troubles i have. [...] With 100 units, it seems to be 'fine'.

## Difficulty Rating
2/5

## Adversarial Principles
- coplanar_depth_tie
- shared_plane_two_meshes
- visually_subtle_root_cause

## How OpenGPA Helps
A query over the draw calls targeting the center fragment would expose two draw calls writing to the same pixel with identical NDC `z` values. Surfacing the per-draw depth (or the overlap of the two bounding boxes on the depth axis) makes the coplanarity obvious where the pixel color alone only shows "speckle".

## Source
- **URL**: https://github.com/mrdoob/three.js/issues/25936
- **Type**: issue
- **Date**: 2023-04-25
- **Commit SHA**: (n/a)
- **Attribution**: Reported by upstream user; diagnosed by three.js maintainer Mugen87

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
  region: center
  region_bounds: [192, 192, 320, 320]
  expected_dominant_color: [229, 25, 25]
  tolerance: 40
  min_dominant_fraction: 0.9
  failure_mode: mixed_with_background
  background_color: [0, 30, 15]
```

## Predicted OpenGPA Helpfulness
- **Verdict**: yes
- **Reasoning**: Z-fighting between two specific draws is a structural fact (two draw calls, equal depth in the overlapping region) that an OpenGPA query over per-draw depth ranges or per-pixel draw-call attribution exposes directly, whereas staring at the framebuffer only shows noise.

## Observed OpenGPA Helpfulness
- **Verdict**: ambiguous
- **Evidence**: validation skipped (--no-validate)
