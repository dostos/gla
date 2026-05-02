# R10: Polygon rendered from dynamic GeoJSON source has missing portions

## User Report
This is a non-dynamically rendered polygon, it is normal.

This is a dynamically rendered polygon. You can clearly see that part of
the polygon is missing. Zooming in will reveal a more obvious missing
part.

(Screenshots in the upstream issue show a filled administrative boundary
polygon rendered from a Mapbox GL JS GeoJSON source. With `dynamic: false`
the fill is complete; with `dynamic: true` chunks of the interior are
unfilled. A CodePen is attached.)

Follow-up comments ask whether there is any progress and note a workaround
of converting fill layers to use a non-dynamic source.

## Expected Correct Output
A continuous filled polygon with no interior gaps, matching the
non-dynamic rendering of the same GeoJSON feature.

## Actual Broken Output
The filled polygon has visible unfilled strips, most prominently along
internal seams where re-tiled sub-regions meet. Zooming in makes more
seams visible.

## Ground Truth
No maintainer diagnosis, fix PR, or commit exists in the upstream thread
at the time of drafting; the issue is open and unresolved. The only
authoritative signal comes from the reporter:

> This is a dynamically rendered polygon. You can clearly see that part
> of the polygon is missing. Zooming in will reveal a more obvious
> missing part.

The symptom reported is therefore: a fill rendered from a GeoJSON source
with `dynamic: true` is missing interior portions that are present when
the same source is used with `dynamic: false`. The two render paths
differ only in the dynamic flag, so the defect is isolated to the
dynamic-source fill pipeline — the component that re-tiles and
re-triangulates features as the camera moves. A plausible failure in
that pipeline is coordinate quantization drift between adjacent
re-generated tiles, which leaves hairline gaps along shared edges where
two tiles' triangulations should have produced coincident vertices. The
minimal reproducer in `main.c` ports that pattern: two tile-like patches
whose shared edge is almost, but not exactly, colinear.

Because no upstream maintainer has confirmed this mechanism, the above
is a best-effort model of the symptom rather than a verified root cause.
Scoring should reward agents that correctly identify the missing-fill
symptom and surface the seam pattern via OpenGPA; it should NOT require
the agent to name a specific internal Mapbox function.

See https://github.com/mapbox/mapbox-gl-js/issues/13299 for the full
thread.

## Difficulty Rating
4/5

## Adversarial Principles
- unresolved_upstream_bug
- tile_seam_quantization

## How OpenGPA Helps
`GET /frames/current/overview` shows the two draw calls (one per tile
patch), and `POST /frames/current/pixel` sampled along the seam returns
the background clear color instead of the fill color, localising the
gap to the shared tile edge rather than a shader or blending issue.

## Source
- **URL**: https://github.com/mapbox/mapbox-gl-js/issues/13299
- **Type**: issue
- **Date**: 2024-10-10
- **Commit SHA**: (n/a)
- **Attribution**: Reported by @ADS-PAN

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
  region:
    x: 254
    y: 200
    width: 4
    height: 200
  expected_dominant_rgba: [25, 102, 229, 255]
  tolerance: 8
  max_background_fraction: 0.05
```

## Predicted OpenGPA Helpfulness
- **Verdict**: ambiguous
- **Reasoning**: OpenGPA can confirm the gap is background-colored (not
  a shader/blend bug) and show the two tile draw calls have
  non-coincident shared-edge vertices. But without upstream source for
  the Mapbox dynamic-tiling pipeline, the agent cannot name the
  offending internal function — only describe the mechanism.

## Observed OpenGPA Helpfulness
- **Verdict**: ambiguous
- **Evidence**: validation skipped (--no-validate)
