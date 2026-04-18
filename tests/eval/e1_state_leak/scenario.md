# E1: State Leak

## Bug

`glBindTexture(GL_TEXTURE_2D, tex_blue)` is missing before the draw call for
Quad B. OpenGL retains the last-bound texture across draw calls, so Quad B
inherits Quad A's red texture.

**Location:** `e1_state_leak.c`, inside the render loop after the comment
`// Draw Quad B`.

```c
// BUG: glBindTexture(GL_TEXTURE_2D, tex_blue) is intentionally omitted here
glBindVertexArray(vao_b);
glDrawArrays(GL_TRIANGLES, 0, 6);
```

## Expected Correct Output

- Left quad: solid red (texture 1)
- Right quad: solid blue (texture 2)

## Actual Broken Output

- Left quad: solid red
- Right quad: solid red (inherits texture 1 from Quad A)

Both quads appear red. There is no error message; the app runs and exits
cleanly.

## Ground Truth Diagnosis

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

```
inspect_drawcall(draw_id=2, query="textures")
```

OpenGPA captures the full texture-unit state at the moment of each draw call.
The output for draw 2 (Quad B) would show:

```json
{
  "TEXTURE_BINDING_2D": { "id": 1, "label": "tex_red", "size": "1x1",
                          "format": "GL_RGBA", "sample": "#FF0000" }
}
```

The sampled color `#FF0000` (red) immediately reveals that tex_red is still
bound. A code-only agent would need to manually trace all `glBindTexture`
calls in order to infer the state, which is error-prone in larger codebases.
