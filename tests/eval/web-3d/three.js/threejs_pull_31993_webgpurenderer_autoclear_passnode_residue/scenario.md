# R13: WebGPURenderer + autoClear=false leaves residue in PassNode's internal render target

## User Report

Setting `renderer.autoClear = false` in three.js post-processing examples
produces visibly different behavior between `WebGPURenderer` and the legacy
`WebGLRenderer`. On WebGL the user sees a persistent after-image (frames
ghost into each other). On WebGPU the same scene renders into a black
texture. Adding `renderer.clear()` at the top of `animate()` does NOT fix
either backend — the residue is in PassNode's *internal* render target,
which the user-level `renderer.clear()` doesn't reach.

Repro:

1. Open `webgpu_postprocessing_outline.html` (or the WebGL equivalent).
2. In the dev console, run `renderer.autoClear = false`.
3. Left-click and drag to rotate the scene.

Expected: the outline pass should still render correctly across frames.
Actual: WebGL ghosts the previous frame; WebGPU shows a black texture.

Three.js version: r177 (issue filed at this revision; behavior reproduces
through r178/179 until the fix landed).

## Expected Correct Output

Each frame's post-processing pass starts from a cleared internal render
target — so toggling `autoClear` at the user-renderer level only affects
what the user is responsible for, not what `PassNode` writes to internally.

## Actual Broken Output

`PassNode` never clears its internal render target. With `autoClear=false`,
the previous frame's PassNode output bleeds into the current frame's pass:
WebGL produces ghosting; WebGPU produces an all-black texture (the WebGPU
backend treats an uncleared texture differently from WebGL).

## Ground Truth

Per maintainer in PR #31993 ("PassNode: Ensure clear of internal render
target"):

> #31966 exposed an issue in `PassNode`: If `autoClear` is set to `false`,
> the internal render target is never cleared which yields to different
> bugs in the backends. WebGL produces a persistent after image effect
> whereas WebGPU produces just a black texture.
>
> The PR introduces the same behavior like in other FX passes by resetting
> the flag to its default value.

The fix forces `PassNode` to reset the renderer's clear-state flag back to
its default before drawing into its internal render target — independent
of whatever `autoClear` value the user set on the outer renderer. This
matches what other FX passes already did and removes the WebGL/WebGPU
divergence.

See https://github.com/mrdoob/three.js/pull/31993 (fixes #31966).

## Fix
```yaml
fix_pr_url: https://github.com/mrdoob/three.js/pull/31993
fix_sha: ec4c9b2e0da04bcc5fe0f597c13c20b44f8ba637
fix_parent_sha: 2a028849d71e5e62d6e139d442a2661bca98f8d9
bug_class: framework-internal
framework: three.js
framework_version: r177
files:
  - src/nodes/display/PassNode.js
  - examples/jsm/tsl/display/OutlineNode.js
change_summary: >
  PassNode's render() now temporarily resets the renderer's clear-state
  flag (matching what other FX passes do) so its internal render target
  is reliably cleared before each frame's pass executes — irrespective
  of the user-level `renderer.autoClear` setting. Removes the
  WebGL-ghosting / WebGPU-black-texture divergence by ensuring both
  backends see a consistent pre-pass clear.
```

## Flywheel Cell
primary: framework-maintenance.web-3d.code-navigation
secondary:
  - framework-maintenance.web-3d.captured-literal-breadcrumb

## Difficulty Rating
3/5

## Adversarial Principles
- bug-lives-inside-framework-not-user-code
- behavioral-divergence-between-backends-points-at-shared-abstraction-not-backend-driver
- user-level-fix-attempts-fail-because-state-is-internal-to-a-node-class

## How OpenGPA Helps

`gpa report` against a captured WebGL frame would surface the
`auto-clear-with-no-explicit-clear` rule firing on the post-processing
draws (the user disabled outer-renderer auto-clear and PassNode never
issued its own clear). The same rule fires on the WebGPU side via the
analogous internal-target capture. The captured drawcall list would
show the missing `glClear` / `vkCmdBeginRenderPass(…loadOp=clear…)`
before the PassNode pass — pointing the agent at PassNode's
render target setup as the location to fix.

## Source
- **URL**: https://github.com/mrdoob/three.js/issues/31966
- **Type**: issue
- **Date**: 2026-04-29
- **Commit SHA**: ec4c9b2e0da04bcc5fe0f597c13c20b44f8ba637
- **Attribution**: Reported in three.js#31966; fix authored by maintainer in PR #31993.

## Tier
maintainer-framing

## API
opengl

## Framework
three.js

## Bug Signature
```yaml
type: code_location
spec:
  expected_files:
    - src/nodes/display/PassNode.js
  fix_commit: ec4c9b2e0da04bcc5fe0f597c13c20b44f8ba637
```

## Predicted OpenGPA Helpfulness
- **Verdict**: yes
- **Reasoning**: The `gpa check-config` rule
  `auto-clear-with-no-explicit-clear` fires precisely on this pattern
  (draw calls with no preceding `glClear` when the framework's auto-clear
  is disabled). On the WebGL capture, the rule output points at the draws
  that immediately follow PassNode's pass — telling the agent the
  pre-pass clear is missing, even though the user already tried adding a
  user-level `renderer.clear()`. From there, the captured drawcall
  sequence around `PassNode` is the natural next step to inspect.

## Observed OpenGPA Helpfulness
- **Verdict**: ambiguous
- **Evidence**: validation skipped (committed via direct gh-driven fetch, no eval run yet)
