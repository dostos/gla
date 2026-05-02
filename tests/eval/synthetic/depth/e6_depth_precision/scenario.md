# E6: Depth Buffer Precision

## User Report

I have two quads positioned very close together near the middle of my scene
(roughly z=-50 and z=-50.01). The nearer one should fully occlude the
further one, but instead the central screen region flickers between the
two colors every frame in a non-deterministic pattern. The geometry is
stable on the CPU side — I've printed the vertex positions across frames
and they don't move. The shader compiles, depth testing is enabled, and
nothing about the matrices or vertex data appears to change frame to frame.

## Expected Output

The red quad (at z=-50) should fully occlude the blue quad (at z=-50.01).
The center region of the screen should be a stable, solid red rectangle.

## Actual Output

The center region flickers between red and blue on every frame as the two
quads compete for depth ownership. The pattern is non-deterministic across
frames.

## Ground Truth

The perspective projection matrix is constructed with `near=0.001` and
`far=100000`, yielding a near/far ratio of ~10^8. A 24-bit depth buffer
provides only ~16 million discrete depth values, so the precision available
near `z=50` is far coarser than the 0.01-unit gap between the two quads.
Both quads map to the same (or alternating) depth values, causing z-fighting.

The near/far ratio destroys depth precision for mid-to-far geometry.
**Fix**: use a near value of at least `0.1` (ratio 1e6) or ideally `1.0`
(ratio 1e5) to restore adequate depth resolution at z=50.

| Property | Buggy value | Correct value |
|---|---|---|
| near | 0.001 | 0.1 – 1.0 |
| far | 100000 | 1000 (if scene allows) |
| near/far ratio | ~10^8 | ≤ 10^5 |

## Difficulty

**Hard.** The symptom (flickering geometry) is visible, but the cause is
invisible from code inspection alone — the near/far values look plausible in
isolation. A developer without depth-precision knowledge may waste hours
chasing floating-point rounding bugs in the geometry or transform code.

## Adversarial Principles

- **Single-value parameter bug**: the two bugged values each look
  individually reasonable (a very small near for fine objects; a very large
  far for a large world).
- **Non-deterministic symptom**: flickering appears random, obscuring the
  root cause.
- **No compile/runtime error**: the shader and geometry compile cleanly.

## How OpenGPA Helps

OpenGPA exposes the camera's projection parameters and per-pixel depth
buffer values, so the precision available at the fighting region can be
read directly rather than inferred from the matrix on the CPU side.
