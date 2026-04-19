# R18_GPUPARTICLES3D_ROTATION_FLICKER: GPUParticles3D rotation flicker on spawn

## User Report
### Godot version

4.0

### System information

Windows 10

### Issue description

In setting particles to be rotated at a random angle when they are spawned, I noticed that there's one frame in which they are unrotated after spawning:

(animated GIF showing rotation flicker)

Which causes the effect seen above (at 30fps).
(3.5 does not have this issue)

### Steps to reproduce

in a `GPUParticles3D` node after assigning a particle mesh to it:
- create a new `ParticleProcessMaterial`
- spread out the particles using an `emission_shape`
- set `Particle Flags`>`flag_rotate_y` to true
- set `Angle`>`angle_max` to 360

### Minimal reproduction project

N/A

## Expected Correct Output
Every particle, on every frame it is visible, is drawn rotated by its assigned random angle. There is no frame in which a spawned particle appears axis-aligned.

## Actual Broken Output
For one frame immediately after spawn, the particle is drawn with rotation = 0 (axis-aligned). On subsequent frames the correct random rotation is applied. The draw call issued during the bad frame has the particle's `u_rotation` uniform (or equivalent per-instance transform) at the default value instead of the randomized value.

## Ground Truth
When a particle system is configured to spawn particles with a random initial rotation (`flag_rotate_y` = true, `angle_max` = 360), each newly spawned particle renders for one frame in its default un-rotated orientation before snapping to the intended random angle on the next frame. At 30 fps this shows up as a visible flicker.

The root cause is the interpolation behavior of `GPUParticles3D` introduced in 4.0, which is documented in the linked issue #51318:

> The new GPUParticles3D interpolation feature smoothes out particle movement, but not property updates such as scale, color and rotation. This is important to fix as particle systems now run at 30 Hz (interpolated) by default, instead of running every frame like they did in `3.x`.

The particle-logic tick runs at a fixed low rate (default 30 Hz) and is responsible for assigning the random per-particle angle. The render tick runs faster and interpolates previous and current particle state. For a *newly spawned* particle there is no previous state, and the interpolator does not carry property curves (rotation/scale/color) through, so on the first render frame following spawn the rotation resolves to its default (0) before the logic tick populates the randomized value. The original reporter confirmed the linkage:

> it looks like it is definitely related to #51318.

Workarounds called out in #51318 — disabling Fixed FPS or raising it to 60 — reduce the visibility of the flicker because they shrink the window during which the un-ticked default is observable.

The issue was closed as not reproducible on 4.6.1.stable, but without a maintainer-identified fix commit, so the closure is based on observation that the symptom no longer appears rather than on an explicit patch to the interpolation/spawn path.

## Difficulty Rating
3/5

## Adversarial Principles
- transient_first_frame_state
- logic_render_rate_desync
- cross_issue_diagnosis_required

## How OpenGPA Helps
Querying the draw-call uniforms for the first captured frame directly exposes `u_rotation = 0.0` for the spawned particle, which contradicts the particle material's configured `angle_max = 360`. An agent pulling `GET /frames/current/draw_calls/{id}` and inspecting uniforms can flag the default-valued rotation against the authored particle settings and conclude that the logic tick producing the randomized angle has not yet run for this particle.

## Source
- **URL**: https://github.com/godotengine/godot/issues/75201
- **Type**: issue
- **Date**: 2023-03-21
- **Commit SHA**: (n/a)
- **Attribution**: Reported by @Magnesiumm; diagnosis cross-referenced to #51318 (reported by @Calinou)

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
  uniform_name: u_rotation
  expected_not_equal: 0.0
  draw_call_index: 0
  tolerance: 1.0e-4
```

## Upstream Snapshot
- **Repo**: https://github.com/godotengine/godot
- **SHA**: 0810756a9fceee369b33f71b8247e3c48c421dbb
- **Relevant Files**:
  - scene/3d/gpu_particles_3d.cpp  # default-branch SHA at issue close (not-reproducible on 4.6.1; cross-referenced to #51318); (inferred)
  - servers/rendering/renderer_rd/storage_rd/particles_storage.cpp
  - servers/rendering/renderer_rd/shaders/particles.glsl

## Predicted OpenGPA Helpfulness
- **Verdict**: yes
- **Reasoning**: The bug is entirely expressible as a wrong uniform value on the very first draw call of the first captured frame. OpenGPA's Tier-1 raw-fact surface (per-draw uniform capture) directly contains the evidence needed to diagnose, and no heuristic interpretation of the value is required — the agent can compare the captured rotation against the particle material's authored `angle_max` to see that the logic tick has not run.

## Observed OpenGPA Helpfulness
- **Verdict**: ambiguous
- **Evidence**: validation skipped (--no-validate)
