# E25_GLDEPTHRANGE_SET_TO_1_0_BUT_DEPTH_TEST_IS_GL_LESS_NOTHING_VI: Inverted depth range with GL_LESS leaves window empty

## User Report
I'm trying out a reverse-Z setup for better depth precision. I draw a
red-orange quad covering most of the window, but the entire framebuffer
just shows the dark blue-gray clear color — the quad is completely
invisible. `glReadPixels` at the center reads roughly `25 31 46 255`
(the clear color), not the orange I expect. The shader compiles, the
draw issues, no GL errors are raised. The geometry is in front of the
camera and would render correctly with my old (standard) depth setup.

## Expected Correct Output
A red-orange quad (≈ RGBA `(235, 77, 56, 255)`) covering most of the 400×300 window, on a dark blue-gray background.

## Actual Broken Output
The entire window is the dark blue-gray clear color. `glReadPixels` at the center prints roughly `center RGBA = 25 31 46 255` — the quad is entirely missing.

## Ground Truth
The renderer enables a reverse-Z configuration (`glClearDepth(0.0)` +
`glDepthRange(1.0, 0.0)`) but leaves `glDepthFunc` at the default
`GL_LESS`. Every post-transform fragment depth lands in `[0,1]` and is
never less than the cleared value `0.0`, so every fragment is rejected
and only the clear color ever reaches the framebuffer.

Two of the three required reverse-Z state changes are applied correctly,
but the depth comparison function is not flipped. With `glDepthRange(1, 0)`
the NDC-to-window-depth mapping is `depth = 0.5 - 0.5 * z_ndc`, which
still lies in `[0,1]`. The depth buffer is cleared to `0.0`, and `GL_LESS`
requires new fragments to be strictly less than the buffered value. No
fragment depth is less than `0.0`, so the depth test rejects everything.
Switching to `GL_GREATER` (or reverting `glClearDepth` and `glDepthRange`
to their defaults) restores visibility.

## Difficulty Rating
**Hard (4/5)**

All three reverse-Z signals are adjacent in the source and read as an intentional, coherent optimization. The missing `glDepthFunc(GL_GREATER)` is a silent omission; no call is "wrong" in isolation — they are only wrong as a set.

## Adversarial Principles
- **Inverted range**: `glDepthRange(1.0, 0.0)` is legal and common in reverse-Z pipelines, so its presence on its own does not look suspicious.
- **Compensating errors**: The pairing of `glClearDepth(0.0)` with the inverted range reinforces the impression that a coherent reverse-Z regime is in force, masking the one state that was forgotten.

## How OpenGPA Helps

OpenGPA returns the full depth-test configuration (range, clear value,
function) together as a single snapshot, so contradictory combinations
across the three knobs are visible at a glance.

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
  rule: "glDepthRange=[1.0, 0.0] with glClearDepth=0.0 is inconsistent with glDepthFunc=GL_LESS; all fragment depths (in [0,1]) fail the test against the cleared 0.0 depth buffer, so no draw calls produce visible output."
  draw_call_index: 0
  observed:
    depth_func: GL_LESS
    depth_range: [1.0, 0.0]
    clear_depth: 0.0
  expected:
    depth_func: GL_GREATER
```
