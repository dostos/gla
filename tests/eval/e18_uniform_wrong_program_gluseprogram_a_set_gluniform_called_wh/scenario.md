# E18_UNIFORM_WRONG_PROGRAM_GLUSEPROGRAM_A_SET_GLUNIFORM_CALLED_WH: Uniform written while the wrong program is bound

## Bug
The foreground program's color uniform is written via `glUniform4f` while the background program is still the currently bound program. OpenGL routes every `glUniform*` call to whichever program `glUseProgram` last made active, so the red value lands on the background program's `uColor` and the foreground program's `uColor` is never written at all.

## Expected Correct Output
A 400x300 framebuffer: a dark-gray background (RGB ~0.2) filling the window with a centered red (1.0, 0.0, 0.0) quad occupying roughly the middle 30% of the frame. Center pixel (200, 150) reads RGBA ≈ (255, 0, 0, 255).

## Actual Broken Output
The background quad renders red (1.0, 0.0, 0.0) — filling most of the framebuffer — and the centered quad renders black. Center pixel (200, 150) reads RGBA = (0, 0, 0, 255). Both the dominant frame color and the center-pixel color are wrong.

## Ground Truth Diagnosis
`glUniform*` always operates on the program currently bound by `glUseProgram` — it takes no program handle. The render path does:

```c
glUseProgram(progBg);
glUniform4f(locBgColor, 0.2, 0.2, 0.2, 1.0);   // sets progBg.uColor to gray
glUniform4f(locFgColor, 1.0, 0.0, 0.0, 1.0);   // progBg is still bound
```

Because `progBg` and `progFg` are linked from identical source, both put `uColor` at location 0, so `locBgColor == locFgColor == 0`. The second `glUniform4f` overwrites `progBg.uColor` with red instead of writing `progFg.uColor`. When the foreground draw then runs under `progFg`, its uniform is still the link-time default `(0, 0, 0, 0)`, producing a black quad. The fix is a missing `gl_UseProgram(progFg)` between the two `glUniform4f` calls.

## Difficulty Rating
**Hard (4/5)**

The code compiles without warnings, both `glUniform4f` calls have plausible arguments, and the location integers are opaque — `locBgColor` and `locFgColor` look distinct textually even though they are the same runtime value. Nothing local to either `glUniform4f` call textually ties the location to a specific program; the binding is implicit in the preceding `glUseProgram`.

## Adversarial Principles
- **Wrong context**: `glUniform*` acts on hidden program-bind state rather than on a program argument. The defect is an *absence* — a missing `glUseProgram(progFg)` — which is much harder to spot than a wrong call.
- **Name-based ambiguity**: Both programs expose a uniform named `uColor`, and the two uniform-location values are both 0. Every local textual check — "did we query the right location?", "did we pass the right color?" — looks correct.

## How OpenGPA Helps

The specific query that reveals the bug:

```
inspect_drawcall(frame=1, draw_call_index=1)
```

This returns the full uniform state bound at the foreground draw call (the second `glDrawArrays`, which uses `progFg`). It reports `uColor = (0.0, 0.0, 0.0, 0.0)` — the link-time default — proving the uniform was never written under `progFg`. Running `inspect_drawcall(frame=1, draw_call_index=0)` on the background draw then shows `progBg.uColor = (1.0, 0.0, 0.0, 1.0)`, the red value that was supposed to reach the foreground — pinpointing the misdirected write.

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
  rule: "Foreground draw call bound to progFg must have uniform uColor = (1.0, 0.0, 0.0, 1.0), but was observed as the link-time default (0.0, 0.0, 0.0, 0.0) because the glUniform4f call that should have written it ran while progBg was still the bound program."
  draw_call_index: 1
  uniform_name: "uColor"
  expected_value: [1.0, 0.0, 0.0, 1.0]
  observed_value: [0.0, 0.0, 0.0, 0.0]
  tolerance: 0.01
```