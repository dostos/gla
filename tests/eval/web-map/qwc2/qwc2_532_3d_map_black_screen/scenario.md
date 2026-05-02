# R4_3D_MAP_BLACK_SCREEN: QWC2 3D map renders a black screen

## User Report
Hi, when navigating in a 3D Map (latest version Docker images) frequently a black screen occurs. I see no related errors in the browser console, workaround is press the zoom to 3D Tiles layer button.

Some console messages (but from before the black window):

- `bootstrap:19 WARNING: Multiple instances of Three.js being imported.`
- `[.WebGL-0x40d40bb2a200] GL_INVALID_OPERATION: glDrawElements: Feedback loop formed between Framebuffer and active Texture.`

The last message occurs many times resulting in:

- `WebGL: too many errors, no more errors will be reported to the console for this context.`

Any idea?

## Expected Correct Output
The 3D map scene renders into its offscreen color target and the target is then presented to the canvas, producing the map image.

## Actual Broken Output
The canvas is black. Each `glDrawElements` call into the offscreen target is dropped by the driver with `GL_INVALID_OPERATION: Feedback loop formed between Framebuffer and active Texture`, leaving the target at its clear color or an earlier stale state, which then composites as black after passing through downstream passes that also fail the same check.

## Ground Truth
The reporter quoted the browser's own error:

> `[.WebGL-0x40d40bb2a200] GL_INVALID_OPERATION: glDrawElements: Feedback loop formed between Framebuffer and active Texture.`

Per the WebGL / OpenGL ES spec, this error is raised when a draw call would sample a texture image that is also attached to the currently-bound draw framebuffer (or a compatible read framebuffer) at an enabled attachment, because the driver cannot guarantee well-defined results. The driver turns the draw into a no-op and the attachment keeps whatever contents it had from the previous pass — most commonly the clear color (black), which is how the user sees it.

The thread on qgis/qwc2#532 does not contain a maintainer root-cause for *which* specific three.js / QWC2 code path establishes this binding — the maintainer replied only that "this will need some WebGL debugging, impossible to say at distance" and no fix commit or PR is linked. The authoritative diagnosis at the class level — a framebuffer ↔ sampler feedback loop during `glDrawElements` — is directly cited from the runtime error in the thread; the *specific* binding pair is not published upstream and is the fact OpenGPA would need to reveal.

## Difficulty Rating
3/5

## Adversarial Principles
- bind_point_collision
- silent_noop_draw
- stale_target_contents_presented

## How OpenGPA Helps
For each failing draw call, OpenGPA can list the currently-bound draw framebuffer and its color/depth attachments, plus the texture object bound to every active sampler uniform. When the set of FBO attachment texture IDs intersects the set of sampler-bound texture IDs for the same draw, OpenGPA has pinpointed the exact binding pair that is producing the feedback loop — a fact the browser's error message states as a symptom but does not attribute to a specific texture object, sampler, or draw call.

## Source
- **URL**: https://github.com/qgis/qwc2/issues/532
- **Type**: issue
- **Date**: 2026-04-20
- **Commit SHA**: (n/a)
- **Attribution**: Reported on qgis/qwc2 issue tracker

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
  required_state:
    draw_framebuffer: not_zero
    color_attachment0_texture: T
    sampler_bound_texture_any_unit: T
  assertion: color_attachment0_texture == sampler_bound_texture_any_unit
  expected_gl_error: 0x0502  # GL_INVALID_OPERATION
```

## Predicted OpenGPA Helpfulness
- **Verdict**: yes
- **Reasoning**: Feedback loops are exactly the class of bug where per-draw state inspection — "what is bound to every sampler unit, and what are the current FBO attachments?" — collapses a vague "black screen + GL_INVALID_OPERATION" symptom into a named texture object that is simultaneously attached and sampled. Without that cross-reference, a developer must eyeball render-graph code; with OpenGPA the offending draw call and texture ID are a single query away.

## Observed OpenGPA Helpfulness
- **Verdict**: ambiguous
- **Evidence**: validation skipped (--no-validate)
