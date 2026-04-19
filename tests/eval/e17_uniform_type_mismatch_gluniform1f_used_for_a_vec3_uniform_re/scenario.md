# E17_UNIFORM_TYPE_MISMATCH_GLUNIFORM1F_USED_FOR_A_VEC3_UNIFORM_RE: glUniform1f on a vec3 tint uniform is silently ignored

## Bug
The code sets the `u_tint` uniform (declared `vec3` in the fragment shader) with `glUniform1f`. GL rejects the type-mismatched call with `GL_INVALID_OPERATION` and performs no update, so the uniform stays at its default `(0,0,0)` and the quad renders black instead of warm orange.

## Expected Correct Output
The 400x300 framebuffer is covered by a large quad tinted warm orange. Center pixel RGBA ≈ `(255, 140, 25, 255)` — i.e. `(1.0, 0.55, 0.10)` scaled to 8-bit.

## Actual Broken Output
The quad renders solid black. Center pixel RGBA = `(0, 0, 0, 255)`. The printed line reads `center RGBA = 0 0 0 255`.

## Ground Truth Diagnosis
`glUniform1f(loc_tint, 1.0f)` targets a uniform the shader declared as `vec3`. The GL spec requires the setter function's component count and base type to match the uniform's GLSL type; on mismatch the driver raises `GL_INVALID_OPERATION` and leaves the uniform unchanged. Because the uniform was never successfully written, it holds its default `(0,0,0)`, and the fragment shader emits `vec4(0,0,0,1)` for every fragment of the quad. The author clearly believed they were setting a red/orange tint (the `1.0f` lands in the R slot only if `glUniform3f` were used), but the silent failure produces a black quad.

## Difficulty Rating
**Moderate (3/5)**

The mistake is a one-character difference (`glUniform1f` vs `glUniform3f`) at a line that looks syntactically correct, compiles without warning, and produces no runtime log output unless the program explicitly polls `glGetError`. A reader skimming the render setup sees a tint being set and an orange rectangle being drawn — nothing jumps out.

## Adversarial Principles
- **Silent no-op**: The faulty API call generates an error flag but has no visible effect on control flow or logs, so the bug manifests only as wrong pixels downstream.
- **Type confusion**: The setter's scalar signature superficially resembles "set a single channel" and reads as plausible beside a shader the author wrote minutes ago, so code review tends to skip over it.

## How OpenGPA Helps

The specific query that reveals the bug:

```
inspect_drawcall(frame=1, draw_call_index=0)
```

The response lists the program's active uniforms with their current values. `u_tint` appears as `vec3` with value `(0.0, 0.0, 0.0)` and a note that the most recent setter call for this location was `glUniform1f` (error `GL_INVALID_OPERATION`). Seeing a vec3 uniform still at its zero default while the code "set" it immediately localizes the bug to the setter's type, not the shader or vertex data.

## Tier
core

## API
opengl

## Framework
none

## Bug Signature
```yaml
type: framebuffer_dominant_color
spec:
  expected_rgba: [0.0, 0.0, 0.0, 1.0]
  tolerance: 0.05
```