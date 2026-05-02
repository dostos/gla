# R13: Bevy `scrolling_fog` example dark + flickering after PostProcess split

## User Report

Bevy `main` since PR #23098 (the "PostProcess set split" change) —
the `scrolling_fog` example regressed.

Repro:

```
cargo run --example scrolling_fog
```

Expected: volumetric fog renders correctly (the previous "before"
appearance of this canonical example).
Actual: the example renders dark and sometimes flickers.

A second issue: enabling TAA on the wireframe example (`wireframe.rs`)
shows similar flicker for wireframe draws.

## Expected Correct Output

Volumetric fog renders into the post-process chain in a stable
ordering relative to TAA, with no flicker between frames.

## Actual Broken Output

When PR #23098 introduced an `EarlyPostProcess` system set distinct
from `PostProcess`, several existing systems that were originally
scheduled "between MainPass and PostProcess" weren't migrated. They
ended up racing with TAA — running on either side of TAA depending
on scheduler order — which manifests as flicker (one frame the fog
applies before TAA, another frame after) and a dark image (the
volumetric fog pass writes to a render target whose contents are
later overwritten by an out-of-order TAA history sample).

## Ground Truth

Per the fix PR ("Fix PostProcess orderings for fog and wireframes"):

> # Objective
>
> Fixes #23472 (and a similar issue for wireframes)
>
> When `EarlyPostProcess` was created in #23098, some existing
> systems that were scheduled between `MainPass` and `PostProcess`
> weren't updated. This caused them to race with TAA, which causes
> flickering and other artifacts.
>
> ## Solution
>
> Order them relative to `EarlyPostProcess` instead.

The fix changes the schedule constraints in `volumetric_fog/mod.rs`
and `wireframe.rs` so the fog and wireframe systems are explicitly
ordered against the new `EarlyPostProcess` set, eliminating the race
with TAA.

See https://github.com/bevyengine/bevy/pull/23558 (fixes #23472).

## Fix
```yaml
fix_pr_url: https://github.com/bevyengine/bevy/pull/23558
fix_sha: b167b12983c9b872bb6a157a23d557f1fcd16f12
fix_parent_sha: 8ec74bd64f6a6d31b69eca9e768000fa7f8f5bc3
bug_class: framework-internal
framework: bevy
framework_version: main@post-23098
files:
  - crates/bevy_pbr/src/volumetric_fog/mod.rs
  - crates/bevy_pbr/src/wireframe.rs
change_summary: >
  PR #23098 split `PostProcess` into `EarlyPostProcess` +
  `PostProcess`, but some systems that needed to run between
  `MainPass` and the post-process chain were left with stale schedule
  constraints. They raced against TAA, producing dark and flickering
  output. The fix restores the intended ordering by anchoring those
  systems against `EarlyPostProcess` explicitly, removing the race
  with TAA.
```

## Upstream Snapshot
- **Repo**: https://github.com/bevyengine/bevy
- **SHA**: 8ec74bd64f6a6d31b69eca9e768000fa7f8f5bc3
- **Relevant Files**:
  - crates/bevy_pbr/src/volumetric_fog/mod.rs
  - crates/bevy_pbr/src/wireframe.rs

## Flywheel Cell
primary: framework-maintenance.game-engine.code-navigation
secondary:
  - framework-maintenance.game-engine.captured-draw-order-breadcrumb

## Difficulty Rating
3/5

## Adversarial Principles
- bug-lives-inside-framework-not-user-code
- regression-introduced-by-an-orthogonal-refactor-23098
- ordering-bug-shows-up-as-pixel-flicker-not-as-an-error

## How OpenGPA Helps

`gpa frame-diff` between two consecutive captured frames would show
the volumetric-fog draws in **different positions** in the
`vkCmdBeginRenderPass` sequence — sometimes before the TAA pass,
sometimes after — exactly mirroring the underlying scheduler race.
Stable ordering after the fix is itself a frame-capture-visible
contract: every captured frame should have the same draw-call
sequence for fog vs. TAA. The agent could, given a few captured
frames, observe the order flipping and infer that the fog system
isn't anchored to `EarlyPostProcess`. The set of files where
volumetric fog is scheduled is small (`volumetric_fog/mod.rs`),
giving a tight code-location signal.

## Source
- **URL**: https://github.com/bevyengine/bevy/issues/23472
- **Type**: issue
- **Date**: 2026-03-22
- **Commit SHA**: b167b12983c9b872bb6a157a23d557f1fcd16f12
- **Attribution**: Reported by @mockersf in bevy#23472; fix in PR #23558.

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
    - crates/bevy_pbr/src/volumetric_fog/mod.rs
  fix_commit: b167b12983c9b872bb6a157a23d557f1fcd16f12
```

## Predicted OpenGPA Helpfulness
- **Verdict**: ambiguous
- **Reasoning**: A single captured frame is not enough for this bug
  — the visual symptom is flicker across frames, and the diagnostic
  is "draw order changes between consecutive frames". OpenGPA can
  surface this with `gpa frame-diff` over multiple frames, but the
  agent must explicitly look at draw-call ordering across frames
  rather than at any single frame. Without that prompt, the agent
  may chase the dark-image symptom into shader code instead of into
  the schedule. With the diff, the signal is strong; without it,
  the bug is harder to localise.

## Observed OpenGPA Helpfulness
- **Verdict**: no
- **Evidence**: code_only baseline scored 1.0 on file-level identification (Claude Code Explore subagent against the bevy snapshot at fix_parent_sha, ~20 file reads, ~30s wall time). The user-report keywords map directly onto the bug-bearing file path, leaving no headroom for runtime capture to add value. See docs/superpowers/eval/round13/bevy-code-only-results.md.
