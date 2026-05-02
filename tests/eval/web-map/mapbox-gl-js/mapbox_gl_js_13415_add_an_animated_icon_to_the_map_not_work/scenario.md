# R11_ADD_AN_ANIMATED_ICON_TO_THE_MAP_NOT_WORK: Overlapping symbol layers sharing a source — one icon disappears

## User Report
**mapbox-gl-js version**: 3.9

**browser**: chrome

### Steps to Trigger Behavior

 1. open example: Add an animated icon to the map
 2. Icon does not render

### Link to Demonstration

https://docs.mapbox.com/mapbox-gl-js/example/add-image-animated/

### Expected Behavior

The animated pulsing icon should render on top of the static map symbol at
the demo location.

### Actual Behavior

The icon does not render — only one of the two symbol layers is visible at a
time, depending on the Mapbox version (either the pulsing dot or the static
image, but not both).

## Expected Correct Output
Both icons visible at the same screen-space location: a pulsing red disc with a smaller static cyan disc composited on top.

## Actual Broken Output
Only one of the two quads is rendered.  In the mapbox regression, which quad wins depends on the library version (3.9 vs 3.10) but never both.

## Ground Truth
The upstream reporter describes the symptom precisely:

> Only one of the layers is visible at a time, depending on the Mapbox version - either the pulsing dot or the static image, but not both.

and identifies the repro recipe as two symbol layers sharing a GeoJSON source with `icon-allow-overlap` and `icon-ignore-placement` both set to true (see mapbox/mapbox-gl-js#13415, linked from the originating issue #13367).  The maintainer acknowledged a regression and committed to a patch:

> Working on a patch for this one to be released shortly — apologies!

A follow-up comment on #13367 notes the fix was incomplete and the behavior returned in a later release:

> This is not completed fix or maybe issue happend again; check this thread: https://github.com/mapbox/mapbox-gl-js/issues/13415

No maintainer-authored root-cause post-mortem has been published; the issue pair (#13367 + #13415) is the primary upstream record.  The observed symptom — two draws from two layers over a shared source where exactly one survives — is consistent with collision/placement state being keyed by source+feature rather than by (source, feature, layer), so the second layer's symbol is suppressed as "already placed" by the first.  The minimal C repro models the shared-state symptom at the GL level: two VAOs intended to issue independent draws, one of which silently degenerates when a binding is carried over from the first.

## Difficulty Rating
3/5

## Adversarial Principles
- shared_source_cross_layer_state
- silently_dropped_draw
- version_dependent_symptom

## How OpenGPA Helps
Query `/api/v1/frames/current/draw_calls` to list every draw and inspect each call's bound VAO/EBO plus vertex count.  The missing or zero-primitive draw will be visible in the draw-call list even though the on-screen pixels look like a single layer, immediately distinguishing "layer skipped" from "layer drawn but hidden."

## Source
- **URL**: https://github.com/mapbox/mapbox-gl-js/issues/13367
- **Type**: issue
- **Date**: 2024-12-17
- **Commit SHA**: (n/a)
- **Attribution**: Reported upstream on mapbox/mapbox-gl-js; linked regression in #13415.

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
  expected_draw_count: 2
  observed_draw_count: 1
  shared_resource: element_buffer
```

## Upstream Snapshot
- **Repo**: https://github.com/mapbox/mapbox-gl-js
- **SHA**: f03200d37b7095291da94781cc5857caa84d050f
- **Relevant Files**:
  - src/symbol/placement.ts  # base of release PR #13379 (closes #13367)
  - src/symbol/collision_index.ts
  - src/data/bucket/symbol_bucket.ts

## Predicted OpenGPA Helpfulness
- **Verdict**: yes
- **Reasoning**: The diagnostic question ("is the second layer being issued at all?") is exactly what a draw-call enumeration answers.  Without OpenGPA an agent would have to guess between "layer not rendered," "layer rendered but occluded," and "layer rendered off-screen" from pixel output alone; with the draw-call list the answer is direct.

## Observed OpenGPA Helpfulness
- **Verdict**: ambiguous
- **Evidence**: validation skipped (--no-validate)
