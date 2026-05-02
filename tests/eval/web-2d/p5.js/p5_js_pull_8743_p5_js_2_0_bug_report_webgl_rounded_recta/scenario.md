# R203: p5.js WebGL rounded rectangles aren't round enough

## User Report
Drawing a rect with a radius parameter in WebGL mode produces corners
that visibly don't approximate a circle. With p5.js (all versions, all
browsers, all operating systems), running the snippet below shows the
problem clearly: a 200x200 rectangle with radius 100 should look like a
perfect circle, but it ends up flat-sided and visibly non-circular.

```js
function setup() {
  createCanvas(400, 400, WEBGL);
}

function draw() {
  background(220);
  rectMode(CENTER);
  rect(0, 0, 200, 200, 100);
}
```

If I instead build the same shape by hand with cubic `bezierVertex`
calls using the kappa constant (`4*(sqrt(2)-1)/3 ≈ 0.5523`) as the
handle ratio, the result looks like a proper circle. So the underlying
machinery is capable of drawing this correctly — it's the corner
construction inside `rect()` itself that looks wrong.

Reference screenshots in the original report:
- Current output: https://github.com/user-attachments/assets/059a99aa-f21f-480d-80cc-7abe9e7122b4
- Expected output (manual cubic bezier): https://github.com/user-attachments/assets/55e7500b-b504-4f9f-9f37-da3b79ed6d59

## Expected Correct Output
A 200x200 rect with radius 100 in WEBGL mode should render as an
indistinguishable-from-circular shape — the corner arcs should match
what a real quarter-circle looks like.

## Actual Broken Output
The corners are visibly "fatter" / less circular than expected. At
extreme radii (radius == half the side length) the result is obviously
non-circular rather than a perfect circle.

## Ground Truth
The maintainer (@davepagurek) confirmed the diagnosis in PR #8743
(https://github.com/processing/p5.js/pull/8743), titled "Use more
circular rounding for WebGL rect corners":

> Replaces quadratic rounded corners with cubic rounded corners

The WebGL `rect()` path was building each rounded corner as a single
quadratic Bezier, which is a poor approximation of a circular arc. The
fix switches the construction to cubic Beziers using the standard
kappa handle ratio (`4*(sqrt(2)-1)/3`), the same approximation the
reporter demonstrated by hand.

## Fix
```yaml
fix_pr_url: https://github.com/processing/p5.js/pull/8743
fix_sha: (auto-resolve from PR #8743)
fix_parent_sha: (auto-resolve from PR #8743)
bug_class: framework-internal
framework: p5.js
framework_version: 2.0+
files:
  - src/webgl/3d_primitives.js
change_summary: >
  Replace the quadratic-Bezier rounded-corner construction in the
  WebGL rect() implementation with a cubic-Bezier approximation using
  the kappa handle ratio (4*(sqrt(2)-1)/3), so corners actually look
  circular at large radii.
```

## Flywheel Cell
primary: framework-maintenance.web-2d.code-navigation
secondary:
  - framework-maintenance.web-2d.geometry-approximation

## Difficulty Rating
3/5

## Adversarial Principles
- bug-lives-inside-framework-not-user-code
- diagnosis-requires-grep-not-pixel-comparison
- visual-quality-bug-not-correctness-bug

## How OpenGPA Helps
OpenGPA's `gpa trace` over a frame containing the rounded rect surfaces
the actual vertex stream that p5.js's WebGL retained-mode renderer
emits for the corners — the agent can see how many segments / what
control points are produced and compare against a circular arc, which
points directly at the corner-construction code in
`src/webgl/3d_primitives.js` rather than at the shader or the geometry
buffer plumbing.

## Source
- **URL**: https://github.com/processing/p5.js/issues/8742
- **Type**: issue
- **Date**: 2026-04-27
- **Commit SHA**: (auto-resolve from PR #8743)
- **Attribution**: Reported by the p5.js community; diagnosed and fixed by @davepagurek in PR #8743.

## Tier
maintainer-framing

## API
webgl

## Framework
p5.js

## Bug Signature
```yaml
type: code_location
spec:
  expected_files:
    - src/webgl/3d_primitives.js
  fix_commit: (auto-resolve from PR #8743)
```

## Predicted OpenGPA Helpfulness
- **Verdict**: yes
- **Reasoning**: The bug shows up as a specific vertex stream (a quadratic-curve corner) emitted by the framework's retained-mode WebGL path. `gpa trace` plus the captured draw-call vertex buffer let the agent confirm "the framework is generating the wrong control points," which scopes the fix from the entire p5.js codebase down to the WebGL rect emitter — exactly where PR #8743 made the change.