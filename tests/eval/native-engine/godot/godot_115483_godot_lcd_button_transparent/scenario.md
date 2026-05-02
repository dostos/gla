# R14: Godot duplicated Button with stylebox texture renders fully transparent

## User Report

The reporter creates a `Button`, sets a custom font (with subpixel
text antialiasing) in its theme overrides, and assigns a PNG with
a semi-transparent background as the Normal stylebox. The first
button in the scene looks correct: visible, semi-transparent
background, crisp text.

They duplicate the button. The duplicate (and any subsequent
duplicates) renders the same text correctly but the stylebox
background is **fully transparent**, not semi-transparent. Only
the very first button in the scene shows its background.

This worked correctly in Godot 4.5.1; broken in 4.6.

Repro:
1. Import a font and set its antialiasing mode to subpixel.
2. Create a `Button`, set the font in theme overrides, and a
   `StyleBoxTexture` with a semi-transparent PNG as Normal.
3. Verify the first button looks right (semi-transparent bg).
4. Duplicate the button. The copy has fully transparent bg.
5. Adding more copies — same result: only the first one
   keeps its background.

## Expected Correct Output

Every `Button` (regardless of duplication order) draws its
configured `StyleBoxTexture` background with the correct alpha
value sampled from the source texture, then draws the font glyphs
on top.

## Actual Broken Output

The second and later buttons skip drawing the stylebox texture
background entirely (or write it with alpha 0), leaving the area
behind the text fully transparent.

## Ground Truth

Per the fix PR ("Fix LCD batching flag for StyleBoxTexture"):

> Fixes https://github.com/godotengine/godot/issues/115483
> Similar to this solution: #113924 except it's `use_lcd` and not
> `use_msdf`.

The canvas renderer batches consecutive items into a single draw
call when their state matches. A flag indicating whether the
batch's content uses subpixel-alpha glyph rendering was getting
"stuck on" after the first text glyph batch, so subsequent
batches that contained pure-image stylebox textures were drawn
with the wrong batched-state, causing the texture's alpha to be
treated as if it were the secondary alpha channel of subpixel
text — effectively zero everywhere. The fix resets the flag at
the boundary between text and non-text batches.

See https://github.com/godotengine/godot/pull/116647 (fixes
#115483).

## Fix
```yaml
fix_pr_url: https://github.com/godotengine/godot/pull/116647
fix_sha: 69a412afcd53dfa360d91e7993205bdc40951645
fix_parent_sha: a3e84cc2af14aa4cffbefd8e13492e59567a64e3
bug_class: framework-internal
framework: godot
framework_version: 4.6.stable
files:
  - servers/rendering/renderer_rd/renderer_canvas_render_rd.cpp
change_summary: >
  The canvas renderer's per-batch state tracking left a "this batch
  used subpixel text rendering" flag set after a text-glyph batch
  ended, so the next stylebox-texture batch inherited the wrong
  shader path that treats the texture's alpha channel as a coverage
  mask rather than as a real alpha — effectively rendering the
  background fully transparent. The fix clears the flag when the
  batch's drawable content changes from text to image.
```

## Upstream Snapshot
- **Repo**: https://github.com/godotengine/godot
- **SHA**: a3e84cc2af14aa4cffbefd8e13492e59567a64e3
- **Relevant Files**:
  - servers/rendering/renderer_rd/renderer_canvas_render_rd.cpp

## Flywheel Cell
primary: framework-maintenance.game-engine.code-navigation
secondary:
  - framework-maintenance.game-engine.captured-state-leak-across-batches

## Difficulty Rating
4/5

## Adversarial Principles
- bug-is-cross-batch-state-leak-not-per-button-state
- first-instance-renders-correctly-only-duplicates-break
- subpixel-text-vocabulary-leaks-via-title-not-body

## How OpenGPA Helps

A frame capture of the broken case shows two consecutive draw
calls: one rendering the first button (with state X), one
rendering the duplicate (with state X' but expected to be Y).
Inspecting the bound shader / pipeline / per-batch uniforms
reveals that the second draw inherited the first's "use lcd"
flag even though it draws a stylebox image, not text. Diffing
the per-batch state against a working pre-4.6 capture (where
the duplicate looked correct) directly highlights the leaked
flag.

## Source
- **URL**: https://github.com/godotengine/godot/issues/115483
- **Type**: issue
- **Date**: 2026-02-23
- **Commit SHA**: 69a412afcd53dfa360d91e7993205bdc40951645
- **Attribution**: Reported in godot#115483; fix in PR #116647.

## Tier
end-user-framing

## API
vulkan

## Framework
godot

## Bug Signature
```yaml
type: code_location
spec:
  expected_files:
    - servers/rendering/renderer_rd/renderer_canvas_render_rd.cpp
  fix_commit: 69a412afcd53dfa360d91e7993205bdc40951645
```

## Predicted OpenGPA Helpfulness
- **Verdict**: yes
- **Reasoning**: The reporter's wording is "duplicated button has
  fully transparent background instead of semi-transparent". A
  code_only agent has no way to know the cause is shared-state
  batching across draw calls — they'd plausibly investigate
  `Button`, theme overrides, or stylebox copy semantics. With a
  frame capture, the agent sees two adjacent draws on the
  canvas pipeline whose only state delta is a single per-batch
  flag, and that flag's name (`use_lcd`) directly points at
  the canvas renderer batch logic — past the entire UI layer.

## Observed OpenGPA Helpfulness
- **Verdict**: ambiguous
- **Evidence**: validation pending — code_only baseline not yet run.
