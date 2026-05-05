# R59_MATRIX4_NAN_WITH_ZERO_SCALE: NaN propagates from zero-scaled meshes' matrices

## User Report
I'm hiding objects in my scene by setting `mesh.scale.set(0, 0, 0)` instead
of `mesh.visible = false`, so I can animate the scale back up later. After
applying a scale of zero, my scene's other objects start to flicker, and
child objects of the zero-scaled mesh end up rendered at random positions
in world space.

Looking at the matrices, the world matrix of the zero-scaled mesh contains
NaN values, and the NaN propagates into anything that reads from its matrix
(children, look-at targets, downstream physics).

A scale of `0.0001` instead of `0` works fine. So it seems the math
pipeline can't handle a 0-determinant matrix without producing NaN.

Reproduction steps:
1. `mesh.scale.set(0, 0, 0)` then `mesh.updateMatrixWorld(true)`.
2. Inspect `mesh.matrixWorld.elements` — every entry is NaN.
3. Any child of the mesh, or any object that copies/reads from this matrix,
   is also corrupted.

Version: r180. Browser: Chrome. OS: Linux.

## Expected Correct Output
With `mesh.scale.set(0, 0, 0)`, the mesh should collapse to a point and
its world matrix should remain finite — typically the identity rotation
augmented with the (0,0,0) translation/scale, i.e. all 16 elements
finite. Children that inherit from this matrix should keep their own
finite local transforms and render at their own positions, not at NaN
coordinates. A center-pixel sample of a child's rendered output should
match what a 0.0001 scale on the parent produces — i.e. ~`(180, 180, 180)`
for a mid-bright diffuse plane.

## Actual Broken Output
With `mesh.scale.set(0, 0, 0)`, downstream code that reads
`mesh.matrixWorld` (children's `updateMatrixWorld`, physics colliders,
shadow culling, ray-casting bounds) consumes NaN values. The render
pipeline produces NaN-projected vertices that the GPU clamps to 0 (or
rejects entirely), so dependent meshes either render at the origin in
black or flicker in/out of the frustum frame-to-frame. Captured at the
GL level, the model-view-projection uniform `u_mvp` for any draw call
that descends from the zero-scaled node contains NaN entries.

## Ground Truth
`Matrix4.extractRotation()` divides each basis column by the column's
length to normalize. When a column has length zero (e.g. the matrix
came from `makeScale(0, 0, 0)`), the division yields `Infinity`, which
when written into the 4x4 result becomes NaN once subsequent
multiplications with finite columns happen. From the PR description:

> The Issue: Currently, `extractRotation` assumes the matrix columns
> (basis vectors) have a non-zero length. If an object has a scale of
> 0 on any axis (e.g., `mesh.scale.set(0, 0, 0)` to hide it), the
> column length becomes 0.
>
> This results in a division by zero (`Infinity`), causing the entire
> matrix to become `NaN`. This `NaN` propagation can crash downstream
> logic (physics engines, world matrix decompositions) that rely on this
> method.

PR #32440 ("Matrix4: Avoid `NaN` values when scale is zero") guards
both `extractBasis` and `extractRotation` with a `determinant() === 0`
check that returns the identity (or finite-default basis) when the
input matrix is degenerate. The fix touches one file:
`src/math/Matrix4.js`.

The minimal GL repro in `main.c` mirrors the same shape:

- A vertex shader transforms a triangle by a `mat4 u_mvp`.
- The host computes `u_mvp` by extracting the rotation from a parent
  matrix that was multiplied by `makeScale(0, 0, 0)` — i.e. it follows
  the buggy path.
- The resulting `u_mvp` contains NaN entries; the rasterized triangle
  is missing or rendered at incorrect coordinates; the center pixel
  reads the clear color instead of the geometry's diffuse.

## Fix
```yaml
fix_pr_url: https://github.com/mrdoob/three.js/pull/32440
fix_sha: 4dafda14e5d92fb98d40b54a13c5edb5fcb7a26f
fix_parent_sha: 4243f389d8877567857a7f93d8042ce074701272
bug_class: framework-internal
files:
  - src/math/Matrix4.js
change_summary: >
  Add a `determinant() === 0` guard to `Matrix4.extractBasis()` and
  `Matrix4.extractRotation()`. When the source matrix is degenerate
  (e.g. produced by `makeScale(0, 0, 0)`), the methods now return the
  identity rotation (or canonical basis vectors) instead of dividing by
  a zero column length and producing `Infinity`/`NaN` values that
  propagate through downstream world-matrix decompositions, physics,
  and rendering uniforms.
```

### Captured-literal breadcrumb (for GPA trace validation)
At reproduction time, the model-view-projection uniform `u_mvp` for any
draw call that descends from a `mesh.scale.set(0, 0, 0)` ancestor reads
back as a 4x4 matrix containing `NaN` entries (typically all 16 entries
are NaN once one column's length-0 division has propagated through the
matrix multiply chain). The correct value would be a finite matrix.
The "wrong literal" is the `NaN` itself — produced by the unguarded
`1.0 / 0.0` divide in `extractRotation`'s normalization step. The write
site that introduces the divide-by-zero is in `src/math/Matrix4.js`'s
`extractRotation()` and `extractBasis()` methods, where each basis
column is divided by `setFromMatrixColumn(...).length()` without
checking for zero. `gpa trace value NaN` (or `gpa trace value Inf` on
the intermediate column-length output) on a captured uniform routes the
agent to `Matrix4.js`. Filtered by call-site context (`extractRotation`
appears on the call stack of `mesh.matrixWorld` decomposition), the
high-confidence target is `Matrix4.extractRotation`. Without the
trace, the agent must read top-down from `Object3D.updateMatrixWorld`
through `decompose()` / `extractRotation()` to find the missing guard
— a 6-file source-logical search.

## Upstream Snapshot
- **Repo**: https://github.com/mrdoob/three.js
- **SHA**: 4243f389d8877567857a7f93d8042ce074701272
- **Relevant Files**:
  - src/math/Matrix4.js
  - src/math/Vector3.js
  - src/core/Object3D.js
  - src/core/Layers.js

## Difficulty Rating
4/5

## Adversarial Principles
- divide-by-zero-produces-Infinity-then-NaN
- NaN-propagates-through-matrix-multiplication
- symptom-is-flicker-not-divide-by-zero
- common-degenerate-input-from-user-API

## How OpenGPA Helps
Capturing the per-draw-call `u_mvp` uniform shows NaN values for any draw
descended from the zero-scaled ancestor — an immediate breadcrumb that a
divide-by-zero happened upstream of the matrix upload. A
`gpa trace value NaN` on the captured uniform routes back to the source
that produces the matrix; combined with the call-stack context for
`Matrix4.extractRotation`, this surfaces the missing degenerate-matrix
guard in one file. Without the trace, the agent must read several
files in the math + Object3D pipeline to find the unguarded divide.

## Source
- **URL**: https://github.com/mrdoob/three.js/pull/32440
- **Type**: pull_request
- **Date**: 2025-11-21
- **Commit SHA**: 4dafda14e5d92fb98d40b54a13c5edb5fcb7a26f
- **Attribution**: Reported and fixed by @bigotry in PR #32440; merged by @Mugen87.

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
  actual_rgb:   [0, 0, 0]
  tolerance: 24
  note: >
    Center pixel of a triangle rendered through an MVP that descended
    from a zero-scale ancestor matrix. Expected the diffuse mid-gray
    color; broken path produces NaN-filled MVP, the GPU clamps NaN-
    transformed vertices off-screen, and the center pixel reads the
    clear color.
```

## Predicted OpenGPA Helpfulness
- **Verdict**: yes
- **Reasoning**: The captured uniform value contains `NaN` — the
  smoking gun. Reverse-searching `NaN`/`Inf` against the framework
  source surfaces `Matrix4.extractRotation` as the unguarded divide-by-
  zero site. Without the trace, the agent has to read top-down from
  `updateMatrixWorld` to find the propagation path — exactly the
  source-logical search that R10 showed to be slow.
