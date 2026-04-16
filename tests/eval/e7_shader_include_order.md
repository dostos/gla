# E7: Shader Include Order (Wrong saturate)

## Bug

The fragment shader contains two `saturate()` helper blocks that simulate
competing include files. The active definition is:

```glsl
float saturate(float x) { return max(x, 0.0); }
```

The correct definition (clamping to `[0, 1]`) is commented out immediately
above it. Lighting code multiplies the specular term by 3.0 and then calls
`saturate()`, expecting values to be clamped to 1.0. Because the active
definition only clamps at 0, the specular channel exceeds 1.0 and writes
HDR values into the standard `[0, 1]` framebuffer, saturating at the display
stage rather than in the shader.

## Expected Output

A smoothly lit quad with diffuse + specular lighting. Highlights should be
white (1.0, 1.0, 1.0) but not blown out beyond that.

## Actual Output

The highlight region of the quad is over-bright: the white channel computes
to values around (4.0, 4.0, 4.0) internally, which clamps to solid white at
the framebuffer but loses all specular shape. The quad looks uniformly
washed out at the highlight center.

## Ground Truth Diagnosis

`saturate(x) = max(x, 0.0)` does not clamp the upper bound.
**Fix**: replace with `clamp(x, 0.0, 1.0)` (the commented-out line above).

The bug is an include-order mistake: in a real engine with a preprocessor
include system, `math_utils_v1.glsl` would be included after
`math_utils_v2.glsl`, overwriting the correct definition.

## Difficulty

**Medium-Hard.** The rendering looks "mostly right" — the object is lit and
shaped correctly. The over-brightness can be attributed to light intensity or
gamma settings. Reading the shader source requires noticing the commented-out
alternative and recognizing that `max(x, 0)` is not a complete `saturate`.

## Adversarial Principles

- **Plausible-looking code**: `max(x, 0.0)` is a recognizable idiom that is
  simply incomplete.
- **Subtle visual symptom**: Over-bright highlights are easily attributed to
  light calibration.
- **Comment noise**: The correct implementation is visibly present but marked
  as inactive, creating confusion about intent.

## GLA Advantage

`query_pixel` at the highlight area returns a raw color channel value > 1.0,
immediately indicating that shader output is exceeding the normalised range.
This directs attention to clamping logic in the fragment shader rather than
to geometry, transforms, or light position.
