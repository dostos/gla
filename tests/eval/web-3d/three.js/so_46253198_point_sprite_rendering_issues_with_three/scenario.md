# R22: Point sprite rendering issues with three.js

## User Report
I'm currently working an a project which will visualize data on browser by
rendering excessive amounts of animated stroked circles. I started evaluating
3D libraries and ended up trying to create a proof of concept application with
three.js. It is capable of animating and rendering up to 150 000 point sprites
at 60 fps on my 1440p monitor. Everything looks great until you start looking
at the details. It has two rendering issues:

1. It creates strange horizontal lines even when you turn animation off.
2. When you turn the camera, transparent areas of overlapping point sprites
   will show the background instead of underlying point sprites.

Here is the proof of concept application: https://jsfiddle.net/tcpvfbsd/1/

```js
var pointsAmount = 100000;
// ... build BufferGeometry with positions, rotations
var material = new THREE.PointsMaterial({
  size: 5,
  transparent: true,
  map: texture
});
points = new THREE.Points(geometry, material);
// In animate(): every sprite has its y locked to 1
position.setY(i, 1);
```

Best way to see the issues is to wait couple of seconds for the point sprites
to spread across the area, use the speed control on top right corner to pause
animation and then use the mouse's left button to turn and rotate the camera.

## Expected Correct Output
A dense, uniform mat of semi-transparent orange point sprites covering the
y=1 plane, with smoothly overlapping circles wherever they coincide.

## Actual Broken Output
Streaks of horizontal lines where the background shows through the cloud,
and square/round "bite" holes where one sprite occludes sprites that should
be visible behind it — background pixels bleed through instead.

## Ground Truth
Two separate depth/blend bugs, both caused by the default `THREE.Points`
transparent path that the upstream snippet uses:

1. **Z-fighting of coplanar sprites.** All point positions are set to
   `position.setY(i, 1)` — identical y for every sprite. Their post-projection
   depths are equal (up to floating-point rasterization noise), so which
   sprite "wins" the depth test varies per-pixel in a pattern that correlates
   with scanline order, producing the horizontal banding.

2. **Transparent fringe writes depth.** The sprite texture has a soft alpha
   fringe. With `transparent: true` and `depthWrite` left on (the default),
   the near-zero-alpha fringe pixels still pass the alpha blend stage and
   **write depth**. A later-drawn sprite behind that fringe then fails its
   depth test and is discarded, so the blended result at that pixel is the
   original background — the "holes" the asker sees.

The accepted (self) answer on the upstream thread confirms exactly this
remediation sequence:
> Using alphaTest with value 0.5 clipped the corners off the circles without
> affecting the rendering of other circles
> Setting transparent value to false removed the buggy fade effect which came
> after setting alphaTest to 0.5
> Randomizing the position on y axis by 0.01 units removed the strange
> horizontal lines

The `alphaTest=0.5` change uses `discard` so the transparent fringe never
writes depth (fixes bleed-through). The y jitter breaks the exact coplanarity
(fixes banding). Both workarounds are classic symptoms of this exact
depth-write-with-transparent-blend + coplanar-fragments pair.

## Difficulty Rating
3/5

## Adversarial Principles
- coplanar-fragments-zfight
- transparent-depth-write-occludes-later-draws
- symptom-at-framebuffer-requires-pipeline-state-inspection

## How OpenGPA Helps
An agent inspecting the draw call sees `GL_DEPTH_TEST=ON`, `DepthMask=TRUE`,
`GL_BLEND=ON` with `SRC_ALPHA/ONE_MINUS_SRC_ALPHA`, and a single
`glDrawArrays(GL_POINTS, 0, N)` with all vertices having the same Y component
— the signature of the transparent-with-depth-write anti-pattern that
directly explains both artifacts.

## Source
- **URL**: https://stackoverflow.com/questions/46253198/point-sprite-rendering-issues-with-three-js
- **Type**: stackoverflow
- **Date**: 2017-09-17
- **Commit SHA**: (n/a)
- **Attribution**: Reported and self-answered by the OP on Stack Overflow

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
  draw_call_kind: POINTS
  required_state:
    GL_DEPTH_TEST: true
    GL_DEPTH_WRITEMASK: true
    GL_BLEND: true
    blend_src_rgb: GL_SRC_ALPHA
    blend_dst_rgb: GL_ONE_MINUS_SRC_ALPHA
  vertex_invariant:
    attribute: position
    component: y
    all_equal: true
```

## Predicted OpenGPA Helpfulness
- **Verdict**: yes
- **Reasoning**: Raw pipeline state (depth-write + alpha-blend) and vertex
  buffer inspection (all y components equal) together pinpoint both failure
  modes. Neither symptom is recoverable from a framebuffer screenshot alone,
  but both are obvious from one draw-call overview query.

## Observed OpenGPA Helpfulness
- **Verdict**: ambiguous
- **Evidence**: validation skipped (--no-validate)
