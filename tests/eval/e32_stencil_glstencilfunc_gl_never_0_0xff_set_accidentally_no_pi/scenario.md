# E32_STENCIL_GLSTENCILFUNC_GL_NEVER_0_0XFF_SET_ACCIDENTALLY_NO_PI: Stencil func GL_NEVER discards every fragment

## User Report
A large orange quad should cover most of the viewport on a dark gray
background. Instead the entire window is the clear color (~26,26,26,255)
— no quad at all. The center pixel reads the clear color. `glDrawArrays`
is issued every frame, the shader compiles and links, the VBO is bound,
and `glGetError` returns `GL_NO_ERROR`. The geometry, viewport, and
matrices all look correct.

## Expected Correct Output
A large orange quad (RGBA ≈ 255, 178, 51, 255) covering most of the viewport
against a dark gray background.

## Actual Broken Output
Only the dark gray clear color is visible. The center pixel reads
RGBA ≈ 26, 26, 26, 255 — the quad is completely missing even though
`glDrawArrays` is issued every frame.

## Ground Truth
`glStencilFunc(GL_NEVER, 0, 0xFF)` is set before the fill pass, so the
stencil test always fails and no fragment ever reaches the color buffer.

Stencil testing is enabled and the active stencil function is `GL_NEVER`,
which means the stencil comparison always fails. On failure
`glStencilOp`'s `sfail` action runs (here `GL_KEEP`) and, critically,
the fragment is discarded before the color write. Every fragment of the
quad is killed by the stencil test, so the framebuffer retains the clear
color. Fix: change `GL_NEVER` to `GL_ALWAYS` (or another passing
predicate), or disable `GL_STENCIL_TEST`.

## Difficulty Rating
**Moderate (2/5)**

The `glDrawArrays` call executes, shaders compile and link, the VBO is bound,
and no GL error is raised — so the code reads as if it should draw. The
single-token swap from `GL_ALWAYS` to `GL_NEVER` is easy to gloss over when
skimming setup code.

## Adversarial Principles
- **Wrong predicate**: The comparison function is the inverse of what was
  intended — a one-token edit changes "always draw" into "never draw".
- **Total occlusion**: Because every fragment fails, the symptom is
  complete absence of geometry, which is often mistaken for a matrix,
  viewport, or culling problem rather than a stencil issue.

## How OpenGPA Helps

OpenGPA exposes the active stencil function and reference value per draw,
so a draw that submits geometry but writes no fragments while a stencil
test is active surfaces the discard cause directly.

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
  rule: "Active stencil test with stencil_func=GL_NEVER discards every fragment; the fill-pass draw should use GL_ALWAYS (or another passing predicate)."
  draw_call_index: 0
  expected_stencil_func: GL_ALWAYS
  actual_stencil_func: GL_NEVER
  stencil_ref: 0
  stencil_mask: 0xFF
  stencil_test_enabled: true
```
