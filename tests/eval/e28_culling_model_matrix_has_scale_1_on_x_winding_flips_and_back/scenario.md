# E28_CULLING_MODEL_MATRIX_HAS_SCALE_1_ON_X_WINDING_FLIPS_AND_BACK: Negative X scale silently inverts winding under GL_BACK culling

## User Report
I want to render a horizontally mirrored orange quad in the center of the
window — the model matrix includes a `scale(-1, 1, 1)` so the texture
appears flipped. Standard back-face culling is enabled, the geometry is
CCW, and viewProj is correct (the same matrices render the un-mirrored
version fine). Instead the entire frame is just the dark blue-grey clear
color — the quad is invisible. No GL errors, no shader warnings, the
draw call issues.

## Expected Correct Output
A mirrored orange quad (RGB ≈ 1.0, 0.5, 0.2) covering the center of the 400×300 framebuffer. Center pixel (200,150) RGBA ≈ `255 128 51 255`.

## Actual Broken Output
Only the clear color is visible. Center pixel RGBA ≈ `13 18 26 255` (the dark blue-grey clear).

## Ground Truth
The model matrix contains a `scale(-1, 1, 1)` (a horizontal mirror). Its
determinant is negative, which flips the effective triangle winding in
clip space. With `GL_CULL_FACE` enabled and `glCullFace(GL_BACK)` /
`glFrontFace(GL_CCW)`, every triangle of the quad is now classified as
back-facing and culled — nothing is drawn.

`glFrontFace(GL_CCW)` classifies front faces by the sign of the signed
area of the post-transform triangle in window space. An odd number of
axis flips (here, one: X) in the model matrix negates that signed area,
so CCW source triangles become CW after transform. Combined with
`glCullFace(GL_BACK)`, OpenGL discards them. The vertex data, shader,
viewport, and viewProj are all correct; only the composition of a
negative-determinant model matrix with back-face culling causes the empty
frame. The fix is either `glFrontFace(GL_CW)` for mirrored instances,
disabling culling, or absorbing the mirror into texture coordinates
instead of geometry.

## Difficulty Rating
**Hard (4/5)**

The source looks entirely reasonable: a mirror transform, standard culling, CCW winding — each setting is defensible in isolation. Nothing in the code path produces a warning, an error, or a shader log, and there is no obvious "missing draw" to grep for because `glDrawArrays` *is* called.

## Adversarial Principles
- **Hidden determinant flip**: The defect is a property of the 4×4 matrix's determinant sign, not of any single call or parameter visible at the draw site.
- **Matrix composition subtlety**: Reading the model construction (`scale(-1,1,1)`) in isolation does not suggest a culling interaction; the bug only emerges when combined with fixed-function culling state set far from the matrix code.

## How OpenGPA Helps

OpenGPA captures the bound model matrix and the active cull state per
draw, so a negative-determinant transform colliding with back-face
culling is observable in a single record (along with the count of
primitives that survived to rasterization).

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
  rule: "model matrix with negative determinant combined with GL_CULL_FACE=GL_BACK and GL_FRONT_FACE=GL_CCW causes all triangles to be culled"
  draw_call_index: 0
  model_matrix_determinant_sign: negative
  cull_face: GL_BACK
  front_face: GL_CCW
  expected_rasterized_primitives_gt: 0
  actual_rasterized_primitives: 0
```
