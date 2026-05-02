# R56_CONEGEOMETRY_HAS_WRONG_SIDE_FACES_AND: ConeGeometry has wrong side faces and triangles

## User Report
When creating the ConeGeometry, set the heightSegments up to a value greater
than 1 (example: 3), there is an error that side faces show only half of
faces and triangles — some triangles disappear.

Reproduction steps:
1. Create a cone geometry
2. Set the heightSegments to 3, others keep default
3. Check the side faces — there is an error

Code:
```js
const geometry = new THREE.ConeGeometry(1, 1, 32, 3);
const material = new THREE.MeshBasicMaterial();
const mesh = new THREE.Mesh(geometry, material);
```

Version: r169. Browser: Chrome. OS: Windows.

## Expected Correct Output
A cone with `radialSegments = 32` and `heightSegments = 3` should have a
fully-tessellated side surface: every horizontal strip between two height
rings should be composed of `32 * 2 = 64` triangles, and the total number
of indices on the side surface should be `64 * 3 * 3 = 576` (3 strips
because `heightSegments = 3`). A ray from the camera toward the cone's
side at roughly the midpoint height should hit a triangle and render as
the material's diffuse colour (e.g. mid-gray).

## Actual Broken Output
Approximately half of the side triangles are missing. The total number of
indices on the side surface collapses to `64 * 3 * 1 = 192` — only the
base strip gets both triangles per quad. A ray aimed at the middle height
strip passes through a gap and hits the background color instead of the
cone. The index buffer length captured at draw time is `192 * 2` (side +
cap) instead of the expected `576 + cap-count`.

## Ground Truth
`CylinderGeometry` (from which `ConeGeometry` derives) is parameterised by
`radiusTop`, `radiusBottom`, `radialSegments`, `heightSegments`. When
`radiusTop === 0` (cone apex), the loop that pushes side triangles in
`generateTorso()` skips the `(a, b, d)` triangle on the assumption that
the top of the quad has collapsed to a point — that skip is correct *only*
for the top-most height strip (`y === 0`), not for every height strip. The
existing condition was:

```js
if ( radiusTop > 0 ) {            // wrong: skips every strip, not just y=0
    indices.push( a, b, d );
    groupCount += 3;
}
if ( radiusBottom > 0 ) {         // wrong: skips every strip, not just y=last
    indices.push( b, c, d );
    groupCount += 3;
}
```

For `heightSegments >= 2`, this drops one triangle per quad on every strip
except the degenerate one, producing the "half the triangles missing"
pattern the reporter saw.

The fix: broaden the condition so the skip is applied only on the
degenerate strip:

```js
if ( radiusTop > 0 || y !== 0 )                     { indices.push( a, b, d ); ... }
if ( radiusBottom > 0 || y !== heightSegments - 1 ) { indices.push( b, c, d ); ... }
```

Maintainer-merged as PR #29728 ("CylinderGeometry: Fix case where triangles
are missing with multiple height segments"), touching exactly
`src/geometries/CylinderGeometry.js`, with a 4-line change.

The minimal GL repro in `main.c` stands up a simplified cone-like strip
geometry. The "broken" code path emits only one triangle per quad while
the "correct" path emits both; the rendered output of the broken variant
shows a striped missing-triangle pattern and the captured index buffer's
length matches the formula above.

## Fix
```yaml
fix_pr_url: https://github.com/mrdoob/three.js/pull/29728
fix_sha: c58511d0e95d5d63c672cd8020dd2a3bf6c102e3
fix_parent_sha: 8be6bed537fed7226fdfc5acb09f27a4bfca99ee
bug_class: framework-internal
files:
  - src/geometries/CylinderGeometry.js
change_summary: >
  In `CylinderGeometry.generateTorso()` (inherited by `ConeGeometry`),
  relax the guards on the two-triangle-per-quad side index emission so
  the degenerate-vertex skip is applied only on the single strip where
  the collapse actually happens — i.e. `radiusTop > 0 || y !== 0` and
  `radiusBottom > 0 || y !== heightSegments - 1`. Restores the full
  triangle count for all interior strips when `heightSegments >= 2`.
```

### Captured-literal breadcrumb (for GPA trace validation)
At reproduction time, the draw call for the cone side issues
`glDrawElements( GL_TRIANGLES, 192, GL_UNSIGNED_SHORT, 0 )` when it should
be `576` (for `radialSegments = 32`, `heightSegments = 3`). The captured
index-buffer length (`192 * sizeof(short) = 384` bytes) and the element
count `192` are the breadcrumbs. The write site that produces too few
indices is in `src/geometries/CylinderGeometry.js` — the `indices.push( a,
b, d )` and `indices.push( b, c, d )` calls guarded by the buggy
`radiusTop > 0` / `radiusBottom > 0` checks. `gpa trace value 192` (filtered
by "cone" context) wouldn't hit anything directly because 192 isn't a
literal in the source, but `gpa trace value 64` (the per-strip correct
triangle count in this parameterisation, and appears as `radialSegments *
heightSegments` products across the source) plus contextual reading of
`indices.push` blocks points to the same file. More usefully: a
`gpa trace value "indices.push"` string trace, combined with the observed
under-count, surfaces `CylinderGeometry.js` as the single write site. The
agent should notice the factor-of-2 shortfall in the captured index count,
compare to the expected formula `2 * radialSegments * heightSegments`, and
reverse-search to the source that writes indices per strip.

## Upstream Snapshot
- **Repo**: https://github.com/mrdoob/three.js
- **SHA**: 8be6bed537fed7226fdfc5acb09f27a4bfca99ee
- **Relevant Files**:
  - src/geometries/CylinderGeometry.js
  - src/geometries/ConeGeometry.js
  - src/core/BufferGeometry.js
  - src/core/BufferAttribute.js

## Difficulty Rating
4/5

## Adversarial Principles
- guard-condition-too-strict
- symptom-is-missing-triangles
- numeric-count-mismatch-buffer-length
- only-triggers-with-heightsegments-gt-1

## How OpenGPA Helps
A `gpa report` on the broken frame shows the cone's draw call issuing
`glDrawElements(GL_TRIANGLES, count = 192, ...)`. Comparing to the
expected count for the given `radialSegments` / `heightSegments`
immediately reveals the factor-of-2 under-emission. From there the agent
reverse-looks-up which source writes `indices.push` for a
`CylinderGeometry`-like primitive — exactly one file.

## Source
- **URL**: https://github.com/mrdoob/three.js/issues/29721
- **Type**: issue
- **Date**: 2024-10-22
- **Commit SHA**: c58511d0e95d5d63c672cd8020dd2a3bf6c102e3
- **Attribution**: Reported by @jiff-2024 (three.js #29721); fixed by @WestLangley in PR #29728.

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
  region: { x: 128, y: 80, w: 1, h: 1 }
  expected_rgb: [160, 160, 160]
  actual_rgb:   [0, 0, 0]
  tolerance: 24
  note: >
    Pixel aimed at the cone's middle-height strip. Expected to hit one of
    the 64 quad triangles on that strip and return the diffuse gray;
    broken path emits only half the triangles so the ray passes through
    a gap and the pixel reads the background clear color.
```

## Predicted OpenGPA Helpfulness
- **Verdict**: yes
- **Reasoning**: The captured `glDrawElements(count=192)` literal is the
  direct breadcrumb. Reverse-searching the expected index-generation
  code routes to one file that owns the `indices.push` for cones and
  cylinders. The user-facing symptom — "some triangles disappear" —
  gives no source location.

## Observed OpenGPA Helpfulness
- **Verdict**: ambiguous
- **Evidence**: validation skipped (--no-validate)
