# E2: NaN Propagation

## User Report

I'm rendering a quad with simple diffuse lighting and a directional light at
`(1, 1, 2)`. Instead of the expected gradient from ambient grey to bright
white, the entire quad renders solid near-black — only the ambient term
seems to contribute. The shader compiles cleanly, `glGetError` returns
`GL_NO_ERROR` every frame, and the light direction and color uniforms read
back correctly on the CPU side. I've tried tweaking the light direction with
no change. The object is intentionally being flattened to a shadow plane
this frame (a common pre-pass step in my engine).

## Expected Correct Output

A flat, lit quad (or cube face) showing a gradient from ambient grey to
bright white depending on the surface orientation relative to the light at
`(1, 1, 2)`.

## Actual Broken Output

The entire quad renders solid near-black (`vec3(0.05)` from the ambient
term only). No error is printed; `glGetError` returns `GL_NO_ERROR` because
NaN in a uniform is not an OpenGL error.

## Ground Truth

The model matrix is constructed with a Z scale of 0 (`model[10] = 0.0f`),
intended to flatten the object to a shadow plane. The CPU then computes
the normal matrix as `transpose(inverse(model))`. Inverting a singular
matrix (determinant = 0) produces Inf values; Inf multiplied by the zero
column then produces NaN. The NaN propagates into every fragment's normal
vector, causing `max(dot(normalize(NaN), lightDir), 0.0)` to evaluate to 0,
so all fragments receive zero diffuse contribution and render black.

`model[10] = 0` makes the matrix singular. The CPU-side normal matrix
computation divides by `det = 0`, yielding Inf in every matrix element.
The GLSL `normalize(Inf * finite)` produces NaN. `max(NaN, 0.0)` is
implementation-defined but typically 0. The fix is either:

1. Guard against zero-scale: skip the inverse when `|det| < epsilon`.
2. Use `transpose(inverse(mat3(model)))` only for non-singular matrices;
   fall back to the identity or a dedicated projection normal for flat
   objects.
3. Use a separate model matrix for the position transform vs. the normal
   transform.

## Difficulty Rating

**Hard (4/5)**

The visual symptom (black object) is ambiguous — it could be a lighting
direction bug, a wrong normal direction, a uniform not being set, a shader
typo, or NaN. The root cause requires following the data from the CPU
matrix computation into GLSL, recognising that `scale(1,1,0)` is singular,
and knowing IEEE 754 NaN semantics in GLSL.

## Adversarial Principles

- **Silent numerical failure**: NaN is not an OpenGL error; `glGetError`
  and shader compilation both succeed.
- **Causal distance**: The bug is in the CPU matrix computation; the
  symptom appears inside the GPU fragment shader after two levels of
  indirection (vertex transform then fragment lighting).
- **Plausible intent**: "Flatten a mesh for a shadow" is a legitimate use
  case, making the zero scale look intentional.

## How OpenGPA Helps

OpenGPA captures uniform values at draw time, so derived matrices that
contain Inf or NaN are visible in the per-draw snapshot rather than only
inside the shader. A code-only agent must mentally execute the matrix
inversion or add debug prints and recompile, which is significantly slower.
