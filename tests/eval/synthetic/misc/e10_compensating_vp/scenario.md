# E10: Compensating View/Projection Bugs

## User Report

I'm rendering three triangles: a white one at the world origin, a red one
to the left (x=-0.5), and a green one to the right (x=+0.5). From my
default camera angle the scene looks fine — the white triangle is in the
center, depth ordering is correct, depth precision is fine. But the red
triangle shows up on the right side of the screen and the green one on the
left. They're swapped. There are no GL errors and depth/coverage all look
right; only the horizontal positions seem mirrored, but only for off-axis
content.

## Expected Output

Three triangles:
- White (center): at world x=0, appears at screen center.
- Red (left): at world x=-0.5, should appear on the **left** side of the screen.
- Green (right): at world x=+0.5, should appear on the **right** side of the screen.

## Actual Output

The white triangle renders correctly at screen center. The red and green
triangles are swapped: red appears on the **right** and green appears on the
**left**. The scene looks plausible from the default camera angle, but all
off-axis geometry is mirror-reflected.

## Ground Truth

Two independent matrix construction errors partially cancel each other:

**Bug 1 — Left-handed lookAt** (`buggy_lookat`):
The forward vector is computed as `eye - center` instead of `center - eye`,
producing a view matrix that looks in the opposite direction (+Z instead of
-Z).

**Bug 2 — Inverted depth range** (`buggy_perspective`):
The projection matrix has `m[10]` and `m[14]` negated relative to the
standard OpenGL perspective formula, inverting the NDC depth mapping.

For a camera positioned on the +Z axis looking toward the origin, the two
sign errors cancel in the depth dimension, making on-axis geometry appear
at the correct depth and position. However, the X-axis handedness is still
wrong: left-world maps to right-screen and vice versa.

| Bug | Location | Effect |
|---|---|---|
| Forward vector sign inverted | `buggy_lookat` line 3 | View looks wrong way |
| Depth range negated | `buggy_perspective` m[10], m[14] | NDC Z inverted |
| Combined | — | Depth looks OK; X is mirrored |

**Fix Bug 1**: change `float fwd[3] = { ex-cx, ey-cy, ez-cz }` to
`{ cx-ex, cy-ey, cz-ez }`.
**Fix Bug 2**: remove the negation signs from `m[10]` and `m[14]` in the
projection matrix.

## Difficulty

**Very Hard.** The scene looks correct at the default camera angle. A
developer must either move the camera or notice the left/right swap —
which may not be apparent without clearly asymmetric reference objects.
Even after noticing the swap, attributing it to a matrix handedness error
(rather than a geometry or shader bug) requires deep knowledge of the
transform pipeline. The two bugs interact, making them much harder to
isolate individually.

## Adversarial Principles

- **Compensating errors**: two independent bugs cancel in one dimension,
  producing a "mostly correct" image that masks both errors.
- **Angle-dependent symptom**: the bug is invisible from the canonical camera
  angle and only manifests at other views.
- **Deep pipeline knowledge required**: diagnosing this requires understanding
  the interaction between view and projection matrix handedness conventions.

## How OpenGPA Helps

OpenGPA exposes the raw view and projection matrices and the derived
camera basis vectors as part of per-draw state. Both errors can be read
out independently from the captured matrices, instead of being deduced
from a "mostly correct" final image.
