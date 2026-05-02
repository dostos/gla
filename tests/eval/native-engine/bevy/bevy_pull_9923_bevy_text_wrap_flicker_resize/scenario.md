# R14: Bevy text flickers between one and two lines as font size changes

## User Report

```rust
use bevy::prelude::*;

fn main() {
    App::new()
        .add_plugins(DefaultPlugins)
        .add_systems(Startup, setup)
        .add_systems(Update, update)
        .run();
}

fn setup(mut commands: Commands) {
    commands.spawn(Camera2dBundle::default());
    commands.spawn(TextBundle::from("Hello, world!"));
}

fn update(mut text_query: Query<&mut Text>) {
    for mut text in text_query.iter_mut() {
        text.sections[0].style.font_size *= 1.001;
    }
}
```

As the text increases in size it flickers between being displayed on
one line and being wrapped across two lines. It should always remain
on one line at this size; the wrap is wrong.

## Expected Correct Output

The string "Hello, world!" should be displayed on a single line as
its font size grows continuously. There is no frame at which the
text legitimately needs to be split across two lines while the
window can still hold it on one.

## Actual Broken Output

Every few frames, "Hello, world!" wraps to a second line and
displays as

```
Hello,
world!
```

before snapping back to one line on the next frame.

## Ground Truth

Per the fix PR ("Store both the rounded and unrounded node size in
Node"):

The UI layout system computed each text node's size, rounded the
size to integer pixels for rendering, and then on the next frame
fed the *rounded* size back into the wrap calculation. The rounded
size was sometimes smaller than the unrounded size by less than one
pixel — enough to trip the wrap from "fits in one line" to "needs
two lines". Storing both the rounded and unrounded sizes, and
using the unrounded size for wrap input, eliminates the oscillation.

## Fix
```yaml
fix_pr_url: https://github.com/bevyengine/bevy/pull/9923
fix_sha: edba496697d3918ca5a2110363c502692ef9d2dd
fix_parent_sha: 96a7b4a777d717d0a431f15cde8088c0a3ee2879
bug_class: framework-internal
framework: bevy
framework_version: main@038d113
files:
  - crates/bevy_ui/src/layout/mod.rs
  - crates/bevy_ui/src/ui_node.rs
  - crates/bevy_ui/src/widget/text.rs
change_summary: >
  UI text wrap fed the rounded (pixel-snapped) node size back into
  the wrap calculation on the following frame, causing a sub-pixel
  oscillation between wrapped and unwrapped layouts as the font
  size grew. The fix stores both rounded and unrounded sizes and
  uses the unrounded size for wrap input.
```

## Upstream Snapshot
- **Repo**: https://github.com/bevyengine/bevy
- **SHA**: 96a7b4a777d717d0a431f15cde8088c0a3ee2879
- **Relevant Files**:
  - crates/bevy_ui/src/layout/mod.rs
  - crates/bevy_ui/src/ui_node.rs
  - crates/bevy_ui/src/widget/text.rs

## Flywheel Cell
primary: framework-maintenance.game-engine.code-navigation
secondary:
  - framework-maintenance.game-engine.captured-text-glyph-trace

## Difficulty Rating
4/5

## Adversarial Principles
- visual-symptom-only-user-report
- subpixel-rounding-feedback-loop
- bug-is-cross-frame-state-not-single-frame-defect

## How OpenGPA Helps

A frame-by-frame capture of the text quad's vertex positions and
the glyph atlas's quad positions reveals that the per-frame text
node width oscillates by ~0.5 pixels around the threshold at which
the wrapper splits the line. Once that oscillation is visible in
the trace, the agent's investigation focuses on the layout/text
pipeline rather than on the font-rendering or shader path.

## Source
- **URL**: https://github.com/bevyengine/bevy/issues/9874
- **Type**: issue
- **Date**: 2023-09-26
- **Commit SHA**: edba496697d3918ca5a2110363c502692ef9d2dd
- **Attribution**: Reported in issue #9874; fix in PR #9923.

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
    - crates/bevy_ui/src/layout/mod.rs
    - crates/bevy_ui/src/ui_node.rs
    - crates/bevy_ui/src/widget/text.rs
  fix_commit: edba496697d3918ca5a2110363c502692ef9d2dd
```

## Predicted OpenGPA Helpfulness
- **Verdict**: yes
- **Reasoning**: The user-report mentions "wrap" but does not name
  any rounding or layout subsystem. Grep on "wrap" returns many
  unrelated hits; grep on "flicker" returns nothing useful.
  Cross-frame glyph-position trace from capture localizes the
  problem to the layout step that consumes node size — pointing
  the agent at the rounding feedback loop.

## Observed OpenGPA Helpfulness
- **Verdict**: ambiguous
- **Evidence**: validation pending — code_only baseline not yet run.
