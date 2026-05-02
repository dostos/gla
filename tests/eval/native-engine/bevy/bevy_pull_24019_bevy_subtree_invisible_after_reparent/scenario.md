# R14: Bevy moved UI subtree becomes invisible after re-parenting

## User Report

Bevy 0.18.1.

I tried to re-parent a UI tree using `.detach_children` and then
`.insert_children` in the same system.

The re-parented subtree becomes invisible. The moved row renders at
its new position, but its children do not — sizes collapse to zero
and colored boxes disappear.

```rust
// Repro: a vertical list of rows; each row has a colored child
// box. Pressing space moves a row to a different parent using
// detach_children + insert_children in the same system.
//
// Expected: the moved row's colored child box still renders at its
// new position.
// Actual: the moved row renders at its new position but its
// children do not — sizes collapse to zero and colored boxes
// disappear.
```

(Full minimal repro attached in the issue.)

## Expected Correct Output

After the re-parent operation completes within one system, the
moved subtree should render identically to a subtree that was
spawned at its destination directly. Child node sizes should match
their layout-computed values; colored boxes should be visible.

## Actual Broken Output

After re-parenting, the moved row appears at its new location with
correct background color, but every descendant has a layout size
of zero and is therefore not drawn. The visual effect is that the
moved row looks "empty" while every other row in the list looks
normal.

## Ground Truth

Per the fix PR ("Detach reattach propagation fix"):

`detach_children` walks down the entity tree to clear an internal
"propagation context" component on every descendant — this
context is what the UI layout uses to know which window/camera the
node belongs to. `insert_children` was supposed to re-add the
context as it walks the new tree. But the propagation walker had
an early-out for entities whose context was *already cleared*,
because the walker assumed cleared context meant "this entity is
not a UI node". When a detach was followed by an insert in the
same system, every descendant of the moved subtree had its
context cleared and the early-out triggered for all of them — so
the insert never propagated context to any descendant, and the
layout reported their sizes as zero on the next pass.

The fix removes the early-out so propagation always walks the full
subtree, regardless of the descendant's current context state.

## Fix
```yaml
fix_pr_url: https://github.com/bevyengine/bevy/pull/24019
fix_sha: c3dab1a37eabebae95c4e31d709c1aa73e1732fc
fix_parent_sha: 5754300ef001d73bcd6f600130edee2f1cb7ee53
bug_class: framework-internal
framework: bevy
framework_version: 0.18.1
files:
  - crates/bevy_app/src/propagate.rs
change_summary: >
  The propagation walker's early-out for "already-cleared context"
  prevented re-attachment after a same-frame detach + insert,
  leaving the moved subtree with zero-size layout. Removing the
  early-out makes propagation walk the full subtree on every
  insert, so re-parented descendants receive their context and
  render correctly.
```

## Upstream Snapshot
- **Repo**: https://github.com/bevyengine/bevy
- **SHA**: 5754300ef001d73bcd6f600130edee2f1cb7ee53
- **Relevant Files**:
  - crates/bevy_app/src/propagate.rs

## Flywheel Cell
primary: framework-maintenance.game-engine.code-navigation
secondary:
  - framework-maintenance.game-engine.captured-ui-quad-trace

## Difficulty Rating
4/5

## Adversarial Principles
- visual-symptom-only-user-report
- bug-only-fires-when-detach-and-insert-happen-in-the-same-system
- bug-is-graph-walker-early-out-not-data-corruption

## How OpenGPA Helps

A frame capture of the broken frame shows that the moved row's
container quad is drawn with the correct width and height, but
zero descendant quads are emitted underneath it. That contrast —
"parent has size, children have zero size" — combined with the
fact that the same nodes have non-zero size before the re-parent,
points the agent at the propagation step rather than at layout
math or rendering. From there, the search converges quickly on
`crates/bevy_app/src/propagate.rs`.

## Source
- **URL**: https://github.com/bevyengine/bevy/issues/23893
- **Type**: issue
- **Date**: 2026-04-25
- **Commit SHA**: c3dab1a37eabebae95c4e31d709c1aa73e1732fc
- **Attribution**: Reported in issue #23893; fix in PR #24019.

## Tier
visual-only

## API
vulkan

## Framework
bevy

## Bug Signature
```yaml
type: code_location
spec:
  expected_files:
    - crates/bevy_app/src/propagate.rs
  fix_commit: c3dab1a37eabebae95c4e31d709c1aa73e1732fc
```

## Predicted OpenGPA Helpfulness
- **Verdict**: yes
- **Reasoning**: The user describes the symptom in UI terms
  (`detach_children`, `insert_children`, "moved row"). Grep on
  those names returns the public ECS API surface. The bug is in
  a generic propagation file (`bevy_app/src/propagate.rs`), which
  has nothing in its name about UI or children. A capture's
  parent-has-size-children-don't pattern is the strongest signal
  for finding it.

## Observed OpenGPA Helpfulness
- **Verdict**: ambiguous
- **Evidence**: validation pending — code_only baseline not yet run.
