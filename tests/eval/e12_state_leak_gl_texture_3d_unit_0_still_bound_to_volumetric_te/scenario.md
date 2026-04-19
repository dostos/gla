# E12_STATE_LEAK_GL_TEXTURE_3D_UNIT_0_STILL_BOUND_TO_VOLUMETRIC_TE: Stale 3D Fog Volume Shadows Terrain Sampler

## Bug
A "volumetric fog" module binds a `GL_TEXTURE_3D` volume to texture unit 0 and
never resets state. The terrain module uploads its 2D texture to unit 1 but
calls `glUniform1i(terrain_sampler, 0)` — one off. The shader's `sampler2D`
reads from unit 0, where no 2D texture is bound, so every fragment is black.

## Expected Correct Output
Full-screen quad textured with brown terrain. Center pixel RGBA
≈ `(153, 115, 51, 255)` — i.e. normalized `(0.60, 0.45, 0.20, 1.00)`.

## Actual Broken Output
Full-screen quad is uniformly black. Center pixel RGBA = `(0, 0, 0, 255)`.

## Ground Truth Diagnosis
Texture-unit state in GL is per-target: `GL_TEXTURE_2D` and `GL_TEXTURE_3D`
each have their own binding slot on every unit. The fog module left
`TEXTURE_BINDING_3D = vol_tex` on unit 0 but nothing was ever bound to
`TEXTURE_BINDING_2D` on unit 0 — it defaults to texture name 0. When the
terrain fragment shader's `sampler2D terrain_tex` is assigned unit index 0
(instead of 1), the GL reads the default/incomplete 2D texture on unit 0 and
returns `(0, 0, 0, 1)`. The brown 2D terrain texture uploaded to unit 1 is
entirely unused. The stale 3D binding on unit 0 is the smoking gun that
exposes the off-by-one: it's the fingerprint of the prior module that left
unit 0 in a "don't touch" state, which the terrain setup silently reused.

## Difficulty Rating
**Medium (3/5)**

The offending line looks like a correct sampler-unit assignment; reviewers
have to track which module bound what to which unit across the whole frame
to notice that unit 0 is "claimed" by the fog pass and unit 1 holds the
actual terrain texture.

## Adversarial Principles
- **Stale state**: The fog module's 3D binding on unit 0 persists across
  module boundaries with no visible handoff.
- **Off-by-one unit**: `glUniform1i(loc, 0)` vs. `glUniform1i(loc, 1)` —
  trivially wrong, trivially overlooked.
- **Cross-module leak**: The bug's cause and effect are in different source
  modules, so neither file read in isolation reveals the conflict.

## How OpenGPA Helps

The specific query that reveals the bug:

```
inspect_drawcall(frame=0, index=0)
```

This returns the live per-unit texture binding table snapshot at the draw
call: `active_texture=GL_TEXTURE0`, `unit[0].TEXTURE_BINDING_3D=<vol_tex>`,
`unit[0].TEXTURE_BINDING_2D=0`, `unit[1].TEXTURE_BINDING_2D=<terrain_tex>`,
plus the sampler-uniform values showing `terrain_tex=0`. Seeing the sampler
pointed at unit 0 — where only a 3D texture is bound and the 2D slot is
empty — while the real terrain texture sits unused on unit 1, pins the
off-by-one immediately.

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