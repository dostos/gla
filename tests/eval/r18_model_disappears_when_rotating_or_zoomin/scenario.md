# R18: Model disappears when rotating or zooming the map

## User Report
**mapbox-gl-js version**: v3.9.1 / Chrome 131

When I rotate or zoom the map, the model disappears. How can I set it so
that the model remains visible on the map and is not affected by map
rotation or zooming?

A follow-up reporter posted a JSBin with a single GLB placed on the map:
the model (a building) disappears at higher zoom levels and after
rotation. The original reporter also notes four model instances placed at
distinct lng/lat points; tilting the map after zoom/rotate makes
individual instances vanish intermittently.

## Expected Correct Output
When the map is rotated, zoomed or tilted, each model should remain
visible on screen as long as any part of its geometry intersects the
view frustum. Models whose anchor point drifts slightly off-screen but
whose body still overlaps the viewport should continue to render.

## Actual Broken Output
Models disappear the moment their anchor point leaves the viewport /
current tile, even though the model's geometry still extends into view.
The effect is most pronounced when:
- the GLB's mesh is offset from its local-space origin (the pivot),
- the camera is pitched so that the anchor point is behind the visible
  region but the tall geometry leans forward into it.

## Ground Truth
The model layer culls per instance using only the instance's anchor point
(the lng/lat the feature is placed at), not the model's world-space
bounding volume. When an instance's anchor point falls outside the
currently-rendered tile set — which happens under rotation, zoom and
pitch even if the mesh itself still overlaps the viewport — the draw
call for that instance is skipped entirely, so the model pops out of
view.

Maintainer @jtorresfabra (Mapbox) confirmed this directly for the
single-GLB case:

> In your case the model is displaced from the center of the local axis.
> Then when you place the object the point used is the one referencing
> the center, so when this goes out of the screen the model is culled.
> I would recommend to set the center of the model to the center of the
> local axis to avoid your model getting culled.

And on the required invariant for staying visible:

> The idea would be that the center point stays in the same tile as the
> maximum zoom tileID you are allowing.

A fix for the multi-instance variant of the same culling pattern was
merged; see the issue thread (`Comment 10`: "A fix has been merged and
will be available on the next release.") on
https://github.com/mapbox/mapbox-gl-js/issues/13384.

## Difficulty Rating
3/5

## Adversarial Principles
- silent_cull
- anchor_vs_extent_mismatch
- visually_plausible_disappearance

## How OpenGPA Helps
An OpenGPA draw-call listing for the broken frame shows that the model's
draw call is absent even though the framebuffer region where it should
appear is still the clear color. Comparing to a frame captured before
the rotation reveals a missing `glDrawArrays`/`glDrawElements` for that
instance, pointing the agent at host-side culling rather than at a
shader or depth issue.

## Source
- **URL**: https://github.com/mapbox/mapbox-gl-js/issues/13384
- **Type**: issue
- **Date**: 2025-01-09
- **Commit SHA**: (n/a)
- **Attribution**: Reported by @zrnwsy; single-model variant reported by @geografa; diagnosis by @jtorresfabra

## Tier
core

## API
opengl

## Framework
none

## Bug Signature
```yaml
type: missing_draw_call
spec:
  expected_region:
    x: 256
    y: 128
    width: 256
    height: 256
  expected_min_draw_calls: 1
  observed_draw_calls: 0
```

## Predicted OpenGPA Helpfulness
- **Verdict**: yes
- **Reasoning**: The symptom (object vanishes) maps cleanly to a
  missing-draw-call signal. OpenGPA's per-frame draw-call inventory and
  frame-to-frame diff make "the draw call for this object is gone"
  trivially visible, whereas the agent staring at pixels alone would
  struggle to distinguish CPU-side culling from shader/alpha/depth
  failures.

## Observed OpenGPA Helpfulness
- **Verdict**: ambiguous
- **Evidence**: validation skipped (--no-validate)
