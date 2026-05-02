# E30_CULLING_GL_FRONT_AND_BACK_CULLED_EVERY_TRIANGLE_DISCARDED: GL_FRONT_AND_BACK culling discards every triangle

## User Report
A near-fullscreen magenta-red quad should cover most of the window over a
dark slate background. Instead the entire frame is uniformly the clear
color (~13,13,20,255) — no quad anywhere. The draw call appears to
execute, `glGetError()` returns `GL_NO_ERROR`, the shader compiles, the
vertex data is correct, and the quad is CCW with `GL_CCW` front-face
configured. Cull face is enabled.

## Expected Correct Output
A near-fullscreen magenta-red quad (RGBA ≈ `230, 51, 77, 255`) on a dark
slate background. Center pixel should read the quad color.

## Actual Broken Output
The window is uniformly filled with the clear color (RGBA ≈
`13, 13, 20, 255`). The draw call appears to execute but produces nothing;
`glGetError()` returns `GL_NO_ERROR`.

## Ground Truth
`glCullFace(GL_FRONT_AND_BACK)` is set while `GL_CULL_FACE` is enabled,
so every triangle — front-facing and back-facing alike — is discarded
before rasterization. No fragments are ever produced by the draw call.

The spec for `glCullFace` permits `GL_FRONT`, `GL_BACK`, and
`GL_FRONT_AND_BACK`. The last value is legal and silently culls every
primitive regardless of winding. The CCW quad vertices and `GL_CCW`
front-face setting look perfectly normal; there is no validation error,
no shader warning, and no visible asymmetry to tip off a reader. The
draw issues, the pipeline consumes vertices, the cull stage rejects all
six triangles' worth of primitives, and the framebuffer is left at its
clear value. Fix: change the cull mode to `GL_BACK` (or `GL_FRONT`).

## Difficulty Rating
**Medium (2/5)**

`GL_FRONT_AND_BACK` is a valid enum for `glCullFace`, so there is no
error to chase. The line reads as a reasonable "set the cull mode" call
unless the reader remembers that this particular token means "cull
everything."

## Adversarial Principles
- **Over-enabled state**: The bug comes from *too much* culling, not
  from a missing feature — an easy miss when scanning for omissions.
- **Silent nothing**: No GL error, no warning, no shader log — the only
  symptom is a frame that looks identical to a missed-clear.

## How OpenGPA Helps

OpenGPA exposes the cull mode at each draw and the count of primitives
that reached rasterization, making "submitted vertices but zero
fragments" visible without source tracing.

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
  rule: "When GL_CULL_FACE is enabled, cull_face_mode must not be GL_FRONT_AND_BACK for any draw that is expected to produce fragments."
  draw_call_index: 0
  state_key: "cull_face_mode"
  actual_value: "GL_FRONT_AND_BACK"
  expected_value_one_of: ["GL_BACK", "GL_FRONT"]
  fragments_written: 0
  primitives_submitted: 2
```
