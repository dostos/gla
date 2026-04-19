# R4_SVGLOADER_POINTSTOSTROKE_INCORRECT_RESUL: Bevel linejoin triangles have reversed winding and are backface-culled

## User Report
### Description

When passing a simple 3 point shape to SVGLoader pointToStroke, when linejoin is set to bevel, the resulting geometry is incorrect.

It works correctly when line join is set to miter or round

Two clues that might help
1. If I use positive y values, it renders correctly
```js
  shape.moveTo(-4, 4);
  shape.lineTo(0, 0);
  shape.lineTo(4, 4);
```
2. If I make the material DoubleSided it renders correctly

### Reproduction steps

create a 3 point line shape
getStrokeStyle passing linejoin set to 'bevek'
pass resulting shape and stroke style to pointsToStroke
render the resulting geometry to a mesh

### Code

```js
const shape = new Shape();
  shape.moveTo(-4, -4);
  shape.lineTo(0, 0);
  shape.lineTo(4, -4);

  const style = SVGLoader.getStrokeStyle(
    2,
    "black",
    "bevel",
    "square",
    undefined
  );

  const geometry = SVGLoader.pointsToStroke(shape.getPoints(), style);
  const material = new MeshBasicMaterial();
  const rect = new Mesh(geometry, material);
  scene.add(rect);
```

### Live example

https://codesandbox.io/s/three-linejoin-bevel-test-4t7ppp

### Version

156.1

### Device

Desktop

### Browser

Edge

### OS

Windows

## Expected Correct Output
The V-shape polyline rendered as a solid black stroke of uniform width, with the apex at the origin filled in cleanly — every pixel between the two offset edges is covered.

## Actual Broken Output
The two segment quads render correctly, but the triangular wedge that fills the outer bevel at the apex is missing: the region just above P1 at (0,0) that should be black stays at the clear color. When the camera is rotated the missing triangles become visible from the opposite side (they are facing backwards).

## Ground Truth
`SVGLoader.pointsToStroke` tessellates a polyline into triangles: a quad per segment plus a fill triangle at each bevel join. When `linejoin: 'bevel'` is used, the bevel-join triangle is emitted with the opposite winding order from the segment quads. Under the default single-sided material (backface culling with CCW front-face), the bevel triangles are silently culled, so the joins of the stroke appear as gaps.

The reporter observes that the missing triangles appear when the view is flipped, which indicates a winding/face-culling issue rather than missing geometry:

> When I rotate the scene (using orbit), the missing triangles are facing backwards. So likely the normal is just wrong or not being calculated.

A follow-up commenter corrects the framing from "normal" to "winding" and confirms the workaround:

> That is a winding order issue, not a normals issue. Try `material.side = DoubleSide;`

`DoubleSide` disables the cull, so both winding orders render and the gap disappears — which only makes sense if the bevel triangle is emitted with the wrong winding relative to the rest of the stroke mesh. The reporter also notes that mirroring the Y coordinates (`shape.lineTo(0,0); shape.lineTo(4,4)` etc., making the V open upward rather than downward) produces a correct result, because that flips which side of the polyline the bevel lands on and swaps the vertex index order used for the bevel fill triangle — consistent with a bevel-join construction whose emitted winding depends on the turn direction of the corner rather than on a global convention.

## Difficulty Rating
3/5

## Adversarial Principles
- silent_backface_cull
- winding_depends_on_corner_turn_direction
- side_conditional_visibility
- misattribution_to_normals

## How OpenGPA Helps
Querying the draw call reveals all 15 stroke vertices in the VBO with their positions, so the bevel triangle is present in the draw data. Cross-referencing that with the pipeline state (`GL_CULL_FACE=true`, `GL_FRONT_FACE=GL_CCW`) and computing the signed area / cross product per triangle surfaces exactly one triangle with reversed winding — the culprit. The pixel-level view alone only shows "a gap"; OpenGPA attributes the gap to a specific submitted-but-culled triangle.

## Source
- **URL**: https://github.com/mrdoob/three.js/issues/26784
- **Type**: issue
- **Date**: 2023-09-14
- **Commit SHA**: (n/a)
- **Attribution**: Reported by upstream user; winding diagnosis by community commenter

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
  region: bevel_apex
  region_bounds: [193, 200, 207, 210]
  expected_dominant_color: [0, 0, 0]
  tolerance: 40
  min_dominant_fraction: 0.6
  failure_mode: mixed_with_background
  background_color: [255, 255, 255]
```

## Upstream Snapshot
- **Repo**: https://github.com/mrdoob/three.js
- **SHA**: d9a94c7f5598a28ac6853e2eeed235157a24a653
- **Relevant Files**:
  - examples/jsm/loaders/SVGLoader.js  # base of fix PR #27121 (SVGLoader bevel winding)

## Predicted OpenGPA Helpfulness
- **Verdict**: yes
- **Reasoning**: The bug is a per-triangle winding defect inside a single draw call whose effect (silent cull) leaves no trace in the framebuffer beyond "a gap." Surfacing per-triangle signed area against the current `GL_FRONT_FACE`/`GL_CULL_FACE` pipeline state pinpoints the offending triangle index directly, which a code-only agent would have to reconstruct by tracing SVGLoader's bevel-tessellation branch and the consumer's material side setting.

## Observed OpenGPA Helpfulness
- **Verdict**: ambiguous
- **Evidence**: validation skipped (--no-validate)
