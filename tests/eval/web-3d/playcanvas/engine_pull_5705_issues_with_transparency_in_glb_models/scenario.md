# R201: Issues with transparency in glb models

## User Report
I tried a few meshes with transparency in PlayCanvas, and it seems from some angles
(depending on the sorted order) we don't render them correctly.

Example model: a glass kettle GLB from Sketchfab.

**Correct (front view):** the glass body and interior are layered properly, you can
see through the kettle and the inner walls show through.

**Incorrect (from behind):** large chunks of the kettle's far side disappear or
render as flat opaque silhouettes against the background.

I checked the same models in three.js and Babylon.js — both render them fine, so
this isn't a Sketchfab quirk in the asset.

A second model (a "ship in a bottle" GLB) shows similar but different artifacts:
the bottle's glass walls cut into the ship geometry inside.

I suspect this is related to a recent PlayCanvas change to how transparent gltf
materials interact with the depth buffer, but I'm not sure.

## Expected Correct Output
Semi-transparent GLB materials (glass kettle walls, glass bottle) should sort
and composite correctly from every camera angle, the way they do in three.js
and Babylon.js — the user can see through the front glass to the back glass
and to interior geometry.

## Actual Broken Output
From certain camera angles (notably "from behind" the kettle, and looking into
the bottle), parts of the transparent geometry render as if opaque, occluding
geometry that should be visible through them. The defect is view-angle
dependent and depends on draw-call sort order.

## Ground Truth
The breakage is a regression introduced by PlayCanvas PR #5705 ("Better handling
of gltf blend materials"). Per that PR's own description:

> Instead of completely disabling depth-write for semitransparent gltf materials,
> we write depth and enable alpha test on fragment alpha > 0 instead. This
> results in much better handling of complex semi-transparent scenes.

The change is a global trade-off: writing depth from semi-transparent fragments
fixes self-occlusion artifacts in some scenes (the cases the PR was designed for)
but breaks proper back-to-front blending for true glass-like materials with
smoothly varying alpha — which is exactly what the kettle and bottle GLBs are.
Maintainers in the issue thread acknowledge the trade-off ("Depending on the
scene, you probably want either the old way or new way") and discuss exposing
the behavior as a per-container loading option rather than a hard revert. The
issue thread does not surface a single clean follow-up PR resolving the question
— it remained an open framework-design discussion at the time of the report. See
https://github.com/playcanvas/engine/pull/5705 for the offending change and
https://github.com/playcanvas/engine/issues/5902 for the back-and-forth.

## Fix
```yaml
fix_pr_url: https://github.com/playcanvas/engine/pull/5705
fix_sha: (auto-resolve from PR #5705)
fix_parent_sha: (auto-resolve from PR #5705)
bug_class: legacy
framework: playcanvas
framework_version: "1.67"
files: []
change_summary: >
  Fix PR not resolvable from the issue thread alone; the thread identifies
  PR #5705 as the regression source but ends in an unresolved design debate
  (revert vs. expose as a per-container loading option). Scenario retained
  as a legacy bug-pattern reference for "depth-write on semi-transparent
  fragments breaks back-to-front blending."
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
- regression-traceable-to-specific-prior-pr

## How OpenGPA Helps
`gpa trace` on the affected camera angle would expose the per-draw GL state for
each transparent gltf submesh — specifically `glDepthMask(GL_TRUE)` paired with
`glEnable(GL_BLEND)` and a discard-on-alpha fragment shader, which is the exact
combination PR #5705 introduced. The `/draw_calls/{id}` view's depth-write +
blend-mode flags would let an agent confirm "this engine writes depth from
blended fragments" without reading any framework source, then grep the PlayCanvas
repo for the code that sets that combination on gltf materials.

## Source
- **URL**: https://github.com/playcanvas/engine/issues/5902
- **Type**: issue
- **Date**: 2023-12-19
- **Commit SHA**: (PR #5705 is the regression source; no clean fix PR in thread)
- **Attribution**: Reported by @mvaligursky; PR #5705 authored by @mvaligursky;
  follow-up design debate with @willeastcott in the issue thread.

## Tier
maintainer-framing

## API
opengl

## Framework
playcanvas

## Bug Signature
```yaml
type: code_location
spec:
  expected_files: []
  fix_commit: (auto-resolve from PR #5705)
```

## Predicted OpenGPA Helpfulness
- **Verdict**: yes
- **Reasoning**: GPA's per-draw-call depth-write + blend-state surface is exactly
  the signal that distinguishes "engine disables depth-write for transparents"
  (the conventional behavior, what three.js/Babylon do for these assets) from
  "engine writes depth and alpha-tests" (PlayCanvas's post-#5705 behavior). An
  agent can read that state from a single captured frame and immediately know
  to grep the framework for where gltf-blend materials configure depthWrite,
  collapsing the search space from the entire engine to the gltf-material setup
  path.