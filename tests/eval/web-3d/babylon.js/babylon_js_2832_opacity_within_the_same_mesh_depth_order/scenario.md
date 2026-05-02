# R9: Opacity within the same mesh, depth order

## User Report
Using BabylonJS, I built a simple scene with a torus knot and a blue material with `alpha = 0.9` (playground: https://www.babylonjs-playground.com/#1PLV5Z#18).

Where the knot crosses over itself, the depth order looks wrong. On one of the crossings the visual ordering is fine — the strand that should be in front does appear in front. But on the other crossing, the part that is geometrically behind appears closer to the camera. The transparency seems to be drawn in the wrong order within the same mesh.

For comparison, rendering a similar scene in three.js doesn't look perfect either, but at least the strand-ordering is correct: the part closer to the camera looks closer.

Is there a way to get a result closer to the three.js one in BabylonJS? I tried a few suggestions on the forum (purely additive blending; `mesh.material.needDepthPrePass = true`) — additive blending changes the look in a way I don't want, and `needDepthPrePass` works for separate meshes but breaks down when two "objects" share a single mesh (https://www.babylonjs-playground.com/#JB6H3P#1 — with the purple box in front, the green and yellow boxes vanish).

Tested on the BabylonJS playground at the time of filing (late 2017).

## Expected Correct Output
On the self-intersecting torus knot, every place where one strand crosses another should look consistent: the strand that is geometrically nearer the camera should appear in front of the strand that is geometrically farther.

## Actual Broken Output
At one of the crossings, the strand that is geometrically *behind* is drawn over the strand that is geometrically *in front*. The transparent fragments belonging to the same mesh are not depth-sorted against each other, so whichever triangle the renderer happens to draw last "wins" — even when it is the farther one.

## Ground Truth
This is not a bug in BabylonJS code — it is the well-known limitation of unsorted alpha blending (Order-Independent Transparency, OIT). The maintainer (@deltakosh) explicitly classifies it as such in the thread:

> actually threejs has the same issue (you can see that the right part is not transparent). The problem of self opacity and order independent transparency is a big beast.

The maintainer offers two existing engine-level workarounds rather than a code fix:

> - You can change the alpha blending to move to a purely additive one. Alpha value will not be used but the rendering could work in your case
> - You can rely on a new option we introduced recently: `mesh.material.needDepthPrePass = true`

A later comment points to a third workaround introduced in the engine (`https://www.babylonjs-playground.com/#JB6H3P#5`, line 20). The discussion is then moved to the BabylonJS forum (`http://www.html5gamedevs.com/topic/33026-transparency-alpha-issues/`) and the GitHub issue is closed without a code-level fix PR — the issue thread itself never resolves to a merged framework patch.

The relevant maintainer-authored docs that this scenario should ground out against:
`https://doc.babylonjs.com/typedoc/classes/BABYLON.Material#needDepthPrePass`

## Fix
```yaml
fix_pr_url: (none — issue closed without a fix PR; engine workarounds documented instead)
fix_sha: (none)
fix_parent_sha: (none)
bug_class: legacy
framework: babylon.js
framework_version: 3.x
files: []
change_summary: >
  Fix PR not resolvable from the issue thread alone; the maintainer
  classifies the symptom as the order-independent-transparency limitation
  and points users to engine workarounds (`needDepthPrePass`, additive
  blending) rather than a code patch. Scenario retained as a legacy
  bug-pattern reference for self-intersecting transparent meshes.
```

## Flywheel Cell
primary: framework-maintenance.web-3d.transparency-sort
secondary:
  - framework-maintenance.web-3d.maintainer-classification

## Difficulty Rating
4/5

## Adversarial Principles
- bug-lives-in-rendering-algorithm-not-in-source-line
- diagnosis-requires-recognizing-OIT-limitation-not-finding-a-fix
- workaround-not-fix

## How OpenGPA Helps
A `gpa trace` of the frame would show that within a single draw call the torus-knot triangles are emitted in mesh index-buffer order rather than back-to-front camera order, and `gpa report` over the alpha-blended pass would show no per-triangle depth sort happening between the transparent fragments. Cross-checking `/draw-calls` for the knot mesh against the depth-buffer state via `/feedback-loops` reveals depth-test passes but no depth-write for the transparent material — the classic OIT signature. This evidence lets the agent identify the problem as algorithmic (intra-mesh alpha sorting is not performed) rather than as a localizable bug, and recommend `needDepthPrePass` or weighted-blended OIT as the correct path forward.

## Source
- **URL**: https://github.com/BabylonJS/Babylon.js/issues/2832
- **Type**: issue
- **Date**: 2017-09-19
- **Commit SHA**: (none)
- **Attribution**: Reported by the issue author; classified by @deltakosh (BabylonJS maintainer) as an order-independent-transparency limitation, with engine-level workarounds suggested in the thread.

## Tier
maintainer-framing

## API
webgl

## Framework
babylon.js

## Bug Signature
```yaml
type: code_location
spec:
  expected_files: []
  fix_commit: (none)
```

## Predicted OpenGPA Helpfulness
- **Verdict**: partial
- **Reasoning**: GPA can clearly surface the missing per-fragment depth sort (no depth-write on the alpha-blended draw, mesh-order triangle submission) and so steers the agent toward the correct *category* of answer — "this is OIT, not a bug" — and toward the documented workarounds. But because there is no fix PR or fix file, the maintainer-framing scorer's `code_location` metric cannot be satisfied; GPA's value here is diagnostic framing, not localization.

## Observed OpenGPA Helpfulness
- **Verdict**: ambiguous
- **Evidence**: validation skipped (--no-validate)
