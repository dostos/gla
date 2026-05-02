# E20_UNIFORM_NEVER_UPLOADED_BECAUSE_GLUSEPROGRAM_WAS_CALLED_AFTER: glUniform4f called before glUseProgram

## User Report
A triangle should render bright orange (~RGBA 255,140,25,255 at the center
pixel) using a `uTint` uniform set to (1.0, 0.55, 0.1, 1.0). Instead the
triangle is invisible — the center pixel is just the clear color
(0,0,0,255). My code clearly calls `glUniform4f(locTint, 1, 0.55, 0.1, 1)`
and then `glDrawArrays`. The location is non-negative, the program links
without errors, the shader declares `uniform vec4 uTint`, and the
fragment shader uses `uTint` in its output color. No GL errors are
printed.

## Expected Correct Output
Center pixel should be a bright orange: RGBA ≈ `(255, 140, 25, 255)` — corresponding to `uTint = (1.0, 0.55, 0.1, 1.0)`.

## Actual Broken Output
Center pixel is fully transparent black: RGBA = `(0, 0, 0, 0)` rendered into the framebuffer. Because the default clear is opaque black, the final on-screen pixel is `(0, 0, 0, 255)` — the triangle is invisible against the background.

## Ground Truth
`glUniform4f` is called before `glUseProgram`, so the tint value targets
whatever program was previously bound (program 0 here) rather than the
intended program. The intended program's `uTint` uniform keeps its
default value of `(0, 0, 0, 0)`.

In `setup_tint_and_draw`, the author wrote:

```c
pglUniform4f(locTint, 1.0f, 0.55f, 0.1f, 1.0f);   // no program bound yet!
pglUseProgram(prog);
glDrawArrays(...);
```

`glUniform*` uploads to the *currently bound* program. At the moment of
`glUniform4f`, no program is active (or a different one is), so the
value silently never reaches `prog`'s uniform storage. When
`glUseProgram(prog)` then binds `prog`, its `uTint` is still at the
link-time default of all zeros. The draw call proceeds with `uTint =
(0,0,0,0)`. Fix: swap the order so `glUseProgram(prog)` precedes
`glUniform4f`.

## Difficulty Rating
**Medium (3/5)**

The two lines are adjacent and both reference the same `locTint`/`prog`, so a reader scanning the function sees "uniform set, program used, draw issued" and assumes correctness. The line order looks like a harmless stylistic choice.

## Adversarial Principles
- **Out-of-order ops**: The required precondition (program must be active) is invisible in the local code — it depends on GL's hidden "current program" state at the moment of the call.
- **Silent no-op**: GL does not error when you call `glUniform` with no matching program; it either errors invisibly (GL_INVALID_OPERATION if no program is bound) or writes to the wrong program's storage. Either way, the visible symptom is "uniform stuck at default", not a crash.

## How OpenGPA Helps

OpenGPA's per-draw record shows the bound program and the resolved
uniform values at draw time, so a uniform sitting at its link-time
default on the active program — despite a CPU-side write — points
straight at a program-binding ordering issue.

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
  rule: "uniform 'uTint' on the active program must equal (1.0, 0.55, 0.1, 1.0) at draw time, not its default (0,0,0,0)"
  draw_call_index: 0
  uniform_name: "uTint"
  expected_value: [1.0, 0.55, 0.1, 1.0]
  observed_value: [0.0, 0.0, 0.0, 0.0]
  tolerance: 0.02
```
