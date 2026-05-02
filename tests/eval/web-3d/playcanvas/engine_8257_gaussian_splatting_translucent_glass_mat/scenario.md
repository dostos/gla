# R209: Gaussian Splatting inside translucent glass sphere flips draw order with camera angle

## User Report
Combining Gaussian Splatting with a translucent (glass-like) material produces inconsistent draw order. I created a glass material and placed a Gaussian Splatting entity inside a sphere that uses this glass material.

Depending on the camera angle, the rendering order seems to flip: sometimes the glass sphere renders in front of the splat, and other times it renders behind it. The exact angles where it flips also vary depending on which Gaussian asset is inside.

Either order would be acceptable (glass always in front or always behind), but the fact that it changes back and forth while orbiting the camera is very noticeable and distracting.

PlayCanvas version: 2.14.3

## Expected Correct Output
A stable, consistent draw order between the glass sphere and the Gaussian Splat as the camera orbits — either the glass is always drawn in front of the splat, or always behind it, but never flipping during camera motion.

## Actual Broken Output
As the camera orbits the scene, the glass sphere and the enclosed Gaussian Splat swap which one appears on top. The flip happens at different angles depending on which splat asset is loaded, producing a visible popping artifact during camera movement.

## Ground Truth
The maintainer confirmed this is the engine's documented transparent-sort behavior, not a bug:

> We sort meshes by the center of bounding box, and so whatever is closer, renders on top. In cases like this, where meshes overlap, you might need to do manual sorting.

Because the glass sphere fully encloses the splat, the two bounding-box centers are nearly coincident; small camera-orbit changes flip which center is nearer to the camera, which in turn flips the back-to-front sort under `SORTMODE_BACK2FRONT`. The maintainer's recommended consumer-side fix is to override the order via `MeshInstance.drawBucket` — meshes with a larger bucket number render first under back-to-front sorting. The issue was closed as expected behavior (see https://github.com/playcanvas/engine/issues/8257). No engine-side fix PR was opened.

## Fix
```yaml
fix_pr_url: https://github.com/playcanvas/engine/issues/8257
fix_sha: (auto-resolve from issue #8257)
fix_parent_sha: (auto-resolve from issue #8257)
bug_class: legacy
framework: playcanvas
framework_version: 2.14.3
files: []
change_summary: >
  No engine fix; closed as expected behavior. Maintainer guidance:
  override the bounding-box-center sort by setting MeshInstance.drawBucket
  on the user's overlapping transparent meshes (larger bucket renders first
  under SORTMODE_BACK2FRONT).
```

## Flywheel Cell
primary: framework-maintenance.web-3d.transparent-sort-semantics
secondary:
  - framework-maintenance.web-3d.code-navigation

## Difficulty Rating
4/5

## Adversarial Principles
- bug-is-actually-expected-behavior-not-a-defect
- diagnosis-requires-knowing-engine-sort-mode-rules
- fix-lives-in-user-config-not-engine-source

## How OpenGPA Helps
`gpa trace` across two camera angles around the flip threshold would show the same two transparent draw calls swapping submission order — the depth and blend state are identical, only the call order changes. That, combined with `gpa report`'s per-frame draw-call list, points the agent at a CPU-side sort decision rather than a depth/blend bug, narrowing diagnosis to PlayCanvas's transparent sort mode and its `drawBucket` override.

## Source
- **URL**: https://github.com/playcanvas/engine/issues/8257
- **Type**: issue
- **Date**: 2026-04-27
- **Commit SHA**: n/a
- **Attribution**: Reported by the issue author against PlayCanvas 2.14.3; diagnosed and closed as expected behavior by a PlayCanvas maintainer who recommended `MeshInstance.drawBucket` for manual override.

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
  fix_commit: n/a
```

## Predicted OpenGPA Helpfulness
- **Verdict**: partial
- **Reasoning**: GPA can show that the two transparent draws swap submission order between frames with no state difference, which correctly points at a CPU sort decision rather than a GPU/depth bug. But the resolution is consumer-side configuration (`drawBucket`) inside PlayCanvas's documented sort semantics, so GPA narrows the search but cannot itself surface the API-level fix.