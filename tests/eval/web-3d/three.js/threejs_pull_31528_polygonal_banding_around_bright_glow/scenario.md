# R60_POLYGONAL_BANDING_AROUND_BRIGHT_GLOW: Bloom-style glow looks blocky instead of round

## User Report
I have bright emissive geometry on a dark background under WebGPURenderer
postprocessing. The bright halo around the emissive should fall off
smoothly (a soft glow), but instead it has visible polygonal banding —
concentric square-shaped tiers around the bright source. Same scene with
WebGLRenderer's UnrealBloomPass gives the round, smooth halo I expect.

It's not aliasing per se — it's that the glow's intensity steps down in
discrete bands instead of a smooth radial falloff. The brightest band is
a square the size of the kernel.

Reproduction steps:
1. WebGPURenderer + postprocessing pipeline with a bloom-style pass.
2. Render a small emissive sphere on a black background.
3. Look at the halo around the sphere — it's a stepped square instead of
   a smooth round glow.

Version: r182. WebGPURenderer. Browser: Chrome. OS: macOS.

## Expected Correct Output
Around an isolated bright pixel cluster the bloom halo should be radially
symmetric and smoothly falling off. Sampling a pixel at radius `r` from
the bright source should produce an intensity proportional to `exp(-r^2 /
(2 sigma^2))` — a Gaussian. At a fixed `r` between the bright source and
the kernel edge the intensity should match the analytic Gaussian to
within a few percent. For a mid-radius sample (e.g. 6 pixels off-center
with a kernel of radius 12) the expected intensity is ~`(60, 60, 60)`
± a few units (mid-grey halo).

## Actual Broken Output
The halo's iso-intensity contours are concentric squares. The brightest
ring is the size of the inner kernel; the second tier is the size of the
next mip level's kernel; etc. Mid-radius samples read either much higher
than the analytic Gaussian (when inside a kernel "tier") or near zero
(when outside). For a mid-radius sample at 6 pixels off-center the
captured pixel reads ~`(255, 255, 255)` or `(0, 0, 0)` depending on
which tier the pixel falls in — visibly stepped, not smooth.

## Ground Truth
A separable Gaussian blur kernel of "radius `R`" should use sigma `s = R
/ 3` so the kernel covers ±3 sigma — i.e. the bell curve has fully
decayed by the kernel's edge. The pre-fix three.js TSL bloom code used
`sigma = R` directly, which truncates the Gaussian at ±1 sigma instead.
Truncating that early discards ~70% of the bell-curve's area; the kernel
no longer approximates a Gaussian and instead produces a near-uniform
"box" blur whose iso-contours are squares (because the kernel's separable
1D pass is uniform). PR description:

> Both the gaussian blur-effects in use in the TSL-Nodes "BloomNode" and
> "GaussianBlurNode" look blocky, when they should be round. After
> reviewing the sources, i saw that `kernelRadius` was used directly as
> sigma for calculating the kernel, which is too big and truncates the
> bell-curve too early, leading to that blocky appearance.
>
> The common approach is to have a sigma*3 as kernelRadius, so as a
> minimal change i instead opted to calculate a proper sigma value as
> one third of the given kernelRadius.

The fix: introduce `sigma = kernelRadius / 3` and use it in the
coefficient formula `0.39894 * exp(-0.5 * i^2 / (sigma * sigma)) /
sigma`. Touches two files:
`examples/jsm/tsl/display/BloomNode.js` and
`examples/jsm/tsl/display/GaussianBlurNode.js`.

The minimal GL repro in `main.c` mirrors this directly: a separable
Gaussian-blur fragment shader whose host computes its kernel weights
using `sigma = kernelRadius` (broken) instead of `sigma = kernelRadius
/ 3` (correct). The blur applied to a single bright pixel produces
square iso-contours instead of round ones; the off-center sample reads
the wrong value.

## Fix
```yaml
fix_pr_url: https://github.com/mrdoob/three.js/pull/31528
fix_sha: bce9e96e3b97bf4e30beba6e98ef2cf80c2a08eb
fix_parent_sha: 95febf473cc326ac2029c51442b2fea3348c5321
bug_class: framework-internal
files:
  - examples/jsm/tsl/display/BloomNode.js
  - examples/jsm/tsl/display/GaussianBlurNode.js
change_summary: >
  Compute Gaussian blur coefficients with `sigma = kernelRadius / 3`
  instead of using `kernelRadius` directly as sigma. The pre-fix code
  truncated the bell curve at ±1 sigma, producing a near-uniform box
  blur whose iso-intensity contours are squares — the "blocky" halo
  the reporter observed. With the correct sigma the kernel covers ±3
  sigma and the falloff is the round Gaussian users expect. The change
  also removes the `weightSum` accumulator (the normalization is now
  baked into the coefficients) and adjusts BloomNode's kernel-size
  array to keep blur strength visually identical.
```

### Captured-literal breadcrumb (for GPA trace validation)
At reproduction time, the per-iteration coefficient uniform array
`gaussianCoefficients[i]` uploaded to the separable-blur fragment
shader contains values that are **too large** for what should be a
Gaussian of standard deviation sigma = `R/3`. Concretely: for `R = 5`
and `sigma_buggy = 5`, the central coefficient is
`0.39894 * exp(0) / 5 = 0.07979`. The correct central coefficient with
`sigma = 5/3 ≈ 1.667` is `0.39894 * exp(0) / 1.667 = 0.23936`. The
buggy uploaded value `0.07979` (and the corresponding shape of the
falloff ratio `coefs[i+1] / coefs[i] = exp(-0.5 * (2i+1) / R^2)` ≈
`exp(-(2i+1)/50)` — barely-decaying) is the captured literal. The
write site is the line `coefficients.push( 0.39894 * Math.exp( - 0.5
* i * i / ( kernelRadius * kernelRadius ) ) / kernelRadius )` in
`examples/jsm/tsl/display/BloomNode.js`'s `_getSeparableBlurMaterial`,
mirrored in `examples/jsm/tsl/display/GaussianBlurNode.js`.
`gpa trace value 0.07979` (or `0.39894`, the leading constant
`1/sqrt(2pi)`) on the project source surfaces these two files. The
agent, seeing the captured uniform's shape (a barely-decaying ramp
rather than the expected Gaussian bell), computes the implied sigma
from the falloff and notices it equals `kernelRadius`, not
`kernelRadius/3` — and lands on the BloomNode/GaussianBlurNode files.

## Upstream Snapshot
- **Repo**: https://github.com/mrdoob/three.js
- **SHA**: 95febf473cc326ac2029c51442b2fea3348c5321
- **Relevant Files**:
  - examples/jsm/tsl/display/BloomNode.js
  - examples/jsm/tsl/display/GaussianBlurNode.js
  - examples/jsm/postprocessing/UnrealBloomPass.js
  - src/nodes/display/PassNode.js

## Difficulty Rating
4/5

## Adversarial Principles
- gaussian-truncated-too-early-becomes-box-blur
- sigma-vs-radius-conflated-by-3x-factor
- symptom-is-shape-blocky-not-color-wrong
- post-process-far-from-source-of-bloom

## How OpenGPA Helps
A pixel-walk along a radial line from the bright source captures the
halo's intensity profile: it should be a smooth Gaussian falloff, but
it's piecewise-constant tiers. Capturing the per-iteration
`gaussianCoefficients` uniform on the separable-blur draw call shows
the actual coefficient values uploaded; computing the implied sigma
from `coefs[i] / coefs[0] = exp(-0.5 i^2 / sigma^2)` reveals
sigma = kernelRadius, not kernelRadius/3. A `gpa trace value 0.39894`
filtered to the project source routes directly to BloomNode.js and
GaussianBlurNode.js — the two write sites of the bug. Without the
trace, the agent has to read the bloom pipeline top-down (PassNode →
BloomNode → blur shader) to find the kernel-coefficient computation.

## Source
- **URL**: https://github.com/mrdoob/three.js/pull/31528
- **Type**: pull_request
- **Date**: 2025-09-04
- **Commit SHA**: bce9e96e3b97bf4e30beba6e98ef2cf80c2a08eb
- **Attribution**: Reported and fixed by @donmccurdy in PR #31528 (BloomNode + GaussianBlurNode coefficient calculation).

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
  region: { x: 134, y: 128, w: 1, h: 1 }
  expected_rgb: [60, 60, 60]
  actual_rgb:   [255, 255, 255]
  tolerance: 24
  note: >
    Pixel 6 px right of an isolated bright source after a separable
    Gaussian blur with kernel radius 12. Expected the analytic Gaussian
    intensity (sigma = 4 → mid-falloff); broken path uses sigma = 12,
    barely decays inside the kernel, so the pixel is in the central
    "plateau" tier and reads near-saturated.
```

## Predicted OpenGPA Helpfulness
- **Verdict**: yes
- **Reasoning**: The captured per-coefficient uniform array shape
  uniquely identifies the implied sigma. Reverse-searching the
  `0.39894` constant or the captured coefficient ratios surfaces
  exactly the two TSL display nodes that author the bloom kernel. The
  user-visible symptom ("blocky glow") gives no source-file hint, and
  most agents would chase the wrong path (start at PassNode or
  WebGPURenderer's postprocessing) before reaching the kernel formula.
