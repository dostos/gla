# R15: UnrealBloomPass destroys transparent background

## User Report
Trying to use the transparent background with some post effect like the Unreal Bloom, SMAA and Tonemapping provided in the examples but it seems to break the transparency from my render.

```
renderer = new THREE.WebGLRenderer({ canvas, alpha: true });
renderer.setClearColor(0xFF0000, 0);

composer = new EffectComposer(renderer);
composer.addPass(new RenderPass(scene, camera));

// Bloom pass
canvasSize = new THREE.Vector2(canvas.width, canvas.height);
pass = new UnrealBloomPass(canvasSize, strength, radius, threshhold);
composer.addPass(pass);

// SMAA pass
size = canvasSize.multiplyScalar(this.renderer.getPixelRatio());
pass = new SMAAPass(size.x, size.y);
pass.renderToScreen = true
composer.addPass(pass);

// Tonemapping
renderer.toneMappingExposure = exposure;
renderer.toneMappingWhitePoint = whitePoint;
renderer.toneMapping = type;

composer.render();
```

If I deactivate the bloom pass I get a correct transparent background but when activated, I obtain a black background. I looked at the sources and it seems that it should correctly handle alpha texture channel as the format is set correctly to `THREE.RGBAFormat`.

**Edit**: After some research, I found where does this comes from. It comes from `getSeperableBlurMaterial` in *js\postprocessing\UnrealBloomPass.js*.

The fragment's alpha channel is always set to 1.0 which results in a complete removal of the previous alpha values when doing the additive blending at the end.

The cool thing would be to find a proper way to apply the alpha inside the Gaussian blur. Any idea how?

## Expected Correct Output
After compositing the bloom contribution, the framebuffer alpha in pixels outside the glow should remain 0 (fully transparent), matching the scene's clear alpha.

## Actual Broken Output
The framebuffer alpha is saturated to 1.0 across the entire image after the bloom pass runs, so the "transparent" background renders as solid black once the canvas is composited with the page behind it.

## Ground Truth
Enabling `UnrealBloomPass` on a `WebGLRenderer` created with `alpha: true` and a fully-transparent clear color produces an opaque black background. Disabling the bloom pass restores correct transparency.

The separable gaussian blur material used inside `UnrealBloomPass` (returned by `getSeperableBlurMaterial` in `UnrealBloomPass.js`) writes `gl_FragColor = vec4(diffuseSum, 1.0)` — the alpha channel is hardcoded to 1.0. When this blurred RGBA8 texture is additively composited over the cleared default framebuffer, the destination alpha is blown out to 1.0 everywhere the blur kernel touched, which is the entire screen for any non-zero radius. The reporter traced the issue themselves:

> It comes from `getSeperableBlurMaterial` in js\postprocessing\UnrealBloomPass.js. The fragment's alpha channel is always set to 1.0 which results in a complete removal of the previous alpha values when doing the additive blending at the end.

The accepted fix (see https://github.com/mrdoob/three.js/issues/14104) computes a weighted alpha sum alongside the RGB sum and writes `vec4(diffuseSum, alphaSum)` so transparent regions of the source texture stay transparent after the blur.

## Difficulty Rating
4/5

## Adversarial Principles
- shader_output_channel_hardcoded
- diagnosis_requires_shader_source_reading
- bug_invisible_on_opaque_scene

## How OpenGPA Helps
Querying the bloom blur pass's fragment shader source via `/api/v1/draw_calls/<id>/shaders` reveals the `vec4(..., 1.0)` literal at the output, which directly identifies why destination alpha is saturating. `/api/v1/frames/<id>/pixel` confirms that the default-framebuffer alpha becomes 255 outside the glow even though the scene-pass FBO had alpha=0 there.

## Source
- **URL**: https://stackoverflow.com/questions/50444687/post-effects-and-transparent-background-in-three-js
- **Type**: stackoverflow
- **Date**: 2018-05-21
- **Commit SHA**: (n/a)
- **Attribution**: Reported by Stack Overflow user; fix discussion at three.js issue #14104

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
  region: full_frame
  expected_alpha_max: 10
  actual_alpha_min: 240
  note: "Default framebuffer alpha should remain near 0 outside the glow region but is saturated to 255 everywhere by the buggy blur output."
```

## Predicted OpenGPA Helpfulness
- **Verdict**: yes
- **Reasoning**: The root cause is literally a constant in shader source. OpenGPA's shader-source and per-draw-call output-FBO inspection expose both the constant and its effect on destination alpha, which is exactly what the human debugger had to dig up manually.

## Observed OpenGPA Helpfulness
- **Verdict**: ambiguous
- **Evidence**: validation skipped (--no-validate)
