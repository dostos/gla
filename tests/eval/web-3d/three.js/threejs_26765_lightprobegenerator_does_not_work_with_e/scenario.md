# R16: LightProbeGenerator does not work with EXR files, only HDR

## User Report
I'm not entirely sure if I'm doing something wrong here, or running into a
bug. But it seems that `LightProbeGenerator` only works with specific data
types, and doesn't properly tell me what I need to pass it.

Reproduction:

1. Create a `WebGLCubeRenderTarget` with `format: RGBAFormat, type: FloatType`.
2. Call `cubeRenderTarget.fromEquirectangularTexture(renderer, exrTexture)`
   with an EXR (float) texture.
3. Call `LightProbeGenerator.fromCubeRenderTarget(renderer, cubeRenderTarget)`.

With an HDR source (which decodes to `HalfFloatType` by default), SH
generation works. With an EXR source (which decodes to `FloatType`), the
console shows:

```
6x WebGL: INVALID_OPERATION: readPixels: buffer is not large enough for dimensions
```

and all returned SH coefficients are zero. I tried various combinations of
specifying and not specifying data types and formats, but can't get it to
work. (Older issue that was resolved by adding support for `HalfFloatType`:
#26765.)

Workaround I found: convert the EXR's `Float32Array` to a `Uint16Array` of
half-floats via `THREE.DataUtils.toHalfFloat` before uploading; then the
existing `HalfFloatType` code path in `LightProbeGenerator` is happy.

Version: r177. Browser: Chrome. OS: macOS.

## Expected Correct Output
`glReadPixels` succeeds and returns the color that was just rendered into
the `GL_RGBA32F` framebuffer attachment. Downstream code that averages the
readback buffer sees non-zero values corresponding to the shaded color
`(0.25, 0.5, 0.75, 1.0)`.

## Actual Broken Output
`glReadPixels` generates `GL_INVALID_OPERATION` and leaves the destination
buffer untouched (all zeros). Any consumer that treats the readback as
valid data produces a zero result — for the three.js scenario, all nine
spherical-harmonic coefficients are zero and the light probe contributes
no illumination.

## Ground Truth
`LightProbeGenerator.fromCubeRenderTarget` allocates its readback buffer
assuming the cube render target uses `HalfFloatType` (a `Uint16Array` of
4 components per texel). When the render target was created with
`type: THREE.FloatType`, each texel is 16 bytes on the GPU side, and the
WebGL2 `readPixels(..., format, type, dst)` call requires either a matching
`Float32Array` destination or a buffer at least as large as the
implementation-expected size. The mismatched `Uint16Array` is half the
required byte length, so WebGL rejects the call with
`INVALID_OPERATION: readPixels: buffer is not large enough for dimensions`
and never writes any pixels, leaving the SH projection with zeroed input.

> `LightProbeGenerator.fromCubeRenderTarget()` does not support
> `THREE.FloatType` for input textures. So it's actually a similar issue
> compared to https://github.com/mrdoob/three.js/issues/26765. I'll file
> a PR with a fix.

The linked prior issue #26765 exhibits the symmetric failure mode: a
`HalfFloatType` render target being read into a `Float32Array`
(`WebGL: INVALID_OPERATION: readPixels: type HALF_FLOAT but ArrayBufferView
not Uint16Array`). Both are manifestations of the same class of bug: the
readback buffer's element type and byte length must be chosen from the
render target's actual `type`, not assumed.

## Difficulty Rating
3/5

## Adversarial Principles
- error-state-silently-ignored
- wrong-pixel-format
- assumption-of-fixed-input-type

## How OpenGPA Helps
A query for the GL error state after the draw/readback sequence surfaces
the `GL_INVALID_OPERATION` that the JavaScript `console.error` log makes
visible in the browser but that silent frameworks can swallow. A pixel
query on the color attachment shows the rendered color is present on the
GPU, so the agent can localize the fault to the readback step rather than
to the shader or the framebuffer attachment.

## Source
- **URL**: https://github.com/mrdoob/three.js/issues/31347
- **Type**: issue
- **Date**: 2025-07-07
- **Commit SHA**: (n/a)
- **Attribution**: Reported by a three.js user; confirmed and fix PR
  promised by @Mugen87 in the issue thread.

## Tier
core

## API
opengl

## Framework
none

## Bug Signature
```yaml
type: unexpected_color
spec:
  region: center
  expected_nonzero: true
  tolerance: 0.01
  channel: any
```

## Predicted OpenGPA Helpfulness
- **Verdict**: yes
- **Reasoning**: The bug is a single GL error on a single call. OpenGPA's
  per-draw-call error log and readback-buffer inspection make the mismatch
  between the attachment's internal format (`RGBA32F`) and the
  `readPixels` type (`HALF_FLOAT`) directly observable, without requiring
  the agent to instrument the app or reproduce the browser console.

## Observed OpenGPA Helpfulness
- **Verdict**: ambiguous
- **Evidence**: validation skipped (--no-validate)
