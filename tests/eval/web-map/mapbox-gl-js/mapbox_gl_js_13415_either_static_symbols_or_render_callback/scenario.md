# R6_EITHER_STATIC_SYMBOLS_OR_RENDER_CALLBACK: Overlapping symbol layers sharing a GeoJSON source render only one icon

## User Report

**mapbox-gl-js version**: The issue occurs in both 3.9.0 and 3.10.0, but with different behaviors: In 3.9.0, the static image is visible, while in 3.10.0, the render callback image is shown instead.

**browser**: Chrome, Firefox, Edge

### Steps to Trigger Behavior

1. Instantiate a map and wait for the load event to fire.
2. Add a GeoJSON source with a single point in the feature collection.
3. Add two symbol layers using this source (ensure both layers have `icon-allow-overlap` and `icon-ignore-placement` set to true):
    - The first should use an icon-image with a render callback (like from the "Add an animated icon to the map" example).
    - The second should use a sprite already included in the map style.

### Expected Behavior

The static image should be shown on top of the pulsing dot image.

### Actual Behavior

Only one of the layers is visible at a time, depending on the Mapbox version — either the pulsing dot or the static image, but not both.

A follow-up reporter confirmed the same: downgrading to 3.8.0 restores both icons; 3.9.0 onward hides one of them. Another observation: in larger maps, moving the affected symbol layer behind other clustered layers and then zooming in/out makes the hidden layer appear briefly — suggesting tile/layer-level state that gets out of sync.

## Expected Correct Output

Two icons rendered at the same point feature: the animated pulsing-dot icon (driven by a render callback that updates pixels every frame) and the static sprite icon on top of it. Both should be present on the very first frame after layers are added, because both symbol layers set `icon-allow-overlap: true` and `icon-ignore-placement: true`.

## Actual Broken Output

Only one icon is drawn at the shared point. Which icon wins depends on the version:
- v3.9.0: the static sprite icon is visible; the render-callback icon is missing.
- v3.10.0 through v3.14.0 (latest at time of report): the render-callback icon is visible; the static sprite icon is missing.
In both cases the "losing" layer's symbol is absent from the final framebuffer, not merely occluded or placed elsewhere.

## Ground Truth

Root cause (symptom level, corroborated by the fix commit): when two symbol layers share a single GeoJSON source and one of the layers uses an image with a render callback (`hasRenderCallback: true`, e.g. from `map.addImage(id, { width, height, data, onAdd, render })`), the image-atlas machinery introduced in v3.9.0 produces an atlas state in which only one of the two layers' icons is usable per tile. The regression was introduced alongside the atlas-caching rework (`ImageAtlasCache`, `AtlasContentDescriptor`, `sortImagesMap`, `FinalizationRegistry`-based eviction) visible in the pre-fix `src/render/image_atlas.ts` and in the `getTextureForAtlas` / `patchUpdatedImages` paths in `src/render/texture.ts`.

Citation: the maintainers confirmed a fix in the linked commit:

> The fix will be available in the upcoming release of GL JS — https://github.com/mapbox/mapbox-gl-js/commit/7e814f92d6317cb2bcf28d7ee6bb7eed86963db3

The authoritative diagnosis lives in that commit's diff and message; the upstream thread itself contains no prose explanation of the root cause beyond the fix link. An agent answering this scenario should determine, from the pre-fix source in the snapshot, which of the following paths is responsible:

1. `ImageAtlas.haveRenderCallbacks` / `patchUpdatedImages` treating the render-callback image as belonging to only one of the two layers that reference it.
2. `ImageAtlasCache.findCachedAtlas` returning a subset-match atlas that lacks one layer's icon (`descriptor.subsetOf(cachedAtlas.contentDescriptor)`).
3. `getTextureForAtlas` binding a texture whose atlas image no longer reflects the render-callback layer's current pixel data (the `position.version === image.version` short-circuit in `patchUpdatedImage`).

The fix commit (7e814f9) is the ground-truth tiebreaker between these hypotheses.

## Difficulty Rating

4/5

## Adversarial Principles

- regression_introduced_by_caching_rework
- shared_source_cross_layer_state
- render_callback_vs_static_image_interaction
- symptom_swaps_direction_between_versions

## How OpenGPA Helps

A frame-capture view of the draw calls for the two symbol layers reveals whether (a) one of the layers is skipping its draw entirely (layer-level placement/culling bug) or (b) both draws execute but one samples from an atlas region whose pixels belong to the other layer's icon (atlas-sharing bug). Querying the sampled texture contents at the symbol's UV range, plus the bound texture ID per draw, distinguishes the two root-cause families and points directly at the atlas-cache subset-matching or render-callback-patching code.

## Source

- **URL**: https://github.com/mapbox/mapbox-gl-js/issues/13415
- **Type**: issue
- **Date**: 2026-04-20
- **Commit SHA**: 7e814f92d6317cb2bcf28d7ee6bb7eed86963db3
- **Attribution**: Reported on mapbox/mapbox-gl-js#13415; fix commit 7e814f9 linked by a maintainer in the thread.

## Upstream Snapshot
- **Repo**: https://github.com/mapbox/mapbox-gl-js
- **SHA**: 86882da09f76c0a78618febd28f18a1c1a0c5ad7
- **Relevant Files**:
  - src/render/image_atlas.ts
  - src/render/atlas_content_descriptor.ts
  - src/render/texture.ts
  - src/render/image_manager.ts
  - src/symbol/symbol_bucket.js
  - src/symbol/placement.js
  - src/data/bucket/symbol_bucket.ts
  - src/style/style_image.ts

## Tier
snapshot

## API
webgl

## Framework
mapbox-gl-js

## Bug Signature
```yaml
type: missing_draw_call
spec:
  expected_layers:
    - id: pulsing-dot-layer
      kind: symbol
      icon_image: "pulsing-dot"
      has_render_callback: true
    - id: static-sprite-layer
      kind: symbol
      icon_image: "marker-15"
      has_render_callback: false
  shared_source: single-point-geojson
  shared_feature_coord: [0, 0]
  both_have_allow_overlap: true
  both_have_ignore_placement: true
  observed_symptom: "exactly one of the two symbol-layer icons is absent from the framebuffer at the shared coordinate"
  version_dependent_winner:
    v3_9_0: static-sprite-layer
    v3_10_0_plus: pulsing-dot-layer
  fix_commit: 7e814f92d6317cb2bcf28d7ee6bb7eed86963db3
```

## Predicted OpenGPA Helpfulness
- **Verdict**: yes
- **Reasoning**: The bug manifests as one symbol draw missing or sampling wrong atlas pixels — both are directly observable in a frame-level capture (draw call list, bound texture IDs, sampled UV ranges). OpenGPA's per-draw state queries let the agent distinguish a placement/culling regression from an atlas-cache subset-match regression without reading mapbox-gl-js source, which is the main source of difficulty for a text-only agent.

## Observed OpenGPA Helpfulness
- **Verdict**: ambiguous
- **Evidence**: validation skipped (--no-validate)
