# R14: Godot 3D editor axes flicker on negative half when zoomed far out

## User Report

The reporter is in the Godot 3D editor view. They zoom the editor
camera quite far out, then start orbiting. The negative half of
each 3D axis line (the line that goes into negative X, negative Y,
or negative Z space) flickers in and out — sometimes drawing
correctly, sometimes invisible. The positive halves remain solid.

Two additional clues from the report:
- "if you stop the camera movement while an axis is invisible,
  it stays that way" — i.e. the invisibility is sticky once it
  triggers
- works fine in 4.2.1, broken from 4.3.dev4 onwards

Repro:
1. Open the 3D editor.
2. Zoom out a fair amount.
3. Move the camera (orbit, pan).
4. Watch the negative halves of the X/Y/Z axis gizmo lines flicker.

## Expected Correct Output

Both halves of every axis line render at any camera distance and
under any camera motion. The negative half should look exactly
the same as the positive half, just mirrored.

## Actual Broken Output

When the camera is far enough away that the axis lines are very
long, the negative half of each axis disappears and reappears
intermittently as the camera moves. The positive half is unaffected.

## Ground Truth

Per the fix PR ("Fix 3d axes flickering in the negative direction
when extremely zoomed out"):

> When zooming out in the 3d node editor view, the negative half
> of all 3d axes starts flickering upon moving the camera. To fix
> this, the logic surrounding 3d transform "scaled" and
> "translated" calls has been altered so as to account for
> negative distance values.
>
> Fixes #89215.

The editor builds the axis-line geometry by computing a positive
"length to camera" distance and then constructing a transform
that scales a unit segment to that length and translates it.
For the negative half, the same length is used with a negated
direction — but the order of `.scaled(...).translated(...)`
applied negative scale via positive translate, which under
floating-point rounding produced an endpoint occasionally
*behind* the camera. That endpoint failed near-plane clipping
on a single frame, dropping the line entirely.

See https://github.com/godotengine/godot/pull/90255 (fixes
#89215).

## Fix
```yaml
fix_pr_url: https://github.com/godotengine/godot/pull/90255
fix_sha: dfcf803724a03af5685de2b58f8fafb62e951569
fix_parent_sha: 9d6bdbc56e0ac99a6cc3aaed1c114a6528cb87fc
bug_class: framework-internal
framework: godot
framework_version: 4.3.dev4
files:
  - editor/plugins/node_3d_editor_plugin.cpp
change_summary: >
  The editor's axis-line builder constructed the negative-half
  transform by scaling then translating a unit segment, with the
  scale assumed positive. Under far camera distances the negative
  half ended up with a transform that, due to floating-point
  precision, produced an endpoint slightly behind the camera's
  near plane on some frames — clipping the entire line. The fix
  rewrites the transform construction to handle negative
  distance values explicitly so the endpoint never crosses the
  near plane.
```

## Upstream Snapshot
- **Repo**: https://github.com/godotengine/godot
- **SHA**: 9d6bdbc56e0ac99a6cc3aaed1c114a6528cb87fc
- **Relevant Files**:
  - editor/plugins/node_3d_editor_plugin.cpp

## Flywheel Cell
primary: framework-maintenance.game-engine.code-navigation
secondary:
  - framework-maintenance.game-engine.captured-near-plane-clip

## Difficulty Rating
3/5

## Adversarial Principles
- bug-lives-in-editor-tooling-not-runtime-renderer
- only-the-negative-half-flickers-positive-half-fine
- floating-point-precision-bug-not-logic-bug

## How OpenGPA Helps

A capture during the flickering shows the editor's gizmo draw
call with two line segments per axis. On the broken frame, the
negative-half segment's clip-space endpoints reveal one vertex
with w<=0 (i.e. behind the camera), causing the line to be
trivially clipped. On a working adjacent frame, both endpoints
are in front of the camera. That single fact ("a gizmo line
endpoint sometimes lands behind the near plane") points the
agent at the gizmo geometry construction in the editor plugin,
not the renderer's clipping code.

## Source
- **URL**: https://github.com/godotengine/godot/issues/89215
- **Type**: issue
- **Date**: 2024-04-09
- **Commit SHA**: dfcf803724a03af5685de2b58f8fafb62e951569
- **Attribution**: Reported in godot#89215; fix in PR #90255.

## Tier
end-user-framing

## API
unknown

## Framework
godot

## Bug Signature
```yaml
type: code_location
spec:
  expected_files:
    - editor/plugins/node_3d_editor_plugin.cpp
  fix_commit: dfcf803724a03af5685de2b58f8fafb62e951569
```

## Predicted OpenGPA Helpfulness
- **Verdict**: yes
- **Reasoning**: The user's vocabulary is "axes flicker, only the
  negative direction, only when zoomed out" — no engine
  internals at all. A code_only agent could grep "axes" or
  "gizmo" and reach reasonable candidates, but those files are
  thousands of lines. With OpenGPA, capturing the per-vertex
  clip-space coordinates of the gizmo line on a flickering
  frame directly shows one endpoint at w<=0 — narrowing the
  question from "what causes flicker" to "what code constructs
  this line's endpoint".

## Observed OpenGPA Helpfulness
- **Verdict**: ambiguous
- **Evidence**: validation pending — code_only baseline not yet run.
