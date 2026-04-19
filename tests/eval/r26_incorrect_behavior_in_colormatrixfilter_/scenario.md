# R9_INCORRECT_BEHAVIOR_IN_COLORMATRIXFILTER_: pixi.js ColorMatrixFilter over-normalizes offset column in multiply mode

## User Report
### Expected Behavior

`ColorMatrixFilter.contrast(1, true)` produces the same matrix as
`ColorMatrixFilter.contrast(1, false)` when the current matrix is the
identity.

### Current Behavior

`ColorMatrixFilter.contrast(1, true)` produces a broken matrix that mostly
updates the brightness, even making dark colors brighter.

### Possible Solution

The core of the problem is in `ColorMatrixFilter._loadMatrix` which calls
`ColorMatrixFilter._colorMatrix` only when `multiply=true`. Then,
`_colorMatrix` divides the rightmost column (the offset) by 255. To be honest,
I don't understand the reasoning behind that normalization. I don't see any
other code that produces an offset that's in the range 0..255 that needs to
be normalized, and even if that existed, calling it only in multiply mode
doesn't seem correct.

Dropping the normalization fixes this bug, but I'm unsure about the side
effects of this change. I think fixing this safely also requires improving
the tests of the filter, to verify the effects of each method on the matrix.

### Steps to Reproduce

```js
const node = /* Some PIXI node, it doesn't matter */
const filter = new PIXI.filters.ColorMatrixFilter();
node.filters = [filter];
filter.reset(); /* Not necessary, but to clarify that we start with the identity matrix */
filter.contrast(1, true);
```

### Environment

- **`pixi.js` version**: Both 5.3 and 6.3
- **Browser & Version**: Chrome 101 (doesn't matter)
- **OS & Version**: Ubuntu 21.10 (doesn't matter)
- **Running Example**: https://www.pixiplayground.com/#/edit/NrJ3oM-_T-rL1gp0R98tY

## Expected Correct Output
`contrast(1, multiply=true)` starting from the identity matrix should
produce exactly the same uniform values as `contrast(1, multiply=false)`,
and therefore the same pixels. The non-multiply path stores offset `-128`,
which saturates any mid-bright input to black.

## Actual Broken Output
The multiply-mode path stores offset `-128 / 255 ~= -0.502`. Applied to an
input of RGB 0.7 the shader outputs `2*0.7 - 0.502 ~= 0.898` -- near-white
instead of black. "It mostly updates the brightness, even making dark
colors brighter," as the reporter describes.

## Ground Truth
The over-normalization lives in `_colorMatrix` at
`packages/filters/filter-color-matrix/src/ColorMatrixFilter.ts` L265-278
(pinned commit `45052e29c4`). The maintainer @bigtimebuddy confirmed the
divide is suspect:

> Seems like this should be converting offset `* 255`
>
> https://github.com/pixijs/pixijs/blob/45052e29c4bf58043a9972142b5750c9c722d53c/packages/filters/filter-color-matrix/src/ColorMatrixFilter.ts#L265-L278

The original reporter @rubenlg further argues the normalization is
altogether spurious, because no upstream helper ever produces offsets in
the `0..255` range that would need to be renormalized:

> `_colorMatrix` divides the rightmost column (the offset) by 255. To be
> honest, I don't understand the reasoning behind that normalization. I
> don't see any other code that produces an offset that's in the range
> 0..255 that needs to be normalized, and even if that existed, calling
> it only in multiply mode doesn't seem correct.

No fix had landed at the time of capture; the repro replicates the exact
matrix that pixi would upload as a uniform.

## Difficulty Rating
3/5

## Adversarial Principles
- silent_branch_divergence
- offset_column_normalization
- shader_uniform_scale_mismatch

## How OpenGPA Helps
`GET /api/v1/frames/current/draw_calls/0` exposes the full `m[20]` uniform.
An agent that inspects the values immediately sees the asymmetry: the
diagonal entries are integer-scale (`2.0`) while the offset-column entries
(`m[4]`, `m[9]`, `m[14]`, `m[19]`) are tiny fractions near `-0.502`. That
255x discrepancy is the signature of a single-branch normalization bug and
is essentially impossible to diagnose without seeing the uniform values
directly.

## Source
- **URL**: https://github.com/pixijs/pixijs/issues/8359
- **Type**: issue
- **Date**: 2022-05-11
- **Commit SHA**: 45052e29c4bf58043a9972142b5750c9c722d53c
- **Attribution**: Reported by @rubenlg; root-cause line identified by maintainer @bigtimebuddy

## Tier
core

## API
opengl

## Framework
none

## Bug Signature
```yaml
type: framebuffer_dominant_color
spec:
  region: full
  expected_rgb_max: [50, 50, 50]
  actual_rgb_min: [200, 200, 200]
  note: "expected clamped-black (offset -128 in non-multiply path) but buggy multiply-mode offset -0.502 produces near-white ~0.898"
```

## Upstream Snapshot
- **Repo**: https://github.com/pixijs/pixijs
- **SHA**: b44db4bc32a6e58611a6afe3c9492e02ab51b596
- **Relevant Files**:
  - src/filters/defaults/color-matrix/ColorMatrixFilter.ts  # base of fix PR #11925 (offset normalization)
  - packages/filters/filter-color-matrix/src/ColorMatrixFilter.ts

## Predicted OpenGPA Helpfulness
- **Verdict**: yes
- **Reasoning**: The bug manifests entirely as incorrect uniform values uploaded to the color-matrix shader. OpenGPA's draw-call inspection surfaces `m[20]` directly, and the 255x magnitude gap between diagonal and offset entries is a very legible diagnostic signature. Without OpenGPA an agent would need to instrument the JS filter or diff matrices between `multiply=true` / `multiply=false` paths manually.

## Observed OpenGPA Helpfulness
- **Verdict**: ambiguous
- **Evidence**: validation skipped (--no-validate)
