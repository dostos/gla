# R3_MATERIAL_SHINES_THROUGH_WHEN_ZOOMING_OUT: Far geometry shines through near geometry at large view distances

## User Report
When zooming out to a certain extend the material of objects behind other objects starts to shine through. It looks very similar to the effect when faces are overlapping (faces are in the same plane).

To demonstrate this I made [a fiddle](https://jsfiddle.net/wilt/8rv8cguL/).

In this example I draw two thin boxes (thickness 1 and there is a empty space between the boxes of also 1) so the boxes are not touching eachother but the material shines through anyway.

```
// geometry with thickness 1
var geometry = new THREE.BoxGeometry(20000, 20000, 1);
```

When zooming the effect sometimes appears and sometimes disappears (it is also depending on zoom distance and the size of the screen).

I tried to play around with different material properties, but I seem to be unable to find any material setting that prevents this from happening.

Is this a bug? Or a WebGL limitation? Or a general limitation in 3D graphics? Or am I missing something and is this actually a material or renderer configuration mistake?

In my models this effect is really disturbing and ugly. Can I somehow prevent this from happening?

## Expected Correct Output
The viewer should see only the green near box; the red far box should be fully occluded by depth testing.

## Actual Broken Output
Pixels of the red far box "punch through" the green near box in a speckled/z-fighting pattern, as if the two boxes shared the same plane.

## Ground Truth
When the camera zooms out, the red (far) box visibly shines through the green (near) box even though the two boxes are separated by a 1-unit gap along Z and are not coplanar. Depending on zoom distance and window size, the artifact appears and disappears.

The projection matrix uses `zNear = 0.1` together with `zFar = 60000`. With a 24-bit depth buffer and a ratio of `zFar/zNear = 6×10⁵`, the non-linear 1/z depth mapping collapses almost all precision into the first fraction of the frustum, leaving effectively zero resolvable depth at the geometry's distance (~z = -30000 view-space). The two non-coplanar boxes map to indistinguishable depth-buffer values and z-fighting ensues. The upstream StackOverflow answer (score 7) quotes OpenGL.org directly:

> You may have configured your `zNear` and `zFar` clipping planes in a way that severely limits your depth buffer precision. Generally, this is caused by a `zNear` clipping plane value that's too close to `0.0`. As the `zNear` clipping plane is set increasingly closer to `0.0`, the effective precision of the depth buffer decreases dramatically.

The accepted fixes are raising `zNear` (e.g. to `500`) or enabling `logarithmicDepthBuffer: true`.

## Difficulty Rating
3/5

## Adversarial Principles
- depth_precision_collapse
- znear_too_small
- non_coplanar_z_fighting

## How OpenGPA Helps
Querying the projection matrix uniform via `/draw_calls/<id>/uniforms` reveals `zNear/zFar = 0.1/60000`, a 6×10⁵ ratio that — combined with a visible z-fight on non-coplanar geometry — points directly at depth-buffer precision collapse rather than a shader or blending bug.

## Source
- **URL**: https://stackoverflow.com/questions/37858464/material-shines-through-when-zooming-out-three-js-r78
- **Type**: stackoverflow
- **Date**: 2016-06-16
- **Commit SHA**: (n/a)
- **Attribution**: Reported by StackOverflow user; accepted answer citing OpenGL.org and @WestLangley

## Tier
core

## API
opengl

## Framework
none

## Bug Signature
```yaml
type: unexpected_state_in_draw
spec:
  description: >
    Projection matrix uniform encodes a znear/zfar ratio that collapses
    depth-buffer precision at the rendered geometry's distance, yielding
    z-fighting between non-coplanar draw calls.
  check:
    uniform_is_projection_matrix: true
    znear_max: 1.0
    zfar_min: 10000.0
    znear_over_zfar_ratio_max: 1.0e-4
```

## Predicted OpenGPA Helpfulness
- **Verdict**: yes
- **Reasoning**: The root cause lives in a uniform value (the projection matrix), which OpenGPA exposes verbatim per draw call. An agent comparing the near/far box draw calls can read off the znear/zfar and compute the precision-collapse ratio without guessing — the same diagnosis that normally requires reading the OpenGL.org depth-buffer precision guide.

## Observed OpenGPA Helpfulness
- **Verdict**: ambiguous
- **Evidence**: validation skipped (--no-validate)
