# E31_STENCIL_TEST_LEAKED_FROM_A_UI_PASS_MAIN_GEOMETRY_FAILS_STENC: Stencil test leaked from UI pass kills main 3D geometry

## Bug
The UI pass enables `GL_STENCIL_TEST` and leaves it bound with `glStencilFunc(GL_EQUAL, 1, 0xFF)` before the main 3D pass runs. The scene triangle is drawn into a region where stencil is 0, so every fragment fails the stencil test and nothing from the main pass reaches the framebuffer.

## Expected Correct Output
Dark blue-grey clear color (~`0.10, 0.12, 0.18`) with a red triangle centered in the frame and a small yellow/cyan HUD quad in the top-left corner. Center pixel should be red (~`242, 64, 38, 255`).

## Actual Broken Output
Only the clear color and the small HUD quad are visible. The center pixel is the clear color (`~26, 31, 46, 255`) — the main 3D triangle is completely missing.

## Ground Truth Diagnosis
The UI pass's second draw sets `glStencilFunc(GL_EQUAL, 1, 0xFF)` to restrict HUD fill to the masked region, but it neither disables `GL_STENCIL_TEST` nor restores `GL_ALWAYS` before the main geometry draw. The stencil buffer outside the HUD rectangle is still 0, so `ref=1` never equals the buffer value and every fragment of the 3D triangle is discarded. No GL error is raised; the framebuffer simply shows nothing from the scene draw.

## Difficulty Rating
**Hard (4/5)**

The UI and scene passes are structurally separated and look correct individually; the leak is a single missing `glDisable(GL_STENCIL_TEST)` call. Because stencil failure is silent and depth/color writes don't complain, code inspection has to simulate the entire state machine across both passes to catch it.

## Adversarial Principles
- **Cross-pass state leak**: The bug is not in the draw call that fails but in the absence of a state reset between two otherwise-correct passes.
- **Invisible failure mode**: Stencil rejection produces no GL error, no validation warning, and no partial geometry — just nothing, which reads as "the draw never happened" rather than "the draw was discarded."

## How OpenGPA Helps

The specific query that reveals the bug:

```
inspect_drawcall(draw_call_index=2)
```

Returns the full pipeline state for the main 3D triangle draw, including `stencil_test=GL_TRUE`, `stencil_func=GL_EQUAL`, `stencil_ref=1`, `stencil_value_mask=0xFF`. Seeing a stencil equality test active on a draw that clearly belongs to the scene pass immediately implicates stencil state leakage from the preceding UI pass.

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
  rule: "Main 3D geometry draw must not have GL_STENCIL_TEST enabled with GL_EQUAL ref=1 leaked from the UI pass."
  draw_call_index: 2
  expected:
    stencil_test: GL_FALSE
  actual:
    stencil_test: GL_TRUE
    stencil_func: GL_EQUAL
    stencil_ref: 1
    stencil_value_mask: 0xFF
```