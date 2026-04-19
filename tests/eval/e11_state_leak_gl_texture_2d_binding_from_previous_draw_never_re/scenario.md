# E11_STATE_LEAK_GL_TEXTURE_2D_BINDING_FROM_PREVIOUS_DRAW_NEVER_RE: Second mesh inherits stale GL_TEXTURE_2D from first draw

## Bug
The right quad should sample the blue texture, but it samples the red texture because no `glBindTexture` call is issued between the first and second draw. The blue texture is created but never actually bound to `GL_TEXTURE_2D` before the second `glDrawArrays`.

## Expected Correct Output
A dark background with a red quad on the left half of the window and a blue quad on the right half. The center pixel (200, 150) lies inside the right quad and should read approximately RGBA `(40, 60, 230, 255)`.

## Actual Broken Output
Both quads render red. The left quad is correctly red, and the right quad is also red. The center pixel reads approximately RGBA `(230, 40, 40, 255)` instead of blue.

## Ground Truth Diagnosis
OpenGL's texture binding is a global piece of context state: `TEXTURE_BINDING_2D` on the active texture unit stays put until the next `glBindTexture(GL_TEXTURE_2D, ...)` call. Draw 0 binds `texRed` and leaves it bound. Draw 1 reuses the attribute setup helper but never rebinds, so `TEXTURE_BINDING_2D` is still `texRed` when the second `glDrawArrays` executes. The fragment shader samples `uTex` (which maps to texture unit 0), reads red texels, and paints the right quad red. `texBlue` is created and fully initialized but never becomes the active binding.

## Difficulty Rating
**Medium (2/5)**

Nothing in the source "looks wrong" — the second draw mirrors the structure of the first, but the `glBindTexture` line that should precede it is simply absent. A reviewer scanning for malformed calls finds none; they'd have to notice a missing line from a symmetric pair.

## Adversarial Principles
- **Stale state**: The bug is state that persists across draws when the author implicitly assumed each draw would set up its own binding.
- **Absent code**: The defect is the absence of a call, not a wrong call — there is no incorrect line to highlight.
- **Implicit state machine**: GL's global binding model hides dependency on prior calls; the second draw looks self-contained but silently depends on whatever was bound earlier.

## How OpenGPA Helps

The specific query that reveals the bug:

```
inspect_drawcall(dc_id=1, include=['textures'])
```

The tool returns the bound texture objects for draw call 1. `TEXTURE_BINDING_2D` on unit 0 still points at the red texture object — the same object reported for draw call 0 — even though the second mesh was intended to use a different texture. Seeing identical texture IDs across both draws immediately flags that no rebind happened between them and points straight at the missing `glBindTexture` call.

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
  rule: "Draw call 1 binds the same GL_TEXTURE_2D object as draw call 0 despite being intended to render a different textured mesh"
  draw_call_index: 1
  state_key: TEXTURE_BINDING_2D
  expected_different_from_draw_call: 0
  observed: "TEXTURE_BINDING_2D on unit 0 is identical to draw call 0 (red texture)"
```