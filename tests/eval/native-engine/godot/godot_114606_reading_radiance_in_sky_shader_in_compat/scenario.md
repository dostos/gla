# R30: Reading RADIANCE in sky shader returns black in compatibility mode

## User Report
### Tested versions

 - Reproducible with 4.5.1-stable

### System information

Godot v4.5.1.stable (f62fdbde1) - Ubuntu 22.04.5 LTS - OpenGL 3
(Compatibility) - NVIDIA GeForce RTX 3050 - Intel(R) Xeon(R) CPU E5-1620 v2

### Issue description

 - Reproducible with 4.5.1-stable
 - I wanted to use this simple sky shader in compatibility mode (as suggested
   in the sky shader documentation):
```
shader_type sky;

void sky() {
    if (AT_CUBEMAP_PASS) {
        COLOR = vec3(1.0, 0.0, 0.0);
    } else {
        COLOR = texture(RADIANCE, EYEDIR).rgb;
    }
}
```
The cubemap pass is done (objects get a red tint due to ambient light), but
RADIANCE can not be read (black sky). I'm using NVIDIA GeForce RTX 3050 with
driver version 580.95.05 (linux).

A renderdoc capture suggested that the sampler binding differs from the
engine binding.

A working quick-and-dirty fix is to change
```
uniform samplerCube radiance; //texunit:-1
```
to
```
uniform samplerCube radiance; //texunit:-2
```
in drivers/gles3/shaders/sky.glsl and shifting the following texunits
accordingly.

I'm completely new to the godot code and currently don't have much time, so I
guess I missed something. I will investigate further, but maybe here is an
expert who can give hints in the meantime so I don't think in the wrong
direction.

### Steps to reproduce

use the sky shader described in the issue description

## Expected Correct Output
The framebuffer should be tinted by the sampled cubemap — red, in this
minimal repro.

## Actual Broken Output
The framebuffer is black. The sampler reads from a texture unit that has no
cubemap bound, instead of the unit where the engine actually placed the
radiance cubemap.

## Ground Truth
The Godot GLES3 sky shader declares the radiance sampler with a hint pinning
it to one texture unit, while the C++ renderer activates and binds the
cubemap on a *different* unit. Per the reporter's investigation:

> A renderdoc capture suggested that the sampler binding differs from the
> engine binding.

The GLSL side has:

```
uniform samplerCube radiance; //texunit:-1
```

while `drivers/gles3/rasterizer_scene_gles3.cpp::_render_list_template`
binds the cubemap on `max_texture_image_units - 2`:

> `glActiveTexture(GL_TEXTURE0 + config->max_texture_image_units - 2); ...
> texture_to_bind = sky->radiance; ... glBindTexture(GL_TEXTURE_CUBE_MAP,
> texture_to_bind);`

The proposed fix (acknowledged by a maintainer with "That looks like the
correct fix! Please open a PR.") changes the GLSL hint from `//texunit:-1`
to `//texunit:-2` so it agrees with the C++ binding location. The reproducer
mirrors this by calling `glUniform1i(RADIANCE, max_units-1)` while binding
the cubemap on `max_units-2`, so the sampler reads an empty unit and returns
black.

## Difficulty Rating
4/5

## Adversarial Principles
- bind_point_collision
- sampler_uniform_vs_glActiveTexture_mismatch
- silent_zero_read_from_unbound_unit

## How OpenGPA Helps
Querying the draw call's bound textures reveals a cubemap bound on unit
`MAX_UNITS-2`, while the active program's `RADIANCE` sampler uniform points
at unit `MAX_UNITS-1` (which has no cubemap). Cross-referencing the sampler
uniform values against the per-unit binding table makes the off-by-one
immediately visible — agents staring at shader source alone would never see
it.

## Source
- **URL**: https://github.com/godotengine/godot/issues/114606
- **Type**: issue
- **Date**: 2025-12-04
- **Commit SHA**: (n/a)
- **Attribution**: Reported and root-caused by the issue author; fix
  acknowledged by a Godot maintainer in-thread.

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
  draw_call_index: 0
  uniform_name: RADIANCE
  uniform_kind: sampler
  expected_bound_target_on_uniform_unit: GL_TEXTURE_CUBE_MAP
  actual_bound_target_on_uniform_unit: GL_NONE
  note: |
    The sampler uniform RADIANCE is set to a texture unit that has no cubemap
    bound; the cubemap is actually bound on a different unit
    (max_combined_texture_image_units - 2).
```

## Predicted OpenGPA Helpfulness
- **Verdict**: yes
- **Reasoning**: The bug is invisible from shader source and from the C++
  binding code in isolation — it only manifests as a *mismatch* between the
  two. OpenGPA's per-draw-call view of (active program uniforms) ∪ (per-unit
  texture bindings) is exactly the join needed to spot it.

## Observed OpenGPA Helpfulness
- **Verdict**: ambiguous
- **Evidence**: validation skipped (--no-validate)
