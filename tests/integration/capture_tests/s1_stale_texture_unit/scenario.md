# S1: Texture Unit Cache Stale

## Bug

After a draw call that binds textures to units 0 and 1, a subsequent draw
targets the wrong texture because the texture unit binding cache is stale.
Draw 2 attempts to sample tex_A (red) from unit 0 but ends up sampling an
unexpected texture because `glActiveTexture` is not called to explicitly
reset the active unit before the second `glBindTexture`.

**Location:** `s1_stale_texture_unit.c`, inside the render loop at Draw 2.

## Problem Description (What the User Sees)

The left quad renders red as expected. The right quad, which should also be
red (using tex_A), unexpectedly samples the wrong texture due to the active
texture unit not being explicitly set before the bind. Both quads should
appear red, but the right quad may display an unexpected color depending on
which texture unit is currently active in the driver state machine.

## Source Attribution

Inspired by three.js issue #25618:
https://github.com/mrdoob/three.js/issues/25618

## Difficulty Rating

**Medium (3/5)**

The visual symptom is a wrong color on one quad. The root cause requires
understanding that `glActiveTexture` modifies a global active-unit pointer,
and that `glBindTexture` operates on the currently active unit. An agent
must trace the active-unit state across both draw calls to identify the
missing `glActiveTexture(GL_TEXTURE0)` call before Draw 2.

## Adversarial Principles

- **Implicit state**: The active texture unit is a hidden piece of GL state;
  the source shows `glBindTexture` calls that look correct in isolation.
- **Absence-of-evidence**: The bug is a missing `glActiveTexture` call, not
  an incorrect one.
- **Multi-draw interaction**: The bug only manifests across draw call
  boundaries; inspecting either draw in isolation reveals nothing wrong.

## How OpenGPA Helps

```
inspect_drawcall(draw_id=2, query="textures")
```

OpenGPA captures the full per-unit texture binding at each draw. The output
for draw 2 would show which texture object is bound to the active unit
at the moment of the draw call, immediately revealing whether tex_A or
tex_B is being sampled and on which unit:

```json
{
  "active_unit": 1,
  "TEXTURE_UNIT_0": { "id": 1, "label": "tex_a", "sample": "#FF0000" },
  "TEXTURE_UNIT_1": { "id": 2, "label": "tex_b", "sample": "#0000FF" },
  "sampled_unit": 0
}
```

The mismatch between `active_unit` and the intended bind target immediately
flags the bug. A code-only agent must manually trace every `glActiveTexture`
call across both draw calls to reconstruct the unit-pointer state.
