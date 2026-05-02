# R20: MeshDepthMaterial depth map non-uniform with distant camera and tight near/far

## User Report
So I'm trying to render the depth map of a scene using three.js

An example can be found here: http://threejs.org/docs/#Reference/Materials/MeshDepthMaterial

The depth map looks good when the scene is setup carefully, for example:

```
camera.position.z = 30;
camera.near = 0.1;
camera.far  = 50;
object.position.z = 0;
```

However, if the camera is setup in some other ways, for example:

```
camera.position.z = 600;
camera.near = 550;
camera.far  = 650;
object.position.z = 0;
```

In the second example, the depth resolution is all taken up by the depth range from -45 to -50 in the world coordinate system. This means for -50 < objects.position.z < -45, you can still see grayscale values in the depth map. Anything that has depth ranging from -45 to 50 will appear completely white in the depth map...

Ideally, I would like to see depth values uniformly distributed in the -50 to 50 range.

Is there a way to get the depth map I want?
Is there a way to increase the precision of depth map?

Eventually, I would like to save the Depth Map of the three.js scene as a .png image on to local disk for some analysis. Methods that don't use three.js are also welcome. Thanks.

## Expected Correct Output
Four quads placed at evenly spaced world-space depths (z=0, -15, -30, -45) should produce four distinct grayscale shades covering a wide range of the 0..1 depth output.

## Actual Broken Output
All four quads render at near-identical grayscale values close to 1.0 (white). Only the quad nearest the far plane shows any visible gradient; the others are indistinguishable.

## Ground Truth
When the camera sits far from the origin (z=600) with a tight near/far pair (near=550, far=650), rendering a depth visualization shows nearly all fragments clamped to the same bright value. Objects spread evenly through the world-space depth range (z=0 down to z=-45) do not produce evenly-spaced grayscale values — most of the depth range is compressed into a thin slice near the near plane.

The depth buffer stores window-space depth, which is a non-linear function of eye-space z: roughly `z_win ≈ (f*(z_eye-n)) / (z_eye*(f-n))`. Precision is concentrated near the near plane, and the distribution depends on the ratio `far/near`, not the absolute size of the frustum. With near=550, far=650, the ratio is 650/550 ≈ 1.18 — very tight — and the camera is positioned such that the interesting object range (world z=0 to -45, i.e. eye-space distances 600 to 645) maps to roughly the last 30% of the 0..1 depth output but is itself squeezed because of the 1/z curve. The accepted Stack Overflow answer confirms the root cause indirectly:

> Together with MeshDepthMaterial and the logarithmicDepthBuffer flag, I can get pretty nice looking depth map with the weird camera setup.

The `logarithmicDepthBuffer` flag fixes the symptom by swapping in a log-space depth encoding (`gl_Position.z = log2(max(1e-6, 1.0 + w)) * Fcoef - 1.0`), which is specifically designed for scenes where the near plane is pushed far from the camera — exactly this case. A standard perspective projection does not have enough precision budget across this near/far ratio at this distance for a linear-looking depth map.

## Difficulty Rating
3/5

## Adversarial Principles
- depth_precision_non_linearity
- tight_near_far_ratio_far_from_origin
- visualization_vs_stored_representation

## How OpenGPA Helps
A query that samples fragment depth (`gl_FragCoord.z`) across the four drawn quads would return values clustered near 1.0, letting the agent see the compression directly. Comparing `depth_win` at known world-space depths against an expected linear mapping immediately flags the 1/z non-linearity rather than an application-level bug.

## Source
- **URL**: https://stackoverflow.com/questions/28206718/three-js-meshdepthmaterial-depth-map-not-uniformly-distributed
- **Type**: stackoverflow
- **Date**: 2015-01-28
- **Commit SHA**: (n/a)
- **Attribution**: Reported by Stack Overflow user (question id 28206718)

## Tier
core

## API
opengl

## Framework
none

## Bug Signature
```yaml
type: color_histogram_in_region
spec:
  region: full_frame
  channel: r
  expected_distribution: spread
  actual_distribution: clustered_high
  threshold: 0.9
  min_fraction_above_threshold: 0.8
```

## Predicted OpenGPA Helpfulness
- **Verdict**: yes
- **Reasoning**: The root cause is visible in raw framebuffer and depth-buffer data — a query that dumps depth values at known pixel locations reveals the non-linear clustering without any framework knowledge. Without OpenGPA, the developer has to mentally model the 1/z curve or enable an engine flag as a black box; with OpenGPA, the agent can directly inspect that `gl_FragCoord.z` is >0.99 for all four quads and reason from there.

## Observed OpenGPA Helpfulness
- **Verdict**: ambiguous
- **Evidence**: validation skipped (--no-validate)
