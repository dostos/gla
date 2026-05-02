# R14: Godot ninepatch StyleBoxTexture rows show offset/misaligned texture

## User Report

The reporter has several `StyleBoxTexture` elements on screen, all
configured with identical `texture_margin` values and identical
`region_rect` sizes — only their positions differ. They expect the
nine elements to look pixel-identical because nothing about how the
texture is sliced has changed.

What they actually see in the editor screenshot is that some of the
boxes show a visible 1-pixel horizontal/vertical shift in their
texture content relative to others. They follow up with: "even
without using `texture_margin`, the issue of texture offset can
still be observed."

The issue first appeared in Godot 4.6 dev5 — earlier versions render
the row identically.

Repro:
1. Open the attached MRP in the editor.
2. Look at the row of `StyleBoxTexture` panels.
3. Some panels show a visible texture shift compared to their
   neighbors.

## Expected Correct Output

`StyleBoxTexture` panels with identical region/margin parameters
must sample identical regions of the source texture. There must
be no visible position-dependent shift — i.e. moving the panel
on the screen must not change which pixels of the source texture
appear inside it.

## Actual Broken Output

Different panels (positioned at different on-screen coordinates)
show different texture content — typically a 1-pixel shift in U
or V — for the same source rect parameters. The shift is
consistent for a given on-screen position but visible as a
mismatch across panels in the same row.

## Ground Truth

Per the fix PR ("Increase precision of ninepatch source rect to
ensure pixel perfect alignment"):

> In #112481 the `src_rect` was compressed into 4 half floats. But,
> as it turns out, ninepatch is really sensitive to precision, even
> at normal range numbers, which leads to small misalignment
> artifacts. Since passing another varying has a very real cost,
> this code path is limited to ninepatches.

The fix promotes the source-rect varying for ninepatch draws back
to full-precision floats, removing the half-float quantization that
caused the offset to round differently depending on the destination
position.

See https://github.com/godotengine/godot/pull/115152 (fixes
#115117).

## Fix
```yaml
fix_pr_url: https://github.com/godotengine/godot/pull/115152
fix_sha: dc57cd698d29915cd020b1c229735e4a7ec18b7d
fix_parent_sha: 895630e853b7f389c2a3de5cfe02ef433f7b8c23
bug_class: framework-internal
framework: godot
framework_version: 4.6.rc1
files:
  - servers/rendering/renderer_rd/renderer_canvas_render_rd.cpp
  - servers/rendering/renderer_rd/shaders/canvas.glsl
change_summary: >
  An earlier optimization compressed the canvas-renderer source-rect
  varying from full floats to four halfs to save varying bandwidth.
  Half-precision was insufficient for ninepatch source coordinates
  because the inner-edge UVs fell into a value range where 16-bit
  half rounding produced a 1/W or 1/H delta that visually shifted
  the sampled pixel by one. The fix restores full-precision floats
  on the ninepatch code path only, leaving regular canvas geometry
  on the bandwidth-saving half varying.
```

## Upstream Snapshot
- **Repo**: https://github.com/godotengine/godot
- **SHA**: 895630e853b7f389c2a3de5cfe02ef433f7b8c23
- **Relevant Files**:
  - servers/rendering/renderer_rd/renderer_canvas_render_rd.cpp
  - servers/rendering/renderer_rd/shaders/canvas.glsl

## Flywheel Cell
primary: framework-maintenance.game-engine.code-navigation
secondary:
  - framework-maintenance.game-engine.captured-uv-quantization

## Difficulty Rating
4/5

## Adversarial Principles
- precision-loss-bug-not-correctness-bug
- only-visible-when-the-same-source-rect-is-drawn-at-different-screen-positions
- code-path-touched-was-an-optimization-not-a-feature

## How OpenGPA Helps

The capture would record, per draw call, the actual UVs interpolated
into the fragment shader for adjacent panels. Inspecting the
captured fragment-stage UVs side-by-side, the agent can see that
two panels with identical "input source rect" parameters at the
draw-call level produce different fragment UVs at the same pixel
offset — a quantization fingerprint. From there, "where in the
canvas pipeline are UVs varying-interpolated" leads directly to
the half-float compression in `canvas.glsl` / canvas RD renderer.

## Source
- **URL**: https://github.com/godotengine/godot/issues/115117
- **Type**: issue
- **Date**: 2026-01-19
- **Commit SHA**: dc57cd698d29915cd020b1c229735e4a7ec18b7d
- **Attribution**: Reported in godot#115117; fix in PR #115152.

## Tier
end-user-framing

## API
vulkan

## Framework
godot

## Bug Signature
```yaml
type: code_location
spec:
  expected_files:
    - servers/rendering/renderer_rd/renderer_canvas_render_rd.cpp
    - servers/rendering/renderer_rd/shaders/canvas.glsl
  fix_commit: dc57cd698d29915cd020b1c229735e4a7ec18b7d
```

## Predicted OpenGPA Helpfulness
- **Verdict**: yes
- **Reasoning**: The reporter says "texture offset", "alignment",
  no other vocabulary. A code_only agent could grep
  `StyleBoxTexture` and reach `style_box_texture.cpp`, but the bug
  is in the canvas renderer downstream. With OpenGPA capturing
  the per-fragment UV deltas across two panels, the divergence
  point shows up as "two adjacent draw calls with the same input
  parameters resolved to different per-fragment UVs" — a
  quantization signal that points at the varying-interpolation
  shader, not the style-box class.

## Observed OpenGPA Helpfulness
- **Verdict**: ambiguous
- **Evidence**: validation pending — code_only baseline not yet run.
