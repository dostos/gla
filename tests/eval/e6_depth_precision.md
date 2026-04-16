# E6: Depth Buffer Precision

## Bug

The perspective projection matrix is constructed with `near=0.001` and
`far=100000`, yielding a near/far ratio of ~10^8. A 24-bit depth buffer
provides only ~16 million discrete depth values, so the precision available
near `z=50` is far coarser than the 0.01-unit gap between the two quads.
Both quads map to the same (or alternating) depth values, causing z-fighting.

## Expected Output

The red quad (at z=-50) should fully occlude the blue quad (at z=-50.01).
The center region of the screen should be a stable, solid red rectangle.

## Actual Output

The center region flickers between red and blue on every frame as the two
quads compete for depth ownership. The pattern is non-deterministic across
frames.

## Ground Truth Diagnosis

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

## GLA Advantage

`query_scene(camera)` immediately surfaces `near=0.001, far=100000` and can
compute the resulting depth precision at z=50 (approximately 4.8e-4 units per
LSB vs. 0.01 needed). `query_pixel` at the fighting area shows depth values
that are identical or differ by less than one depth buffer increment, making
the diagnosis unambiguous in a single query.
