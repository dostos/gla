# R18: OpenGL depth clear leaks compare-mode depth texture into non-shadow sampler

## User Report
### Godot version

4.2.dev 5ee983188de97ae027f9b9c1443438063f708a7e

### System information

Windows - OpenGL

### Issue description

I may have introduced this in the work I'm doing right now but just in case this is a more serious issue I don't want to loose track of it. Don't have time to investigate it right now.

In `LightStorage::update_directional_shadow_atlas` the code:
```
glDepthMask(GL_TRUE);
glBindFramebuffer(GL_FRAMEBUFFER, directional_shadow.fbo);
RasterizerGLES3::clear_depth(1.0);
glClear(GL_DEPTH_BUFFER_BIT);
```

Results in:
```
ERROR: GL ERROR: Source: OpenGL Type: Undefined behavior  ID: 131222  Severity: Medium
Message: Program undefined behavior warning:
The current GL state uses a sampler (0) that has depth comparisons enabled,
with a texture object (1018) with a depth format,
by a shader that samples it with a non-shadow sampler.
Using this state to sample would result in undefined behavior
```
(edited for readability)

### Steps to reproduce

Create a project using the compatibility renderer with a directional light, and turn it on.

### Minimal reproduction project

n/a

## Expected Correct Output
A black framebuffer with a white fullscreen triangle (the depth texture's
cleared 1.0 value sampled as red) and no GL debug warnings. Either the depth
texture should be unbound after the shadow-atlas clear, or its
`GL_TEXTURE_COMPARE_MODE` should be reset to `GL_NONE` before any non-shadow
sampler shader can read texture unit 0.

## Actual Broken Output
Driver emits debug message 131222 on the `glDrawArrays` call. Sampled values
are implementation-defined; on most NVIDIA drivers the result is zero
(producing a black triangle), on others it may be the comparison result, on
others it may sample correctly — exactly the symptom of UB.

## Ground Truth
After clearing the directional-shadow atlas FBO, the depth texture (depth
format with `GL_TEXTURE_COMPARE_MODE = GL_COMPARE_REF_TO_TEXTURE`) is left
bound to texture unit 0. The next draw call uses a shader that declares the
matching binding as a plain `sampler2D` (a non-shadow sampler). Per the GL
spec this is undefined behavior; NVIDIA's debug output reports it as
`KHR_debug` message ID 131222 ("sampler with depth comparisons enabled, with a
texture object with a depth format, by a shader that samples it with a
non-shadow sampler").

The reporter quotes the exact driver message and points at the offending
sequence in `LightStorage::update_directional_shadow_atlas`:

> ```
> glDepthMask(GL_TRUE);
> glBindFramebuffer(GL_FRAMEBUFFER, directional_shadow.fbo);
> RasterizerGLES3::clear_depth(1.0);
> glClear(GL_DEPTH_BUFFER_BIT);
> ```
> Results in:
> The current GL state uses a sampler (0) that has depth comparisons enabled,
> with a texture object (1018) with a depth format,
> by a shader that samples it with a non-shadow sampler.

The shadow-atlas depth texture stays bound to texture unit 0 across the
clear; later passes (including 2D-only projects, per comments 4 and 6) bind a
shader expecting `sampler2D` at unit 0 and trip the UB rule. The thread has
no merged maintainer fix as of the bug report, but the reporter and
follow-up commenters consistently reproduce the same `ID: 131222` message,
which uniquely identifies this UB pattern in the GL spec.

## Difficulty Rating
4/5

## Adversarial Principles
- state_leak_across_passes
- depth_compare_mode_vs_non_shadow_sampler
- undefined_behavior_with_implementation_defined_visual_output

## How OpenGPA Helps
Querying `/api/v1/frames/current/draw_calls/<id>` shows the bound textures
per unit and their `GL_TEXTURE_COMPARE_MODE`; cross-referencing the active
program's sampler uniform types lets the agent flag "unit 0 has a depth
texture with COMPARE_MODE = COMPARE_REF_TO_TEXTURE while the program's
`uTex` is a non-shadow `sampler2D`" — exactly the UB the driver complains
about, but visible without needing `KHR_debug` callbacks.

## Source
- **URL**: https://github.com/godotengine/godot/issues/84558
- **Type**: issue
- **Date**: 2023-11-08
- **Commit SHA**: (n/a)
- **Attribution**: Reported by @clayjohn

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
  draw_call_selector: last
  expectation: "no texture unit bound to active program's non-shadow sampler may have GL_TEXTURE_COMPARE_MODE != GL_NONE"
  offending_unit: 0
  offending_param: GL_TEXTURE_COMPARE_MODE
  offending_value: GL_COMPARE_REF_TO_TEXTURE
  sampler_uniform_type: sampler2D
```

## Predicted OpenGPA Helpfulness
- **Verdict**: yes
- **Reasoning**: The bug is a per-draw-call state mismatch (sampler type vs.
  texture compare mode) that is invisible in the rendered pixels on many
  drivers but trivially detectable from captured per-draw GL state. OpenGPA's
  Tier-1 raw state capture is exactly the right shape for this query, and an
  agent doesn't need any heuristic — just compare the sampler uniform type
  against `GL_TEXTURE_COMPARE_MODE` of the bound texture.

## Observed OpenGPA Helpfulness
- **Verdict**: ambiguous
- **Evidence**: validation skipped (--no-validate)
