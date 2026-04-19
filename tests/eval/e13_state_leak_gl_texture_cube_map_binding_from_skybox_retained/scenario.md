# E13_STATE_LEAK_GL_TEXTURE_CUBE_MAP_BINDING_FROM_SKYBOX_RETAINED: Skybox cube map bleeds into terrain ambient

## User Report
I render a skybox with a blue cube map, then a terrain pass that's supposed
to sample a separate, neutral-white environment cube map (`envTex`). The
terrain shows up as a dark teal — roughly RGBA `(10, 122, 82, 255)` at the
center pixel — instead of the saturated green grass I expect (~RGBA
`(51, 255, 102, 255)`). The colors look like the grass base color is being
modulated by the blue skybox color rather than the white probe. Both cube
maps are uploaded successfully and the sampler uniform on the terrain
shader is set to unit 0. No GL errors.

## Expected Correct Output
Terrain covers the whole viewport at z=0.5, overdrawing the skybox. With the neutral white env probe bound (`envTex`), the fragment output is `base * env * 2.0 = (0.1, 0.8, 0.2) * (1, 1, 1) * 2 = (0.2, 1.0, 0.4)`, so the center pixel reads roughly RGBA `(51, 255, 102, 255)` — saturated green grass.

## Actual Broken Output
The skybox cube map (`skyTex`, color (0.2, 0.3, 0.8)) is still bound on unit 0, so the fragment output becomes `(0.1, 0.8, 0.2) * (0.2, 0.3, 0.8) * 2 = (0.04, 0.48, 0.32)`. Center pixel reads approximately RGBA `(10, 122, 82, 255)` — a dark teal that looks nothing like grass.

## Ground Truth
The terrain pass samples a `samplerCube uEnv` expecting a neutral white
environment probe, but the renderer never rebinds `GL_TEXTURE_CUBE_MAP` on
texture unit 0 after the skybox pass. The terrain therefore modulates its
grass color with the blue skybox cube map.

Cube map bindings are per-texture-unit, not per-shader-program. Switching
`glUseProgram` and resetting `uEnv` to sampler unit 0 does nothing about
which cube map *object* is attached to unit 0 — that binding was set by
the skybox pass and persists. The terrain pass forgot to issue
`glBindTexture(GL_TEXTURE_CUBE_MAP, envTex)`, so the skybox texture
silently services the terrain's env samples. The bug is invisible in
source review because everything "looks bound" near `glUseProgram(terrProg)`,
and the uniform assignment of `0` reads correctly.

## Difficulty Rating
**Medium (3/5)**

The two passes are textually close and the buggy pass has a uniform-location call that looks like setup; reviewers scan the lines and see a sampler being wired to unit 0 without noticing there is no `glBindTexture`. Cube map leaks are also easy to confuse with lighting bugs in the shader.

## Adversarial Principles
- **Stale state**: A binding from an earlier pass silently services a later pass that assumed a fresh environment.
- **Module boundary leak**: Skybox renderer and terrain renderer appear independent but share mutable texture-unit state with no contract about who resets it.

## How OpenGPA Helps

OpenGPA reports the cube map object bound on each texture unit at every
draw call, so identical cube map ids appearing across the skybox draw and
the terrain draw is visible directly without manually tracing binds across
passes.

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
  rule: "Terrain draw (draw_call_index=1) must sample a dedicated env-probe cube map, not the skybox cube map from draw_call_index=0"
  draw_call_index: 1
  texture_unit: 0
  target: GL_TEXTURE_CUBE_MAP
  expected_binding: "env probe cube map (distinct from skybox)"
  actual_binding: "same cube map id bound at draw_call_index=0 (skybox)"
```
