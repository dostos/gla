# E29_CULLING_GLFRONTFACE_GL_CW_WAS_SET_DURING_DEBUG_AND_NEVER_RES: Leaked GL_CW winding culls all geometry

## User Report
A full-screen CCW triangle should fill the viewport bright green. Instead
the framebuffer is solid black — center pixel reads (0,0,0,255). I set
`glFrontFace(GL_CCW)` explicitly in `main` before rendering, the cull
state is the engine's standard back-face cull, and the shader / vertex
data look correct. There's a one-shot `debug_overlay_marker()` helper
called once at startup but it just writes some diagnostic markers and
shouldn't affect rendering.

## Expected Correct Output
The full-screen CCW triangle should fill the viewport with bright green. Center pixel RGBA ≈ `(51, 204, 76, 255)`.

## Actual Broken Output
The viewport stays the black clear color. Center pixel RGBA = `(0, 0, 0, 255)`.

## Ground Truth
A one-shot debug overlay helper calls `glFrontFace(GL_CW)` and never
restores `GL_CCW`. The main render path assumes CCW front-faces with
back-face culling enabled, so every subsequent CCW triangle is classified
as back-facing and culled — the framebuffer keeps the clear color.

`debug_overlay_marker()` is called once after culling state is configured.
It sets `glFrontFace(GL_CW)` but never restores `GL_CCW`. The engine's
convention is CCW + `GL_CULL_FACE`/`GL_BACK`, so with the leaked CW
setting, CCW-wound triangles are now interpreted as back-facing and
discarded by the culling stage. No draw output reaches the framebuffer.
Fix: have `debug_overlay_marker()` save/restore front-face state, or
re-issue `glFrontFace(GL_CCW)` before the main draws.

## Difficulty Rating
**Medium (3/5)**

Glancing at `main()` you see `glFrontFace(GL_CCW)` set explicitly before rendering — the state looks correct in code order. The leak comes from a helper named as a "debug overlay," easy to dismiss as benign. Nothing in the GL error stream flags this; culling silently removes primitives.

## Adversarial Principles
- **Debug state leak**: a diagnostic helper mutates global pipeline state and forgets to restore it, corrupting the render path it was meant to instrument.
- **Module boundary leak**: the winding convention is an implicit contract across modules; the helper crosses that boundary and breaks it without any compile-time or runtime signal.

## How OpenGPA Helps

OpenGPA exposes per-draw front-face and cull state, so a mismatch with
the engine's documented convention is visible directly in the draw
record.

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
  rule: "front_face must be GL_CCW when engine convention is CCW with back-face culling"
  draw_call_index: 0
  expected:
    front_face: GL_CCW
    cull_face_enabled: true
    cull_face_mode: GL_BACK
  actual:
    front_face: GL_CW
    cull_face_enabled: true
    cull_face_mode: GL_BACK
```
