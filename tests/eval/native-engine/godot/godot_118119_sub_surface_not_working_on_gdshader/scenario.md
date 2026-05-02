# R21: Sub-Surface Scattering silently disabled when ALPHA=1.0

## User Report
### Tested versions

You could use "SSS_STRENGTH = 1.0;" to turn ON Sub-Surface Scattering on a spatial shader and "SSS_STRENGTH = 0.0;" to turn it off. However, starting from version 4.6 this command stopped working.

The image below shows how it's supposed to worked, and how it is working

(images attached)

### System information

Godot v4.6.2.rc1 - Windows 11 (build 26200) - Multi-window, 2 monitors - Vulkan (Forward+) - dedicated NVIDIA GeForce RTX 3060 (NVIDIA; 32.0.15.9186) - AMD Ryzen 7 5800X 8-Core Processor (16 threads) - 31.91 GiB memory

### Issue description

Trying to turn on Sub-Surface Scattering using gdshader doesn't work anymore.

### Steps to reproduce

1. Create a spatial gdshader
2. Try to turn on SubSurface Scattering using "SSS_STRENGTH = 1.0;"
3. It doesn't work.

### Minimal reproduction project (MRP)

No

## Expected Correct Output
A material with non-zero `SSS_STRENGTH` should render visible subsurface
scattering regardless of whether the shader also writes `ALPHA = 1.0`.
Setting alpha to its default opaque value should not silently mask an
unrelated lighting feature.

## Actual Broken Output
With `ALPHA = 1.0` and `SSS_STRENGTH = 1.0`, the surface renders as a plain
opaque material with no SSS tint. The base color pass is dispatched but the
SSS effect pass is missing from the frame entirely.

## Ground Truth
A spatial shader that sets both `SSS_STRENGTH = 1.0` and `ALPHA = 1.0`
produces no visible subsurface scattering. Removing the `ALPHA` write (or
setting it below 1.0) restores the effect. The SSS uniform is honored by
the shader source but the SSS render pass is never dispatched, so the agent
sees a draw call with the expected uniforms yet no SSS contribution in the
final image.

The original reporter narrowed the trigger to a specific interaction
between `ALPHA` and `SSS_STRENGTH`:

> Whenever you set the ALPHA to 1.0 and the SSS_STRENGTH = 1.0, Godot turns
> off the Subsurface Scattering Effect ... However, if I don't set the
> ALPHA, the effect turns ON again. Apparently this is the default behavior
> in Godot.

The pattern is a material-pass classifier that treats explicit `ALPHA = 1.0`
writes as a hint that the material is fully opaque, and on that branch
skips enqueuing the separate SSS effect pass — even though the SSS strength
uniform is non-zero. Note: as of the issue thread no maintainer has
confirmed whether this is a regression or intended optimization, and no fix
PR has been merged; this diagnosis is grounded in the reporter's own
bisection in the linked thread.

## Difficulty Rating
4/5

## Adversarial Principles
- silent_pass_dropping
- uniform_set_but_pass_skipped
- classifier_short_circuits_on_opaque

## How OpenGPA Helps
Listing draw calls for the affected mesh shows the base color draw call
present with the expected SSS-related uniforms, but no subsequent SSS
effect draw call against the SSS framebuffer. That mismatch — uniform
plumbed but pass missing — points the agent at the material classifier
rather than at the shader source.

## Source
- **URL**: https://github.com/godotengine/godot/issues/118119
- **Type**: issue
- **Date**: 2026-04-19
- **Commit SHA**: (n/a)
- **Attribution**: Reported by upstream user in godotengine/godot#118119

## Tier
core

## API
opengl

## Framework
none

## Bug Signature
```yaml
type: missing_draw_call
spec:
  expected_pass: subsurface_scattering_effect
  trigger_state:
    material.alpha: 1.0
    material.sss_strength: 1.0
  observed: only base color pass dispatched; SSS pass absent
```

## Upstream Snapshot
- **Repo**: https://github.com/godotengine/godot
- **SHA**: (auto-resolve from commit 118119-head)
- **Relevant Files**:
  - servers/rendering/renderer_rd/forward_clustered/render_forward_clustered.cpp
  - servers/rendering/renderer_rd/shaders/forward_clustered/scene_forward_clustered.glsl
  - scene/resources/material.cpp
  - servers/rendering/shader_compiler.cpp

## Predicted OpenGPA Helpfulness
- **Verdict**: yes
- **Reasoning**: The bug is invisible from the shader source alone — the
  uniform is set and the GLSL is correct. Only by inspecting the actual
  dispatched draw calls can the agent see that the SSS pass is missing,
  which immediately redirects the investigation from "shader math" to
  "render-pass classifier".

## Observed OpenGPA Helpfulness
- **Verdict**: ambiguous
- **Evidence**: validation skipped (--no-validate)
