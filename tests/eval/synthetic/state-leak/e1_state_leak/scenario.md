# E1: State Leak

## User Report

I'm drawing two textured quads side-by-side: the left quad should be red and
the right quad should be blue. Both textures upload without errors and I've
verified both texture IDs are valid (querying them returns the expected
RGBA8 / 1x1 color data). At runtime both quads render solid red — the right
one never picks up its blue texture. There are no GL errors and the program
runs and exits cleanly.

## Expected Correct Output

- Left quad: solid red (texture 1)
- Right quad: solid blue (texture 2)

## Actual Broken Output

- Left quad: solid red
- Right quad: solid red (inherits texture 1 from Quad A)

Both quads appear red. There is no error message; the app runs and exits
cleanly.

## Ground Truth

`glBindTexture(GL_TEXTURE_2D, tex_blue)` is missing before the draw call for
Quad B. OpenGL retains the last-bound texture across draw calls, so Quad B
inherits Quad A's red texture.

The GL texture unit is stateful. After binding `tex_red` for Quad A, no
subsequent `glBindTexture` is issued before Quad B's draw, so the driver
uses `tex_red` again. The fix is to insert
`glBindTexture(GL_TEXTURE_2D, tex_blue)` before `glDrawArrays` for Quad B.

## Difficulty Rating

**Easy (1/5)**

The symptom (wrong color) is obvious. However, this scenario is included
because code review alone is unreliable: the missing call is invisible rather
than incorrect — readers tend to read what they expect to be there.

## Adversarial Principles

- **Absence-of-evidence**: The bug is a missing call, not a wrong one.
  Static analysis and code search find nothing because there is nothing to
  find at the bug site.
- **Implicit state**: GL state machine semantics are not visible in the
  source; understanding the bug requires knowing that `glBindTexture` is
  persistent.

## How OpenGPA Helps

OpenGPA captures the full texture-unit state at the moment of each draw
call. Inspecting per-draw bindings would surface the actual texture object
sampled by Quad B's fragment shader, which a code-only agent must infer by
manually tracing all `glBindTexture` calls in the program.
