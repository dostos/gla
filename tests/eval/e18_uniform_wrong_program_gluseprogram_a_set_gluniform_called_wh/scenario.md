# E18_UNIFORM_WRONG_PROGRAM_GLUSEPROGRAM_A_SET_GLUNIFORM_CALLED_WH: Uniform written while the wrong program is bound

## User Report
I render a dark-gray background quad and then a centered red foreground
quad on top of it. Instead, the entire framebuffer comes out red and the
foreground quad shows up black where I expect it to be red. The center
pixel reads (0,0,0,255) and the background reads (255,0,0,255) — the
opposite of what I want. There are no GL errors, both programs link, and
both color values I'm passing on the CPU side are correct. The two
fragment shaders are compiled from identical source.

## Expected Correct Output
A 400x300 framebuffer: a dark-gray background (RGB ~0.2) filling the window with a centered red (1.0, 0.0, 0.0) quad occupying roughly the middle 30% of the frame. Center pixel (200, 150) reads RGBA ≈ (255, 0, 0, 255).

## Actual Broken Output
The background quad renders red (1.0, 0.0, 0.0) — filling most of the framebuffer — and the centered quad renders black. Center pixel (200, 150) reads RGBA = (0, 0, 0, 255). Both the dominant frame color and the center-pixel color are wrong.

## Ground Truth
The foreground program's color uniform is written via `glUniform4f` while
the background program is still the currently bound program. OpenGL
routes every `glUniform*` call to whichever program `glUseProgram` last
made active, so the red value lands on the background program's `uColor`
and the foreground program's `uColor` is never written at all.

```c
glUseProgram(progBg);
glUniform4f(locBgColor, 0.2, 0.2, 0.2, 1.0);   // sets progBg.uColor to gray
glUniform4f(locFgColor, 1.0, 0.0, 0.0, 1.0);   // progBg is still bound
```

Because `progBg` and `progFg` are linked from identical source, both put
`uColor` at location 0, so `locBgColor == locFgColor == 0`. The second
`glUniform4f` overwrites `progBg.uColor` with red instead of writing
`progFg.uColor`. When the foreground draw then runs under `progFg`, its
uniform is still the link-time default `(0, 0, 0, 0)`, producing a black
quad. The fix is a missing `glUseProgram(progFg)` between the two
`glUniform4f` calls.

## Difficulty Rating
**Hard (4/5)**

The code compiles without warnings, both `glUniform4f` calls have plausible arguments, and the location integers are opaque — `locBgColor` and `locFgColor` look distinct textually even though they are the same runtime value. Nothing local to either `glUniform4f` call textually ties the location to a specific program; the binding is implicit in the preceding `glUseProgram`.

## Adversarial Principles
- **Wrong context**: `glUniform*` acts on hidden program-bind state rather than on a program argument. The defect is an *absence* — a missing `glUseProgram(progFg)` — which is much harder to spot than a wrong call.
- **Name-based ambiguity**: Both programs expose a uniform named `uColor`, and the two uniform-location values are both 0. Every local textual check — "did we query the right location?", "did we pass the right color?" — looks correct.

## How OpenGPA Helps

OpenGPA reports each draw call's bound program along with the resolved
values of that program's uniforms, so a uniform sitting at its link-time
default on one program while another program shows the value the code
intended makes the misdirected write obvious.

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
