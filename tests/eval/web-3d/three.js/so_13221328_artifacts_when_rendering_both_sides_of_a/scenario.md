# R24: Artifacts when rendering both sides of a transparent sphere in a single pass

## User Report
I try to render both sides of a transparent object with three.js. Other
objects located within the transparent object should show too. Sadly I get
artifacts I don't know how to handle. Here is a test page:
https://dl.dropbox.com/u/3778149/webgl_translucency/test.html

Here is an image of the said artifact. They seem to stem from the underlying
sphere geometry.

Interestingly the artifacts are not visible for blending mode
THREE.SubtractiveBlending = 2.

Any help appreciated!

Alex

## Expected Correct Output
A smooth translucent blue sphere where the farther half of the sphere's
surface is visibly composited behind the nearer half, with no tessellation
streaks.

## Actual Broken Output
The sphere appears streaked with wedge-shaped artifacts following the
latitude/longitude grid of the underlying mesh. Switching blend mode to
subtractive blending (which does not depend on back-to-front order in the
same way) visually hides the artifact.

## Ground Truth
This is the classic self-transparency ordering problem in alpha-blended
rasterization. Blending a single-pass, double-sided mesh with `depthMask=true`
makes the result order-dependent on triangle emission order; the fix on the
upstream thread is architectural, not a state toggle:

> You need to render two transparent spheres -- one with
> `material.side = THREE.BackSide`, and one with
> `material.side = THREE.FrontSide`. Using such methods is generally required
> if you want self-transparency without artifacts

The accepted answer frames this as an unavoidable consequence of how
depth+blend interact on self-occluding geometry, not a bug in a specific
uniform or draw-state. The "fix" is splitting one draw call into two passes
with opposite cull-face state so back-facing triangles are composited before
front-facing ones.

## Difficulty Rating
3/5

## Adversarial Principles
- architectural-workaround-not-state-bug
- order-dependent-blending
- self-transparency-ordering

## How OpenGPA Helps
OpenGPA can confirm the draw state (blend enabled, depth-mask on, cull-face
off, single draw call for the sphere), which names the problem class. It
cannot point to a "wrong uniform" because the defect is the pipeline choice
itself — the correct remediation is adding a second draw call. This makes
OpenGPA's contribution diagnostic, not prescriptive.

## Source
- **URL**: https://stackoverflow.com/questions/13221328/artifacts-when-rendering-both-sides-of-a-transparent-object-with-three-js
- **Type**: stackoverflow
- **Date**: 2012-11-04
- **Commit SHA**: (n/a)
- **Attribution**: Reported by StackOverflow user Alex; accepted answer by WestLangley.

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
  draw_selector: "sphere_single_pass"
  required_state:
    GL_BLEND: enabled
    GL_DEPTH_TEST: enabled
    GL_DEPTH_WRITEMASK: true
    GL_CULL_FACE: disabled
  expected_remediation: "split into two draws: one with cull=front, one with cull=back"
```

## Predicted OpenGPA Helpfulness
- **Verdict**: ambiguous
- **Reasoning**: OpenGPA can surface the offending state combination (blend
  on + depth-write on + cull off in a single draw) which is a recognizable
  fingerprint of the self-transparency class. However, the upstream resolution
  is a pipeline restructure (two passes with opposite culling), not a value
  fix, so OpenGPA narrows the hypothesis space but does not hand the agent a
  one-line patch.

## Observed OpenGPA Helpfulness
- **Verdict**: ambiguous
- **Evidence**: validation skipped (--no-validate)
