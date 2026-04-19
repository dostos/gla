# E33_STENCIL_MASK_0_ON_WRITE_ATTEMPTS_TO_UPDATE_STENCIL_ARE_SILEN: Stencil writes masked off during prepass

## Bug
A lingering `glStencilMask(0x00)` left over from an earlier UI pass is still
in effect when the stencil prepass runs. `GL_REPLACE` is the stencil op, but
with the write mask at zero every bit of the update is dropped — the prepass
is a silent no-op and the stencil buffer stays all zero.

## Expected Correct Output
Blue background (0.05, 0.10, 0.45) with a red (0.95, 0.10, 0.10) square
covering the center half of the window. The center pixel (200, 150) should
read roughly `242 26 26 255`.

## Actual Broken Output
Solid blue across the entire framebuffer — no red anywhere. The center
pixel reads `13 26 115 255`.

## Ground Truth Diagnosis
Stencil updates are gated by `GL_STENCIL_WRITEMASK`. When it is 0, any
`glStencilOp` that would write (including `GL_REPLACE`) is masked off
bit-for-bit, so the stencil buffer remains at its cleared value of 0. The
subsequent masked draw uses `glStencilFunc(GL_EQUAL, 1, 0xFF)`, which fails
for every fragment, so the fullscreen red quad contributes nothing. Nothing
in the C source directly disables the prepass — the failure is purely a
piece of GL state that outlived its intended scope.

## Difficulty Rating
**Hard (4/5)**

The stencil enables, `glStencilFunc`, and `glStencilOp` calls all look
correct, and `glColorMask` is restored before the visible draw. The single
`glStencilMask(0x00)` call is visually indistinguishable from the dozens of
legitimate state-setup calls around it, and no compile/runtime error is
reported — the update simply does not happen.

## Adversarial Principles
- **Silent no-op**: `GL_REPLACE` under a zero write mask still binds, still
  executes the draw, still passes the stencil function — it just doesn't
  write. There is no GL error and nothing in the API shape suggests the
  operation was discarded.
- **Masked update**: The defect is a mask value, not a missing call. Code
  inspection sees both "write stencil 1" and "test stencil == 1" and
  reasonably assumes they will agree.

## How OpenGPA Helps

The specific query that reveals the bug:

```
inspect_drawcall(frame=1, draw_call_index=0)
```

The prepass draw call's state snapshot shows `stencil_write_mask=0x00`
alongside `stencil_op_zpass=GL_REPLACE` and `stencil_func=GL_ALWAYS`. The
combination is the smoking gun: the write path is armed but the mask blocks
the commit, so the stencil buffer never leaves its cleared state. The
masked draw that follows then fails its `EQUAL 1` test for every fragment,
exactly matching the all-blue framebuffer.

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
  rule: "stencil prepass draw has stencil_write_mask=0 while stencil_op writes REPLACE"
  draw_call_index: 0
  expected_stencil_write_mask: 0xFF
  actual_stencil_write_mask: 0x00
  stencil_op_zpass: GL_REPLACE
  stencil_func: GL_ALWAYS
  consequence_framebuffer_rgba: [0.05, 0.10, 0.45, 1.0]
  tolerance: 0.05
```