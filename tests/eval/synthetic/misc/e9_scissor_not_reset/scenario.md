# E9: Scissor Rect Not Reset

## User Report

I render a UI element first, then the main 3D scene. The 3D scene is
supposed to be a large blue triangle filling most of the viewport, with a
small yellow UI rectangle in the middle. Instead, the UI rectangle looks
correct but the blue triangle is clipped to a tiny rectangle in the same
area as the UI element — as if it's only rendering inside the UI's
bounding box. There are no GL errors. If I change the projection matrix
the clipped region doesn't move.

## Expected Output

A large blue triangle filling most of the 400×300 viewport, with a small
yellow UI rectangle overlaid near the center.

## Actual Output

The yellow UI element appears correctly within its scissor rect. The blue
3D triangle is clipped to the same 200×100 rectangle (x=100..300, y=100..200),
making it appear as a small coloured patch rather than a large triangle.

## Ground Truth

A UI rendering pass enables `GL_SCISSOR_TEST` with a small rectangle
(`glScissor(100, 100, 200, 100)`) to clip UI elements to a sub-region of the
viewport. The subsequent 3D scene pass omits `glDisable(GL_SCISSOR_TEST)`,
so all 3D draw calls are silently clipped to the same UI rectangle.

`GL_SCISSOR_TEST` was not disabled between the UI and 3D passes.
**Fix**: add `glDisable(GL_SCISSOR_TEST)` immediately before the 3D pass, or
save/restore scissor state across pass boundaries.

## Difficulty

**Medium.** The symptom — unexpected clipping — is visible, but the clipping
rectangle exactly matches the UI element's area, making it easy to mistake for
a viewport or projection bug. The developer must inspect render-state at the
time of the 3D draw call, not just at the start of the frame.

## Adversarial Principles

- **State leak across passes**: the bug is not in the 3D pass itself but in
  the residual state left by a preceding unrelated pass.
- **Plausible misdiagnosis**: clipping often suggests a viewport, NDC, or
  frustum error.
- **No error signal**: GL happily clips geometry; no warning is issued.

## How OpenGPA Helps

OpenGPA reports the per-draw pipeline state, including scissor test enable
and rectangle, so the residual UI scissor active during the 3D pass is
visible in a single record without manually tracing state across passes.
