# R31_WEIRD_R164_WEBGL_RENDERER_REGRESSION_WIT: Per-frame color clear skipped, prior-frame trails persist

## User Report
### Description

After upgrading three.js from `0.163.0` to `0.164.0` or `0.164.1` one
particular `GLB` model from my library breaks the renderer when camera looks
at it, it leaves the "trail" on the screen, where only the background image
visible. I'm not sure how to describe it in a more informative way TBH, see
the screenshot and attached codepen.

### Reproduction steps

1. open this [CodePen example](https://codepen.io/Andrew-Gura-the-flexboxer/pen/ZENQpjR)
2. move camera to the left and see that lambo car can be seen without issues
3. replace `three@0.163.0` with `three@0.164.1` in HTML
4. move camera to the left again and see the issue

OR

1. add [this glb](https://gg-web-demos.guraklgames.com/assets/fly-city/lambo/body.glb) to scene
2. add some mesh behind this glb to see the bug
3. add two directional lights (optional?)
4. move camera

### Code (excerpted)

```js
const renderer = new THREE.WebGLRenderer({
  preserveDrawingBuffer: true,
  background: 0xffffff,
});
renderer.outputColorSpace = THREE.SRGBColorSpace;
renderer.shadowMap.enabled = true;
renderer.shadowMap.type = THREE.PCFSoftShadowMap;
renderer.setClearColor(0xffffff, 1);

new GLTFLoader().load(
  "https://gg-web-demos.guraklgames.com/assets/fly-city/lambo/body.glb",
  (gltf) => {
    gltf.scene.position.set(10, 0, 0);
    scene.add( gltf.scene );
  }
);

function render(time) {
  requestAnimationFrame(render);
  renderer.render(scene, camera);
}
render();
```

### Live example

[CodePen](https://codepen.io/Andrew-Gura-the-flexboxer/pen/ZENQpjR)

### Screenshots

0.163.0 — renders correctly.

0.164.0(1) — leaves trail of background pixels behind moving geometry.

### Version

r164

### Device / Browser / OS

Desktop / Chrome / Linux

## Expected Correct Output
A 256×256 frame with a white background and a single green quad on the right half. The left half should be entirely white (clear color).

## Actual Broken Output
A frame showing BOTH the red quad on the left (leaked from the previous logical frame) AND the green quad on the right. The left half contains red pixels that should have been cleared.

## Ground Truth
The upstream regression was traced to a reordering in WebGLBackground that moved the color clear to after render-list insertion, so with `preserveDrawingBuffer: true` the intended per-frame clear was effectively skipped and prior-frame pixels persisted:

> Confirmed with `git bisect`, the change in behavior was introduced in #28118.

> If I set `preserveDrawingBuffer: false`, the artifacts disappear for me. Alternatively, call `renderer.clear()` in the render loop, and the artifacts disappear.

The linked PR confirms the reordering and its intent:

> This PR splits these two background paths so the render list is complete before the transmission pass and any applicable clears happens after it.

The root cause is a framework-internal ordering issue: the GL-level symptom is simply that `glClear(GL_COLOR_BUFFER_BIT)` is not issued between frames, so the preserved drawing buffer retains prior content.

## Difficulty Rating
3/5

## Adversarial Principles
- state_leak_across_logical_frames
- missing_color_buffer_clear
- preserve_drawing_buffer_semantics

## How OpenGPA Helps
An OpenGPA query over the command stream for frame N can report that between the two logical "render" passes no `glClear` with `GL_COLOR_BUFFER_BIT` is issued, while `glDrawArrays` writes new content into the same default framebuffer — directly flagging the missing clear that causes the trails.

## Source
- **URL**: https://github.com/mrdoob/three.js/issues/28420
- **Type**: issue
- **Date**: 2024-05-18
- **Commit SHA**: (n/a)
- **Attribution**: Reported by @AndyGura; regression bisected to PR #28118

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
  region:
    x: 16
    y: 64
    width: 96
    height: 128
  expected_dominant_rgb: [255, 255, 255]
  forbidden_rgb: [255, 0, 0]
  forbidden_fraction_max: 0.01
```

## Upstream Snapshot
- **Repo**: https://github.com/mrdoob/three.js
- **SHA**: eaede05ea1aac8a047b03fef536f3aa53955539c
- **Relevant Files**:
  - src/renderers/webgl/WebGLBackground.js  # base of fix PR #28445 (clear ordering vs. transmission pass)
  - src/renderers/WebGLRenderer.js

## Predicted OpenGPA Helpfulness
- **Verdict**: yes
- **Reasoning**: The bug reduces to a missing `glClear(GL_COLOR_BUFFER_BIT)` call between two draw sequences on the default framebuffer. An OpenGPA trace of the frame makes the absence of that clear, and the persistence of the prior draw's pixels, trivially inspectable — turning an opaque "trails" symptom into an explicit state-leak diagnosis.

## Observed OpenGPA Helpfulness
- **Verdict**: ambiguous
- **Evidence**: validation skipped (--no-validate)
