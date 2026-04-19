# E19_UNIFORM_LOCATION_1_SILENTLY_IGNORED_BECAUSE_SHADER_COMPILER: uTint uniform optimized away, glUniform3f is a no-op

## Bug
The fragment shader declares `uniform vec3 uTint` and the host sets it to
`(0.3, 0.3, 0.3)` intending to desaturate the output. But the shader's final
assignment writes `vBase` instead of the `tinted` local, so `uTint` is
unreferenced after dead-code elimination. The GLSL compiler drops it,
`glGetUniformLocation("uTint")` returns `-1`, and `glUniform3f(-1, ...)` is
a silent no-op per the GL spec.

## Expected Correct Output
The quad should render as a muted dark red — base `(0.9, 0.1, 0.1)` modulated
by the tint `(0.3, 0.3, 0.3)` — i.e. roughly `(0.27, 0.03, 0.03)` → center
pixel RGBA ≈ `69 8 8 255`.

## Actual Broken Output
The quad renders as full-intensity red `(0.9, 0.1, 0.1, 1.0)` → center pixel
RGBA = `230 26 26 255`. The tint has no effect.

## Ground Truth Diagnosis
The fragment shader's `tinted` local is computed but never consumed — the
output write `gl_FragColor = vec4(vBase, 1.0)` ignores it. GLSL compilers
aggressively eliminate unreferenced uniforms: if no active code path feeds
them into the output, they're pruned from the linked program. The pruned
uniform has no location, so `glGetUniformLocation` returns `-1`. All
subsequent `glUniform*(-1, ...)` calls are valid GL (not an error) but do
nothing. The author sees their `glUniform3f` call succeed and assumes the
tint is applied; in reality the GPU never saw the value.

## Difficulty Rating
**Medium (2/5)**

The host code looks textbook-correct and the shader declares the uniform
that host code sets. The defect is a one-character mixup in the shader's
final line (`vBase` vs `tinted`) that silently cascades into the compiler
stripping the uniform entirely.

## Adversarial Principles
- **Silent no-op**: `glUniform3f(-1, ...)` is not a GL error — no `GL_INVALID_OPERATION`, no debug message, no indication at runtime that the call did nothing.
- **Dead-code elimination**: The uniform is syntactically declared and syntactically referenced (`vBase * uTint` computes `tinted`), so a reader skimming the shader sees nothing wrong. Only end-to-end dataflow analysis reveals it's dead.

## How OpenGPA Helps

The specific query that reveals the bug:

```
inspect_drawcall(frame=1, draw_index=0)
```

The returned drawcall record lists program uniforms with their resolved
locations. `uTint` appears with `uniform_location: -1`, immediately flagging
that every `glUniform3f` write to it was discarded by the driver. That one
field collapses the entire diagnosis: the tint host-side value was never
bound, because the linker removed the uniform.

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
  rule: "Uniform 'uTint' has location -1 in the linked program, indicating the GLSL compiler eliminated it; glUniform3f writes to it are silent no-ops."
  draw_call_index: 0
  uniform_name: uTint
  expected_location_valid: true
  actual_location: -1
```