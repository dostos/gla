# R208: PlayCanvas alpha-tested materials render incorrectly during prepass

## User Report
On a PlayCanvas scene that uses several materials with alpha testing
(foliage cards, chain-link fences) and a few standard materials with
dithered opacity for fade-out LOD transitions, the prepass output looks
wrong. Cutout regions of the foliage are not being discarded — instead
the prepass writes depth/normals for the full quad, and that causes
ghost silhouettes around leaves and the fence wires when later passes
sample the prepass targets. The dithered fade-out materials similarly
write a fully-opaque footprint into the prepass, so SSAO and other
prepass-driven effects show a hard rectangle at the LOD transition
distance instead of the expected dither pattern.

The shadow pass for the same materials looks fine — alpha test and
opacity dither both work there. It's specifically the prepass that
seems to skip the alpha logic. Tested on PlayCanvas engine, latest
main as of the report.

## Expected Correct Output
The prepass should respect alpha testing — pixels failing the alpha
test discard, exactly like in the forward and shadow passes. Dithered
opacity materials should produce the same dither pattern in the
prepass that they produce in the shadow pass, so prepass-derived
effects (SSAO, screen-space normals) match the eventual lit output.

## Actual Broken Output
Foliage and fence prepass output is fully opaque — alpha cutouts are
ignored. SSAO/contact-shadow effects derived from the prepass show
ghost rectangles around alpha-tested geometry. Dithered LOD fade-outs
appear as hard rectangles in prepass-derived effects rather than the
expected stippled pattern.

## Ground Truth
The prepass shader path was sharing the same empty code branch as the
pick pass in `LitShader.generateFragmentShader()`, which meant the
prepass compiled with no shader defines at all. As the maintainer
described in PR #8606:

> The prepass shader pass was sharing the same empty code path as
> the pick pass, which meant it had no shader defines set. This
> caused materials with alpha testing or opacity dithering to render
> incorrectly during the prepass because the relevant shader code
> was never compiled in.

The fix splits the combined `SHADER_PICK` / `SHADER_PREPASS` branch
and adds a dedicated `preparePrepassPass()` method on `LitShader`
that sets `LIT_ALPHA_TEST`, `LIT_BLEND_TYPE`, and
`STD_OPACITY_DITHER` (mirroring `prepareShadowPass()` and using
`opacityShadowDither` for the dither selection). See
https://github.com/playcanvas/engine/pull/8606.

## Fix
```yaml
fix_pr_url: https://github.com/playcanvas/engine/pull/8606
fix_sha: (auto-resolve from PR #8606)
fix_parent_sha: (auto-resolve from PR #8606)
bug_class: framework-internal
framework: playcanvas
framework_version: main
files:
  - src/scene/shader-lib/programs/lit-shader.js
change_summary: >
  Splits the prepass off from the combined SHADER_PICK / SHADER_PREPASS
  empty-defines branch in LitShader.generateFragmentShader() and adds a
  preparePrepassPass() method that sets LIT_ALPHA_TEST, LIT_BLEND_TYPE,
  and STD_OPACITY_DITHER (using opacityShadowDither, mirroring
  prepareShadowPass) so alpha-tested and dithered-opacity materials
  compile the right shader code during the prepass.
```

## Flywheel Cell
primary: framework-maintenance.web-3d.code-navigation
secondary:
  - framework-maintenance.web-3d.captured-literal-breadcrumb

## Difficulty Rating
4/5

## Adversarial Principles
- bug-lives-inside-framework-not-user-code
- diagnosis-requires-grep-not-pixel-comparison
- shader-pass-coupling-hidden-in-switch-statement

## How OpenGPA Helps
A `gpa trace` of a single frame would show that the draw calls for
alpha-tested foliage submitted during the prepass bind a shader
program whose fragment source contains no `#define LIT_ALPHA_TEST`
and no `discard` site, while the same material in the shadow and
forward passes binds programs that DO contain the alpha-test discard.
Inspecting the prepass program's `/uniforms` and source via
`gpa report --pass prepass` reveals the missing defines and points
the agent at the shader-program preparation code path
(`LitShader.generateFragmentShader`) where the prepass branch lacks
its own `preparePrepassPass()` setup.

## Source
- **URL**: https://github.com/playcanvas/engine/pull/8606
- **Type**: pull-request
- **Date**: 2026-04-27
- **Commit SHA**: (auto-resolve from PR #8606)
- **Attribution**: Fix authored and described by the PlayCanvas engine maintainers in PR #8606.

## Tier
maintainer-framing

## API
webgl

## Framework
playcanvas

## Bug Signature
```yaml
type: code_location
spec:
  expected_files:
    - src/scene/shader-lib/programs/lit-shader.js
  fix_commit: (auto-resolve from PR #8606)
```

## Predicted OpenGPA Helpfulness
- **Verdict**: yes
- **Reasoning**: The smoking-gun signal — alpha-tested geometry
  binding a prepass shader whose fragment source lacks the
  `LIT_ALPHA_TEST` define and any `discard` — is exactly the kind of
  per-pass per-program comparison OpenGPA's frame capture surfaces
  natively. Diffing the prepass program against the shadow-pass
  program for the same material narrows the search to the shader
  preparation function and the pass-specific define setup, which
  maps directly to the fix site in `lit-shader.js`.