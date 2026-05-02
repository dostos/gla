# R14: Bevy "hello bevy" text vanishes while the window is being resized

## User Report

```
cargo run --example text
```

Resize the window by dragging its bottom edge. While dragging, the
"hello bevy" message vanishes from the screen. As soon as you stop
dragging, it reappears.

This only happens during continuous drag — single-step resizes
don't trigger it.

(Bevy main, commit 05cae875.)

## Expected Correct Output

During a continuous resize the text should remain visible in every
frame. It is fine for the text size to lag the window size by a
frame, but the text must not blink off entirely.

## Actual Broken Output

Every frame in which the window size changes, the text disappears.
On the first stable frame after the user stops dragging, the text
returns. The intermediate frames render the rest of the UI
correctly — only the text content is missing.

## Ground Truth

Per the fix PR ("1-frame text update delay fix"):

Each text node, when its size changes, schedules a new font
instance to be loaded at the new size. The text-rendering system
waits for the font instance to be ready before producing glyph
quads. Loading happens asynchronously and lands one frame later.
The previous code path didn't keep the *old* font instance
available as a fallback, so during the in-between frame the text
node's draw produced zero glyphs.

The fix keeps the previous font instance available until the new
one is ready, so during the loading frame the text continues to
render at the previous size.

## Fix
```yaml
fix_pr_url: https://github.com/bevyengine/bevy/pull/23190
fix_sha: 8d55916d2933586b266ada76b82873b88897f776
fix_parent_sha: c89541a1af0add4b421acf58e62dc74382f6708a
bug_class: framework-internal
framework: bevy
framework_version: main@05cae875
files:
  - crates/bevy_sprite/src/lib.rs
  - crates/bevy_text/src/font.rs
  - crates/bevy_text/src/lib.rs
  - crates/bevy_ui/src/lib.rs
change_summary: >
  Font instance loading happens one frame after a font-size change
  is observed. The text renderer dropped the previous instance
  before the new one was ready, producing one frame with zero
  glyphs. The fix keeps the previous instance live until the new
  one finishes loading, eliminating the visual gap.
```

## Upstream Snapshot
- **Repo**: https://github.com/bevyengine/bevy
- **SHA**: c89541a1af0add4b421acf58e62dc74382f6708a
- **Relevant Files**:
  - crates/bevy_text/src/font.rs
  - crates/bevy_text/src/lib.rs
  - crates/bevy_sprite/src/lib.rs
  - crates/bevy_ui/src/lib.rs

## Flywheel Cell
primary: framework-maintenance.game-engine.code-navigation
secondary:
  - framework-maintenance.game-engine.captured-glyph-atlas-trace

## Difficulty Rating
4/5

## Adversarial Principles
- visual-symptom-only-user-report
- bug-only-fires-during-continuous-input-not-on-single-events
- bug-is-async-load-window-not-render-bug

## How OpenGPA Helps

A frame capture during a drag shows that the text quad's bound
texture is the *new* (still-empty) glyph atlas, while the previous
frame's capture had the *old* (filled) atlas. The diff highlights
that the text renderer switched to a new texture before that
texture had any contents. That is direct evidence of "rebound the
asset before it was ready" — pointing at the font-instance
lifecycle in `bevy_text/src/font.rs` rather than at the text
rendering code or the UI layout.

## Source
- **URL**: https://github.com/bevyengine/bevy/issues/23004
- **Type**: issue
- **Date**: 2026-04-02
- **Commit SHA**: 8d55916d2933586b266ada76b82873b88897f776
- **Attribution**: Reported in issue #23004; fix in PR #23190.

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
    - crates/bevy_text/src/font.rs
    - crates/bevy_text/src/lib.rs
  fix_commit: 8d55916d2933586b266ada76b82873b88897f776
```

## Predicted OpenGPA Helpfulness
- **Verdict**: yes
- **Reasoning**: The user report contains only "text vanishes
  during drag", no naming of fonts, atlases, or async loads. Grep
  on "text" or "drag" gives no useful localization. A capture
  diff between a stable frame and a drag frame highlights an
  empty glyph texture being bound — pointing the agent at font
  instance lifecycle code.

## Observed OpenGPA Helpfulness
- **Verdict**: ambiguous
- **Evidence**: validation pending — code_only baseline not yet run.
