# R13: Bevy depth prepass skipped when there are only transparent objects

## User Report

Running the `order_independent_transparency` example on Bevy `main`
(commit `9eed7a39a1728ac7a9fbcc00f49ba6a91db380d5`) and pressing **C**
to cycle scenes, the red sphere ends up culled by the cube's depth.
The reporter believes this is a regression — the example used to
render correctly.

Repro:

1. `cargo run --example order_independent_transparency`
2. Press **C** to cycle to the all-transparent scene.

Expected: every transparent object renders correctly, regardless of
which other objects are present.
Actual: the red sphere is depth-culled by the cube as if the cube
had been written into the depth prepass — but in fact the depth
prepass texture is **uncleared**, so it still contains stale depth
from the previous scene.

## Expected Correct Output

When the scene contains only transparent objects, the depth prepass
must still **run** (or at minimum, clear its target). Either way the
depth attachment that subsequent passes read from must start at the
"far" value, so transparents are not occluded by stale depth from
prior frames or prior scene layouts.

## Actual Broken Output

The prepass node early-returns when it has no opaque draws to issue,
which means the depth prepass texture is never cleared. The texture
still contains depth from the previous frame's render pass, and the
order-independent transparency pass reads that stale depth and
incorrectly culls fragments that should be visible.

## Ground Truth

Per the fix PR ("Don't skip prepass if there are no opaque objects"):

> # Objective
>
> Fixes #23920
>
> ## Solution
>
> Don't skip prepass if there are no opaque objects

The fix removes the early-return in `prepass/node.rs` so the prepass
render pass is always begun (and therefore its depth/stencil
`load_op` runs and clears the attachment) on every frame, even when
no opaque draws would be recorded into it.

See https://github.com/bevyengine/bevy/pull/23999 (fixes #23920).

## Fix
```yaml
fix_pr_url: https://github.com/bevyengine/bevy/pull/23999
fix_sha: 073624d14daf3da15f2a4288b7d5b6747c36ca19
fix_parent_sha: 14f34fa98d1c913a6e357009a66bf18393aa2f8f
bug_class: framework-internal
framework: bevy
framework_version: main@9eed7a39a1728ac7a9fbcc00f49ba6a91db380d5
files:
  - crates/bevy_core_pipeline/src/prepass/node.rs
change_summary: >
  The prepass node previously early-returned when its draw queue was
  empty, which meant `vkCmdBeginRenderPass`/`renderPass.Begin` was
  never called and the depth attachment's clear `load_op` never fired.
  The fix removes the early-return so the prepass render pass is
  always begun, ensuring the depth prepass texture is cleared every
  frame, irrespective of whether there are any opaque objects in the
  scene.
```

## Upstream Snapshot
- **Repo**: https://github.com/bevyengine/bevy
- **SHA**: 14f34fa98d1c913a6e357009a66bf18393aa2f8f
- **Relevant Files**:
  - crates/bevy_core_pipeline/src/prepass/node.rs

## Flywheel Cell
primary: framework-maintenance.game-engine.code-navigation
secondary:
  - framework-maintenance.game-engine.captured-clear-op-breadcrumb

## Difficulty Rating
3/5

## Adversarial Principles
- bug-lives-inside-framework-not-user-code
- stale-attachment-state-when-pass-is-skipped-not-when-pass-runs
- regression-only-visible-on-the-all-transparent-cycle-of-the-example

## How OpenGPA Helps

The Vulkan capture would show the **absence** of the prepass render
pass on broken frames: the captured frame's `vkCmdBeginRenderPass`
sequence would jump directly from the shadow pass to the main forward
pass, with no entry whose attachment list contains the prepass depth
target. On the working scene cycle (with opaque objects) the same
capture would show the prepass `vkCmdBeginRenderPass` present with
`loadOp = CLEAR`. A diff between the two captures highlights the
missing prepass — pointing the agent at `prepass/node.rs` as the
location where the pass is conditionally suppressed.

## Source
- **URL**: https://github.com/bevyengine/bevy/issues/23920
- **Type**: issue
- **Date**: 2026-04-21
- **Commit SHA**: 073624d14daf3da15f2a4288b7d5b6747c36ca19
- **Attribution**: Reported by @beicause in bevy#23920; fix in PR #23999.

## Tier
maintainer-framing

## API
vulkan

## Framework
bevy

## Bug Signature
```yaml
type: code_location
spec:
  expected_files:
    - crates/bevy_core_pipeline/src/prepass/node.rs
  fix_commit: 073624d14daf3da15f2a4288b7d5b6747c36ca19
```

## Predicted OpenGPA Helpfulness
- **Verdict**: yes
- **Reasoning**: A frame capture of the broken scene shows the
  prepass render pass missing entirely (no `vkCmdBeginRenderPass`
  whose attachments include the prepass depth target). The
  `gpa frame-diff` between the all-transparent cycle and any cycle
  with opaque geometry would surface that missing pass as the
  primary delta. From there, the agent has a strong signal that
  the prepass node is being skipped — directly pointing at
  `prepass/node.rs`.

## Observed OpenGPA Helpfulness
- **Verdict**: no
- **Evidence**: code_only baseline scored 1.0 on file-level identification (Claude Code Explore subagent against the bevy snapshot at fix_parent_sha, ~20 file reads, ~30s wall time). The user-report keywords map directly onto the bug-bearing file path, leaving no headroom for runtime capture to add value. See docs/superpowers/eval/round13/bevy-code-only-results.md.
