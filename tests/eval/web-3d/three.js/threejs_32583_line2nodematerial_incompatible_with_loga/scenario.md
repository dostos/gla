# R3: Line2NodeMaterial incompatible with logarithmic depth buffer

## User Report
In the WebGPU rendering scenario, the WebGPURenderer uses the `logarithmicDepthBuffer` property and loads both a glb model and Line2 lines. The glb model is positioned below the Line2 model in the scene. At certain angles, some of the Line2 lines may be occluded by the glb model and become invisible.

Reproduction steps:
1. Initialize `renderer = new THREE.WebGPURenderer({ antialias: true, logarithmicDepthBuffer: true })`
2. Load the glb model
3. Load the Line2 line
4. Rotate the perspective and observe the phenomenon — Line2 segments that should be in front of the helmet end up occluded by it.

A live reproduction is available on jsfiddle. The same scene without `logarithmicDepthBuffer: true` renders correctly.

**Version:** dev; r178
**Device:** Desktop, Chrome, Windows

## Expected Correct Output
With `logarithmicDepthBuffer: true`, the Line2 lines should occlude/be-occluded by the glb model based on their actual world-space depth, exactly as they do when the logarithmic depth buffer is disabled.

## Actual Broken Output
With `logarithmicDepthBuffer: true`, Line2 segments that should be in front of (or alongside) the helmet are wrongly occluded by it as the camera rotates. The depth values written for Line2 fragments are inconsistent with the depth values written for the glb mesh, so the depth test rejects pixels that should be visible.

## Ground Truth
Maintainer diagnosis from the issue thread:

> It seems `Line2NodeMaterial` is currently incompatible with logarithmic depth buffer because it directly assigns logic to `vertexNode` and does not compute `positionNode`. Hence, the below logic in `NodeMaterial.setupDepth()` for computing logarithmic depth does not operate on a correct view space position.

The pointer is to `src/materials/nodes/NodeMaterial.js` lines 737-749, where the logarithmic-depth path derives view-space Z from `positionView` — but `Line2NodeMaterial` never sets `positionNode`, so `positionView` is stale relative to the actual clip-space position the material returns from its `vertexNode`.

> @sunag I have a fix ready that computes the correct depth in the `Fn()` for `Line2NodeMaterial.vertexNode`. However, I don't like the solution since any custom material implementing `vertexNode` runs in the same issue. I think it would be better to update the code in `NodeMaterial` such that the logarithmic depth buffer computation relies on `clip.z` and not `positionView.z`.

The accepted approach was to introduce a `vertex` accessor exposing the result of `vertexNode` (analogous to `gl_Position`) and have `NodeMaterial.setupDepth()` derive logarithmic depth from `vertex.z` / `vertex.w` instead of `positionView.z`, so any material that overrides `vertexNode` is correct under the logarithmic depth buffer.

See draft at https://github.com/Mugen87/three.js/commit/818a050b9c0da69122c9745618d0139ae5a6bea9 and discussion in issue https://github.com/mrdoob/three.js/issues/32583.

## Fix
```yaml
fix_pr_url: https://github.com/mrdoob/three.js/pull/32594
fix_sha: ecf6e9c2a1b611dec468965db6c831b63889cbe8
fix_parent_sha: 11dc4c60a4e083666ca719a4ed9febcdd514c103
bug_class: framework-internal
framework: three.js
framework_version: r178
files:
  - src/Three.TSL.js
  - src/materials/nodes/NodeMaterial.js
  - src/nodes/accessors/Position.js
  - src/nodes/core/NodeBuilder.js
  - src/renderers/webgpu/nodes/WGSLNodeBuilder.js
change_summary: >
  Make NodeMaterial.setupDepth()'s logarithmic-depth path derive view-space
  Z from the actual vertex/clip-space output (vertex.z / vertex.w via
  perspectiveDepthToViewZ) rather than from positionView.z, so materials
  like Line2NodeMaterial that override vertexNode without setting
  positionNode produce consistent log-depth values.
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
- symptom-and-root-cause-are-in-different-files
- only-triggers-when-two-features-combine (Line2 + logarithmicDepthBuffer)

## How OpenGPA Helps
A `gpa trace` of two adjacent draws (the Line2 instanced quad and a glb mesh triangle near the same world position) exposes the per-fragment depth written by each shader; comparing the captured `gl_FragDepth`/clip-space `z/w` against the view-space Z that `NodeMaterial.setupDepth()` would expect makes the discrepancy visible without needing a screenshot diff. `gpa report --uniforms` on the Line2 draw also confirms `cameraNear`/`cameraFar` are bound while `positionView` for that material is never written, pointing the agent at the `positionNode` vs `vertexNode` divergence inside `NodeMaterial`.

## Source
- **URL**: https://github.com/mrdoob/three.js/issues/32583
- **Type**: issue
- **Date**: 2026-04-29
- **Commit SHA**: 818a050b9c0da69122c9745618d0139ae5a6bea9 (draft fix referenced in thread)
- **Attribution**: Reported by issue filer; diagnosed by @Mugen87; fix approach iterated with @sunag.

## Tier
maintainer-framing

## API
webgpu

## Framework
three.js

## Bug Signature
```yaml
type: code_location
spec:
  expected_files:
    - src/materials/nodes/NodeMaterial.js
    - src/materials/nodes/Line2NodeMaterial.js
  fix_commit: 818a050b9c0da69122c9745618d0139ae5a6bea9
```

## Predicted OpenGPA Helpfulness
- **Verdict**: yes
- **Reasoning**: The agent must connect a user-visible symptom (lines incorrectly occluded) to a two-file framework-internal interaction between `Line2NodeMaterial.vertexNode` and `NodeMaterial.setupDepth()`. OpenGPA's per-draw uniform/varying capture lets the agent observe that the Line2 draw never produces a view-space position while the log-depth path consumes one, narrowing the search to `setupDepth()` and the materials that override `vertexNode` without `positionNode`.

## Observed OpenGPA Helpfulness
- **Verdict**: ambiguous
- **Evidence**: validation skipped (--no-validate)
