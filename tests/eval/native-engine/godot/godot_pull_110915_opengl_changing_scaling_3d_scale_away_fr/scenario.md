# R21: OpenGL scene dims when Scaling 3D engages an intermediate buffer (double tonemap)

## User Report
### Tested versions

Reproducible in 4.3dev

### System information

Godot v4.3.stable - Windows 10.0.26100 - GLES3 (Compatibility) - NVIDIA GeForce RTX 4050 Laptop GPU (NVIDIA; 32.0.15.6119) - Intel(R) Core(TM) Ultra 7 155H (22 Threads)

### Issue description

Making a game with large outdoor scenes from birds eye view. I am trying to use compatibility rendering so there's low system requirements and I am finding conflicts with 3D settings. I have an environment in the main scene which clears the background to a custom color and uses Filmic Tonemapping. It seems that whenever I change scaling_3d_scale in my game's options panel the entire scene will permanently dim, until I reset the 3d scale back to its default 1.0 value at runtime. It doesn't occur with linear tonemapping in the environment's settings.

| 3d scale 1.0 | 3d scale 4.0 |
|--------------|--------------|
| (image) | (image) |

### Steps to reproduce

To reproduce what the example scene I uploaded:
1) Create a test scene
2) Add an environment that uses custom clear for the background
3) Add a toggle button that when toggled sets the scaling_3d_scale to 4.0
4) Press the toggle button and observe that changing the 3d scale causes the entire scene and background to dim
5) Press again to set back the 3d scale and observe that its fixed.

### Minimal reproduction project (MRP)

3d_scale_tonemapping_scene.zip (attached)

## Expected Correct Output
A scene rendered with Filmic tonemapping should look identical regardless of whether the renderer is going scene → backbuffer directly (1.0 scale) or scene → intermediate FBO → post → backbuffer (non-1.0 scale). Tonemapping should be applied exactly once.

## Actual Broken Output
The 3D scene is visibly darker once `scaling_3d_scale != 1.0`. Highlights are crushed, mid-tones are pushed down. The frame contains the result of running the tonemap operator twice on the scene color.

## Ground Truth
On Godot's OpenGL (Compatibility) backend, setting `scaling_3d_scale` to anything other than 1.0 — or otherwise enabling an intermediate buffer (glow, color adjustments) — causes the entire scene to dim. Toggling the scale back to 1.0 restores the original brightness.

Two interacting bugs in the GL3 Compatibility renderer:

1. The scene shader unconditionally applies tonemapping inline, even when an intermediate buffer is present and a post pass will tonemap again. Comment 2 from the issue describes exactly this:
   > "The tonemapping is *always* being applied in the scene shader, thus scene objects receive tonemapping twice when using an intermediate buffer."

2. Once the intermediate buffer (`internal3d.fbo`) is created on a config change, it is not torn down when no longer needed, so the post-tonemap path stays active. Per PR #110915:
   > "After setting up the intermediate buffers for the first time, they don't get cleared after disabling glow / adjustments."

The author who landed PR #110915 confirms the scene-side fix in comment 3:
   > "I didn't notice a difference in the scene on master, so I'm guessing I fixed that with https://github.com/godotengine/godot/pull/110915 which fixed tonemapping happening twice in some cases after toggling settings on and then off again."

The companion fix for the clear-color tonemapping path is PR #111550 ("Always apply tonemapping to solid color background in Compatibility").

## Difficulty Rating
4/5

## Adversarial Principles
- state_leak_across_config_change
- duplicated_postprocess_in_two_passes
- correctness_depends_on_runtime_toggle

## How OpenGPA Helps
A draw-call dump on the broken frame shows two consecutive program uses that both contain a `tonemap`/`x/(x+1)` style operation (or, in Godot's case, the `APPLY_TONEMAPPING` define active in the scene shader AND the post tonemap shader bound for the resolve). An agent comparing the bound program for the scene draw and the bound program for the post draw — or doing a histogram comparison of the intermediate FBO color attachment vs. the default framebuffer — sees that the post pass darkens an already-tonemapped image instead of mapping HDR linear to display.

## Source
- **URL**: https://github.com/godotengine/godot/issues/102860
- **Type**: issue
- **Date**: 2025-02-14
- **Commit SHA**: (n/a)
- **Attribution**: Reported by upstream user; diagnosis from comments by @Calinou and @clayjohn, fix in PR #110915 (Clayton John) and PR #111550

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
  draw_index: -1   # final post-pass draw to default framebuffer
  expected:
    bound_program_does_not_chain_with_prior_tonemap: true
  observed:
    prior_pass_program_applies_tonemap: true
    final_pass_program_applies_tonemap: true
  notes: >
    Two consecutive draws each apply a tonemap-shaped operator to the same
    color signal. The intermediate FBO color attachment is already in
    display-mapped range when the post pass samples it, so the second tonemap
    further compresses the values and the frame appears dimmed.
```

## Predicted OpenGPA Helpfulness
- **Verdict**: yes
- **Reasoning**: The bug is purely a pipeline-shape issue — "which programs ran, in what order, against which framebuffers." OpenGPA's draw-call list with bound program + bound FBO per draw exposes this directly: the agent sees scene_prog rendered into a non-zero FBO, then post_prog rendered into FBO 0 sampling that texture, with both fragment shaders containing tonemap math. No pixel-level oracle is needed — the state trace is the diagnosis.

## Upstream Snapshot
- **Repo**: https://github.com/godotengine/godot
- **SHA**: c4a893e988935aa8401a9ab4d3dd29b96db4fa1a
- **Relevant Files**:
  - drivers/gles3/rasterizer_scene_gles3.cpp
  - drivers/gles3/rasterizer_scene_gles3.h
  - drivers/gles3/storage/render_scene_buffers_gles3.cpp
  - drivers/gles3/storage/render_scene_buffers_gles3.h
  - drivers/gles3/shaders/scene.glsl
  - drivers/gles3/shaders/sky.glsl
  - drivers/gles3/shaders/tonemap_inc.glsl

## Observed OpenGPA Helpfulness
- **Verdict**: ambiguous
- **Evidence**: validation skipped (--no-validate)
