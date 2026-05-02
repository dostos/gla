# R2_WEBGPURENDERER_MISSING_EXT_CLIP_CONTROL: Reversed-Z projection without clip-control fallback

## User Report
### Description

I discovered yesterday the `WebGPURenderer { reverseDepthBuffer : true}` in
webgl was breaking on Firefox (linux & mac at least) on all instance, making
them disapear, not sure if it's a known bug but it was easy to reproduce on
my mac with `forceWebGL`.

It just silently made all the instance disappear without any error.

### Reproduction steps

1. Instance + reverse Depth Buffer : disapear

### Live example

super simple example: https://jsfiddle.net/xsjcqvdg/1/

### Version

r182.1

### Device

Desktop

### Browser

Firefox

### OS

MacOS

## Expected Correct Output
A single red triangle centered on a dark background, lit by the
reversed-Z depth configuration (near plane -> window z = 0, far plane ->
window z = 1; `GL_GREATER` vs cleared `0.0` lets in-frustum geometry pass).

## Actual Broken Output
Geometry that the application expects to render silently fails to appear
(or appears with completely inverted depth ordering) because the
clip-space depth range the projection was designed for does not match
the one the driver is actually using, and no fallback to a
non-reversed-depth pipeline is taken.

## Ground Truth
The upstream report describes the exact failure mode:

> I discovered yesterday the `WebGPURenderer { reverseDepthBuffer : true }`
> in webgl was breaking on Firefox (linux & mac at least) on all
> instance, making them disapear [...] It just silently made all the
> instance disappear without any error.

and the maintainer confirms the root cause in a follow-up comment:

> `WebGLRenderer` only works because it falls back to a non-reversed
> depth buffer. `EXT_clip_control` is not supported in Firefox. So I
> guess we must fix the fallback in `WebGPURenderer`.

So the diagnosis is: `WebGPURenderer`'s WebGL backend uses a reversed-Z
projection that assumes clip-space depth `[0, 1]` via `EXT_clip_control`;
when the extension is missing (Firefox), the projection is interpreted
against the default `[-1, 1]` clip range and no fallback to a
conventional (non-reversed) depth path is taken, so geometry silently
disappears. The fix is to detect the missing extension and fall back to
a non-reversed-Z configuration, as `WebGLRenderer` already does.

## Difficulty Rating
4/5

## Adversarial Principles
- silent-failure (no GL error, geometry just vanishes)
- state-vs-shader-mismatch (projection math assumes a clip range that
  driver state does not enforce)
- capability-detection-gap (extension presence gates whole pipeline)

## How OpenGPA Helps
An OpenGPA query on the frame would show the draw call's depth state
(`clearDepth = 0.0`, `depthFunc = GL_GREATER`) together with the bound
projection uniform (reversed-Z, `[0,1]` style) and the *absence* of a
`glClipControl` call in the frame trace. The inconsistency between the
reversed-Z depth state and the default `NEGATIVE_ONE_TO_ONE` clip-space
configuration is exactly the kind of cross-state mismatch that is
invisible to a pure shader/uniform inspector but falls straight out of a
raw GL capture.

## Source
- **URL**: https://github.com/mrdoob/three.js/issues/33076
- **Type**: issue
- **Date**: 2025-10
- **Commit SHA**: (n/a)
- **Attribution**: Reported by a three.js user; diagnosis confirmed by a
  three.js maintainer in the issue thread.

## Tier
core

## API
opengl

## Framework
none

## Bug Signature
```yaml
type: unexpected_state_in_draw
spec:
  draw_call_selector: first
  required_absent_calls:
    - glClipControl
  required_state:
    DEPTH_TEST: GL_TRUE
    DEPTH_FUNC: GL_GREATER
    DEPTH_CLEAR_VALUE: 0.0
  rationale: >
    A reversed-Z depth configuration (clearDepth=0, depthFunc=GL_GREATER)
    combined with a [0,1]-style reversed-Z projection is only correct if
    glClipControl(GL_LOWER_LEFT, GL_ZERO_TO_ONE) has also been issued.
    The absence of any glClipControl call in the frame while these depth
    states are active is the signature of the missing-EXT_clip_control
    fallback bug.
```

## Predicted OpenGPA Helpfulness
- **Verdict**: yes
- **Reasoning**: The bug is a cross-cutting state inconsistency (depth
  test configuration vs. clip-space configuration vs. projection matrix)
  that produces no GL error and no visible shader defect. An LLM agent
  reading a raw capture can directly observe the missing `glClipControl`
  call alongside the reversed-Z clear/func values and the reversed-Z
  projection uniform, which points to the exact fallback fix the
  upstream maintainer describes.

## Observed OpenGPA Helpfulness
- **Verdict**: ambiguous
- **Evidence**: validation skipped (--no-validate)
