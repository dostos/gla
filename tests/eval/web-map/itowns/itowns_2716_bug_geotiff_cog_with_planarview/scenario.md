# R210: iTowns COG geotiff tiles missing on PlanarView with "Texture dimensions mismatch"

## User Report
I would like to display a COG (Cloud Optimized GeoTIFF) with PlanarView over a large extent, but some map tiles never appear and the browser console fills with "Texture dimensions mismatch" errors.

**Environment**
- iTowns: master @ `2987cb1` (development build)
- Use case: PlanarView with a large planar extent, layered with a COG geotiff source.

**Steps to reproduce**
1. Start the demo `examples/demo_hackathon_orvault_planarView.html` (a PlanarView with a COG layer over a large extent — see https://github.com/bloc-in-bloc/itowns/commit/136c65c74acd4bfd6422ac5571617df2f5c240bb).
2. Pan/zoom across the planar extent.
3. Observe: some map tiles are missing (broken / never rendered). The console shows repeated "Texture dimensions mismatch" errors.

**Expected**: Tiles of the PlanarView render correctly, with no texture-size errors.

**Actual**: A subset of tiles never renders. Screenshot: https://github.com/user-attachments/assets/b518e2a6-58e1-4197-8a3c-698df2871776

**My own hypothesis (possibly wrong)**: The COG parser appears to be producing a degenerate (1×1) texture for certain tiles, which a downstream layered-material check then refuses to upload because it doesn't match the expected tile size. If I bypass that early-return guard the tiles paint, but the console still complains. Forcing a 256×256 blank texture in the parser also seems to mask the symptom. I don't know what the right fix is — should the parser fail gracefully, or should the consumer be more tolerant of odd-sized inputs?

## Expected Correct Output
Every tile in the PlanarView's extent renders the COG raster (or a clean fallback) with no console errors. Either the COG parser produces a usable texture for every tile, or it skips/handles bad tiles cleanly without poisoning the layered material.

## Actual Broken Output
Random tiles across the planar extent are blank/broken. The console emits a stream of "Texture dimensions mismatch" errors, one per offending tile per frame.

## Ground Truth
Per the original report at https://github.com/iTowns/itowns/issues/2716, the bug pattern is rooted inside iTowns' own framework code, not in the user's application:

> The bug occurs because the CogParser create a 1x1 Texture
> And in LayeredMaterial.ts if we have a mistmatch texture size it logs an error and return immediately.

The reporter pinpointed two framework-internal files as the locus of the issue:
- `packages/Main/src/Parser/CogParser.ts` (around L113) — where the 1×1 texture is being constructed for some COG tiles.
- `packages/Main/src/Renderer/LayeredMaterial.ts` (around L142) — where a strict size check causes the early return that drops the tile.

A subsequent commenter agreed the framework should fail gracefully:

> In my experience, the texture mismatch is usually caused by invalid, empty or incorrectly inferred size of fetched data. We should fail gracefully in itowns, instead of passing it to three!

As of triage, no maintainer-merged fix PR has been linked from this issue, so this scenario is retained as a legacy bug-pattern reference — the diagnosis above is the reporter's, partially confirmed by another community member, but not yet ratified by a merged fix.

## Fix
```yaml
fix_pr_url: (not resolvable from issue thread)
fix_sha: (not resolvable)
fix_parent_sha: (not resolvable)
bug_class: legacy
framework: itowns
framework_version: master @ 2987cb1
files: []
change_summary: >
  Fix PR not resolvable from the issue thread alone; scenario retained
  as a legacy bug-pattern reference. Reporter's diagnosis points at
  CogParser emitting a 1×1 texture and LayeredMaterial early-returning
  on size mismatch, but no maintainer-merged resolution exists yet.
```

## Flywheel Cell
primary: framework-maintenance.web-3d.code-navigation
secondary:
  - framework-maintenance.web-3d.captured-literal-breadcrumb

## Difficulty Rating
3/5

## Adversarial Principles
- bug-lives-inside-framework-not-user-code
- diagnosis-requires-grep-not-pixel-comparison
- symptom-is-console-error-not-rendering-artifact

## How OpenGPA Helps
A `gpa trace` of a frame around a missing tile would show the tile's draw call invoking a sampler bound to a 1×1 texture (or no texture upload at all), which contradicts the LayeredMaterial's expected tile-size constant. `/uniforms` on the failing draw call surfaces the texture-handle + dimensions, letting the agent grep iTowns' source for the literal "Texture dimensions mismatch" error string and follow it back to `LayeredMaterial.ts`, then upstream to the parser that produced the degenerate texture.

## Source
- **URL**: https://github.com/iTowns/itowns/issues/2716
- **Type**: issue
- **Date**: 2025-XX-XX
- **Commit SHA**: 2987cb1cae1efa068d9b06ef69f21de9a828ef5f (reporter's repro point; no fix SHA)
- **Attribution**: Reported on iTowns issue #2716; community diagnosis quoted in `## Ground Truth`.

## Tier
maintainer-framing

## API
opengl

## Framework
itowns

## Bug Signature
```yaml
type: code_location
spec:
  expected_files: []
  fix_commit: (not resolvable)
  legacy_hint_files:
    - packages/Main/src/Parser/CogParser.ts
    - packages/Main/src/Renderer/LayeredMaterial.ts
```

## Predicted OpenGPA Helpfulness
- **Verdict**: yes
- **Reasoning**: The console message "Texture dimensions mismatch" is a literal string in iTowns' source, so the agent's path is (a) confirm via `gpa trace` / `/uniforms` that the failing tile's bound texture is 1×1 rather than the expected tile size, then (b) grep the framework for the error literal to land on `LayeredMaterial.ts`, then (c) trace the texture's producer back to `CogParser.ts`. OpenGPA's per-draw-call texture-dimension capture short-circuits the "is the bug in my code or the framework's" question that would otherwise require ad-hoc instrumentation.