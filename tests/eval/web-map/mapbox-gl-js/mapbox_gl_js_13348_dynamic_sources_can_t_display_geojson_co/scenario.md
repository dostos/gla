# R4_DYNAMIC_SOURCES_CAN_T_DISPLAY_GEOJSON_CO: Dynamic GeoJSON source renders corrupted features across tile boundaries

## User Report
Hi,
I noticed it's impossible to use dynamic sources, due to corrupted GeoJSON features display.

Latest maplibre version (3.8.0) and chrome version (131) are used.

```js
map.addSource('main', {
  dynamic: true,  // when "dynamic: false" is used all is OK
  type: 'geojson',
  data: {}
});
```

Almost all features I tried to display look corrupted. A follow-up commenter adds: "it appears to be a problem with fills and lines that span over multiple map tiles for any dynamic source. It will appear differently depending on your zoom level. With that in mind it shows up very consistently at high zoom levels."

A reproducing demo is attached: https://codepen.io/qwioefsd/pen/zxOKjrZ — toggling `dynamic` between true and false is the only change needed to swap broken vs correct rendering.

## Expected Correct Output
A GeoJSON polygon that spans several tiles should render as a single contiguous filled shape, indistinguishable from the same polygon rendered with `dynamic: false`.

## Actual Broken Output
The polygon renders as fragmented per-tile slivers: only the sub-polygon formed by the feature's vertices that fall inside each tile's AABB is drawn, producing visible seams along every tile boundary. Lines exhibit the same pattern. The corruption scales with zoom level because higher zooms increase the number of tile boundaries a feature crosses.

## Ground Truth
This scenario is not upstream-diagnosed. The maplibre/mapbox-gl-js thread contains multiple independent "same for me" reports and one symptom characterization:

> "it appears to be a problem with fills and lines that span over multiple map tiles for any dynamic source. It will appear differently depending on your zoom level. With that in mind it shows up very consistently at high zoom levels."

No maintainer reply, fix commit, or PR has landed identifying the root cause. The only confirmed facts from the upstream artifact are:
1. The regression is gated on `dynamic: true` on a GeoJSON source.
2. It affects features whose geometry crosses tile boundaries (fills and lines both).
3. It is zoom-dependent (more severe at high zoom, where more tile boundaries are crossed per feature).

Because no authoritative diagnosis exists, this scenario is included as a symptom-only reproducer. The reproducer above emulates the observed rendering pattern (per-tile draws using only vertices inside each tile's AABB) to exercise the capture pipeline against the symptom, without claiming a specific root cause inside maplibre's tile worker or vector tile encoder.

## Difficulty Rating
4/5

## Adversarial Principles
- symptom_without_upstream_diagnosis
- tile_boundary_artifact
- framework_layer_bug_surfaced_as_gl_pattern

## How OpenGPA Helps
Per-tile draw-call inspection (`list_draw_calls` + `get_draw_call`) lets the agent see that each tile's draw uses a disjoint vertex subset instead of a clipped-but-complete polygon, and pixel queries along tile seams surface the background color bleeding through — both observations that point at the tile-slicing step rather than at the shader or blend state.

## Source
- **URL**: https://github.com/mapbox/mapbox-gl-js/issues/13348
- **Type**: issue
- **Date**: 2024-12-12
- **Commit SHA**: (n/a)
- **Attribution**: Reported by @qwioefsd; symptom characterization by a later commenter in the same thread.

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
  region: { x: 255, y: 255, w: 2, h: 2 }
  expected_not: [26, 26, 26, 255]
  tolerance: 8
```

## Predicted OpenGPA Helpfulness
- **Verdict**: ambiguous
- **Reasoning**: OpenGPA can reveal the per-tile draw-call slicing pattern, which is valuable structural evidence. However, the actual upstream root cause lives in maplibre's JS tile worker (not in GL state), so OpenGPA narrows the search but cannot point at the offending JS code path. Helpful for triage, insufficient for a full fix.

## Observed OpenGPA Helpfulness
- **Verdict**: ambiguous
- **Evidence**: validation skipped (--no-validate)
