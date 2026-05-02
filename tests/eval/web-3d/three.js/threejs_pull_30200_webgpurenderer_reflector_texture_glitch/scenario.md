# R58_WEBGPURENDERER_REFLECTOR_TEXTURE_GLITCH: WebGPURenderer reflector texture-repeat glitches when zooming

## User Report
Glitch appears when you zoom in and zoom out on a scene that contains a
`Reflector` (mirror) plus a textured `RepeatWrapping` model.
[screenshot 1] [screenshot 2]

If I comment out line 81 (the line that adds the model to the scene), the
glitch disappears. The reflector by itself is fine; only the combination
of reflector + model with `RepeatWrapping` triggers it.

Reproduction steps:
1. WebGPURenderer + a `Reflector` mirror surface + a textured model whose
   texture uses `RepeatWrapping` (e.g. a tiled floor inside the reflected
   scene).
2. The reflection pass renders the scene from the mirror's POV; then the
   main pass renders the scene from the camera's POV.
3. Zoom in/out continuously.

Live fiddle: https://jsfiddle.net/497y862v/19/

Version: r170. WebGPURenderer. Browser: Chrome. OS: macOS.

## Expected Correct Output
On a textured `RepeatWrapping` plane visible through the reflector mirror,
the reflected texture should remain stable as the camera zooms — its UV
transform is recomputed for each render pass so the reflected scene's
texture coordinates always match what the main pass would see for the same
camera state. A single-pixel sample of the reflected texture's center
should yield the texture color, e.g. an off-white roughly `(180, 180, 180)`
± a few units, regardless of zoom level.

## Actual Broken Output
The reflected texture jumps/snaps to a stale UV transform from a previous
render call within the same frame. Specifically: the reflection pass uses
the camera's matrix from the *previous* frame's main pass, so the texture
coordinates of the reflected geometry are derived from a stale uniform.
The visible artifact is a noticeable texture-coordinate "glitch" — bands
of repeated tile snap to the wrong place — that flickers as the camera
zooms.

In a captured frame, the *uniform value* uploaded for the texture's UV
transform matrix in the reflection pass equals the value from the prior
main pass. Both passes happen within the same `frame` (same `requestAnimationFrame`
tick), so a `FRAME`-granularity update bucket runs only once per frame
total — the second pass within the same frame keeps the first pass's
uniform.

## Ground Truth
WebGPURenderer's TSL nodes have an `updateType` field that determines
*when* the node's CPU-side `update()` callback runs. The valid values
include `NodeUpdateType.NONE` (never), `NodeUpdateType.FRAME` (once per
`requestAnimationFrame` tick — at most one update per frame, regardless
of how many `render()` calls happen inside that tick), `NodeUpdateType.RENDER`
(once per `render()` call), and `NodeUpdateType.OBJECT` (once per draw
call).

`TextureNode.setUpdateMatrix(value)` toggles whether the node owns a per-
frame UV transform matrix that is recomputed on the CPU and uploaded each
update. In r170 it was set to `FRAME`:

```js
setUpdateMatrix( value ) {
    this.updateMatrix = value;
    this.updateType = value ? NodeUpdateType.FRAME : NodeUpdateType.NONE;
    return this;
}
```

The Reflector's mirror pass calls `renderer.render(reflectedScene, mirrorCamera)`
INSIDE the user's main render loop — i.e. there are TWO `render()` calls per
single `requestAnimationFrame` tick. With `FRAME`-granularity, the second
render's TextureNode update is *skipped*, so the texture matrix uniform is
the value computed for the first (mirror) pass, not the actual camera's
view. The visible texture coordinates jump because the matrix never gets
re-computed for the second pass.

The fix is one character: change `FRAME` to `RENDER`. The maintainer
diagnosis from issue #30198:

> `Glitch appear when you zoom in and zoom out`
>
> Comment line 81 (not adding the model to the scene) and the glitch
> disappears.

PR #30200 ("TextureNode: Fix matrix update") flips the bucket so the
texture matrix uniform is recomputed for every `render()` call rather
than once per animation frame. After the fix the reflected texture stays
stable across both passes within the same animation frame.

The minimal GL repro in `main.c` mirrors the same shape: it does TWO
draw passes within a single frame. The first pass (mirror) computes a
texture matrix and uploads it to the uniform. The second pass (main)
should also recompute, but the `FRAME`-granularity update logic in this
repro emulates the bug by only updating on the first pass per frame —
the second pass keeps the stale uniform value, producing the wrong
sampled texel.

## Fix
```yaml
fix_pr_url: https://github.com/mrdoob/three.js/pull/30200
fix_sha: 9f3eb47c7a78cde8d6df05fe1ee85b1a8ebb1ada
fix_parent_sha: 3e6034a0fe6db50a5c779d5fe4128aec565e60fd
bug_class: framework-internal
files:
  - src/nodes/accessors/TextureNode.js
change_summary: >
  Change `TextureNode.setUpdateMatrix()` to assign `NodeUpdateType.RENDER`
  instead of `NodeUpdateType.FRAME` to `this.updateType`. The texture
  matrix uniform is recomputed once per `render()` call instead of once per
  animation-frame tick, so reflectors and other intra-frame multi-render
  setups see a fresh uniform on every pass instead of a stale value from
  a previous pass within the same `requestAnimationFrame` tick.
```

### Captured-literal breadcrumb (for GPA trace validation)
At reproduction time, the texture-matrix uniform uploaded for the second
(main) pass within a single `requestAnimationFrame` tick is identical to
the value uploaded for the first (mirror) pass, even though the camera
state has changed between them. Concretely: the captured uniform vec4
(top row of the texture matrix, 2D UV-transform variant) reads back as
`(s, 0, 0, t_mirror)` for *both* passes in the buggy build, where
`(s, t_mirror)` are the values the reflector's mirror camera computed.
The correct value for the main pass is `(s, 0, 0, t_main)` with
`t_main != t_mirror`. The "wrong" value the second pass reads is not a
literal in any source file — it's the result of `setUpdateMatrix`'s
dispatch logic running once per FRAME and writing once-per-tick. The
write site is `src/nodes/accessors/TextureNode.js`'s `setUpdateMatrix`
method (one-line: `this.updateType = value ? NodeUpdateType.FRAME :
NodeUpdateType.NONE`). `gpa trace value NodeUpdateType.FRAME` (or
`gpa trace value FRAME` filtered to the `nodes/accessors/` subtree)
surfaces exactly this site as the only location where a TextureNode's
update bucket is set to `FRAME`. Compared against the rest of the TSL
codebase (where `RENDER` is the standard for per-pass uniforms),
`TextureNode.js` is the outlier — exactly the file that the fix touches.

## Upstream Snapshot
- **Repo**: https://github.com/mrdoob/three.js
- **SHA**: 3e6034a0fe6db50a5c779d5fe4128aec565e60fd
- **Relevant Files**:
  - src/nodes/accessors/TextureNode.js
  - src/nodes/core/NodeUpdateType.js
  - examples/jsm/objects/ReflectorNode.js
  - src/renderers/common/Renderer.js
  - src/nodes/core/Node.js

## Difficulty Rating
4/5

## Adversarial Principles
- update-bucket-too-coarse-for-multi-pass-frame
- regression-only-with-reflector-or-cubecamera
- captured-uniform-equals-prior-pass-value
- cross-pass-stale-value-symptom

## How OpenGPA Helps
Capturing the texture-matrix uniform on the two consecutive `render()`
calls within a single frame and comparing them shows a byte-for-byte
match where the values must differ. A single
`gpa diff frame {N} frame {N+1}` filtered to uniform-value drift, plus
a `gpa trace value <captured-uniform-value>` reverse-search, surfaces
`TextureNode.js`'s `setUpdateMatrix` as the only source location whose
update-bucket assignment matches the FRAME-granularity behaviour.
Without the trace, the agent must read top-down from `Reflector` →
`Renderer` → TSL update logic to discover the bucket-mismatch — the
exact "source-logical" search the R10 round showed to be slow and
error-prone.

## Source
- **URL**: https://github.com/mrdoob/three.js/issues/30198
- **Type**: issue
- **Date**: 2024-12-24
- **Commit SHA**: 9f3eb47c7a78cde8d6df05fe1ee85b1a8ebb1ada
- **Attribution**: Reported by @hlx-23 (three.js #30198); diagnosed and fixed by @sunag in PR #30200.

## Tier
snapshot

## API
opengl

## Framework
three.js

## Bug Signature
```yaml
type: unexpected_color
spec:
  region: { x: 128, y: 128, w: 1, h: 1 }
  expected_rgb: [180, 180, 180]
  actual_rgb:   [70, 70, 70]
  tolerance: 32
  note: >
    Center pixel of a textured RepeatWrapping plane visible through a
    Reflector mirror, sampled on the second (main) render pass within
    the same animation frame. Expected the mid-bright tile color;
    broken path samples a different texel because the texture-matrix
    uniform was never updated for the second pass and still holds the
    mirror pass's value.
```

## Predicted OpenGPA Helpfulness
- **Verdict**: yes
- **Reasoning**: The user-visible symptom ("zoom glitch on a reflected
  texture") gives no source-file hint at all. The captured GL state shows
  two consecutive draw passes uploading the same texture-matrix uniform
  value where they must differ — an immediate breadcrumb that the matrix
  is being computed once per frame and read twice. Reverse-searching the
  TSL update-bucket constants surfaces `TextureNode.js`'s `setUpdateMatrix`
  as the single outlier file using `FRAME` instead of `RENDER`.
