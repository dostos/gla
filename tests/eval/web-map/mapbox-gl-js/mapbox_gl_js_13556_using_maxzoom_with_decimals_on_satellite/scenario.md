# R2_USING_MAXZOOM_WITH_DECIMALS_ON_SATELLITE: Fractional maxZoom renders black satellite tiles under 3D terrain (mapbox-gl-js)

> This scenario is snapshot-tier: diagnosis requires reading upstream code; capture is a context stub.

## User Report
### mapbox-gl-js version

v3.15.0

### Browser and version

Firefox 142.0.1, Chromium 140.0.7339.127

### Expected behavior

When setting a `maxZoom`, I simply expect this max zoom value to be applied
as limit without impact on the rendering.

### Actual behavior

When setting a `maxZoom` a numeric value with decimals (like `16.58`), on a
map with satellite style and 3D terrain, some tiles are not correctly
displayed (and appear black).

Setting an integer value as `maxZoom` (like `16`) fixes the issue!

### Link to the demonstration

https://jsbin.com/tukedijime/edit?html,js,output

### Steps to trigger the unexpected behavior

- Add 3D terrain
- Use satellite style (`mapbox://styles/mapbox/satellite-v9`)
- Set `maxZoom` with decimals
- Zoom in the map

## Expected Correct Output
A seamless satellite-imagery mosaic draped on the terrain mesh. Every
visible tile shows photographic ground imagery sampled from the
`mapbox://styles/mapbox/satellite-v9` raster source, with neighbouring
tiles joining continuously along tile edges.

## Actual Broken Output
A subset of tiles within the visible mosaic render as solid black
rectangles while neighbouring tiles render normally. The black tiles are
aligned on the tile grid, indicating the failure is per-tile (not a
fragment-shader artifact or a terrain-mesh seam). The raster imagery for
those tiles is never visible to the user.

## Ground Truth
The fix landed as commit
`e730d17afb4a05af9f744ed783dee13d7e238425` with message
"Fix empty tiles on non-integer maxZoom with terrain" and shipped in
v3.19.0. The v3.19.0 CHANGELOG entry states:

> Fix empty tiles on non-integer maxZoom when terrain was used.

The diff is a two-line change in `src/terrain/terrain.ts`. The terrain
pipeline creates two internal `SourceCache` instances — a `MockSourceCache`
(for the raster-DEM elevation data that shapes the terrain mesh) and a
`ProxySourceCache` (a GeoJSON-backed proxy used to schedule tile rendering
into the terrain proxy atlas). Both were constructed with the user's
`map.transform.maxZoom` passed straight through as the source's `maxzoom`:

```
// before
const sourceSpec: SourceSpecification = {type: 'raster-dem', maxzoom: map.transform.maxZoom};
...
const source = createSource('proxy', {type: 'geojson', maxzoom: map.transform.maxZoom}, ...);
```

`SourceCache` / `TileID` arithmetic is integer-indexed — tile coordinates
are `(z, x, y)` with `z` an integer. When the user sets
`map.transform.maxZoom = 16.58` the two source caches end up with a
fractional `maxzoom`, which downstream tile-selection logic (overzoom
decisions, parent-tile lookup, `OverscaledTileID` construction) then
treats inconsistently with the integer tile-coordinate space the
satellite raster source uses. The result is that for some grid cells the
terrain pipeline cannot find / upload a DEM tile (or proxy tile) at a
zoom level compatible with the visible raster tile, so the shader that
drapes the satellite texture over the terrain proxy ends up sampling
nothing and writes black.

The fix is to round up before handing the value to `SourceCache`:

```
// after
const sourceSpec: SourceSpecification = {
    type: 'raster-dem',
    maxzoom: Math.ceil(map.transform.maxZoom)
};
...
const source = createSource('proxy', {
    type: 'geojson',
    maxzoom: Math.ceil(map.transform.maxZoom)
}, ...);
```

`Math.ceil(16.58) === 17`, so the derived source caches now declare an
integer `maxzoom` that fully covers the camera's requested zoom, and the
terrain proxy / DEM pipelines can fetch tiles for every visible grid cell.

Commit: `e730d17afb4a05af9f744ed783dee13d7e238425`
(see the `src/terrain/terrain.ts` hunks for `MockSourceCache` and
`ProxySourceCache` constructors).

## Difficulty Rating
4/5

The symptom is "some tiles are black, others aren't" — a generic missing-
data signature that could be caused by tile-request failure, CORS, shader
compile error, depth/stencil misuse, or a hundred other things. The fact
that the trigger is a *fractional* numeric input at an unrelated JS API
surface (`map.maxZoom`) and that the failure is in an internal derived
`SourceCache` `maxzoom` that the user never sees, makes the bug very hard
to localize without either bisecting the repro or reading the fix.

## Adversarial Principles
- numeric_precision_at_api_boundary
- float_to_integer_index_coercion
- derived_internal_cache_misconfig
- symptom_spatially_tiled_but_cause_not_per_pixel

## How OpenGPA Helps
Limited. OpenGPA's WebGL shim could capture the browser frame and a per-
draw inspection would show that specific tile draws sample from DEM /
proxy textures that have no coverage at the required zoom (black /
uninitialized regions) — that narrows the cause to the terrain tile
pipeline rather than the satellite raster fetch. But OpenGPA has no
visibility into the JS `SourceCache.maxzoom` field that is the actual
bug, so the agent would still need to read the terrain source code to
find the missing `Math.ceil`.

## Source
- **URL**: https://github.com/mapbox/mapbox-gl-js/issues/13556
- **Type**: issue
- **Date**: 2025-09-15
- **Commit SHA**: 97fc828fc04ed8390bc98ad1dcbbb8042cd8ba55
- **Attribution**: Reported on issue #13556; fix by @mourner, landed in v3.19.0 (CHANGELOG: "Fix empty tiles on non-integer maxZoom when terrain was used")

## Tier
snapshot

## API
opengl

## Framework
none

## Upstream Snapshot
- **Repo**: https://github.com/mapbox/mapbox-gl-js
- **SHA**: 97fc828fc04ed8390bc98ad1dcbbb8042cd8ba55
- **Relevant Files**:
  - src/terrain/terrain.ts
  - src/source/source_cache.ts
  - src/source/tile_id.ts
  - src/source/raster_dem_tile_source.ts
  - src/geo/transform.ts
  - src/render/draw_raster.ts

## Bug Signature
```yaml
type: color_histogram_in_region
spec:
  region: visible_satellite_tile_grid
  expected_color_dominant: photographic_varied
  observed_color_dominant: pure_black
  trigger_precondition: map.transform.maxZoom is non-integer AND terrain enabled AND style == satellite-v9
```

## Predicted OpenGPA Helpfulness
- **Verdict**: ambiguous
- **Reasoning**: OpenGPA's per-draw texture/uniform snapshots could surface
  the downstream symptom — tile draws that sample an empty DEM / proxy
  texture region — and thereby localize the failure to the terrain tile
  pipeline rather than the raster fetch or the satellite shader. It
  cannot, however, directly observe the root cause, which is a JS-side
  numeric-precision mistake (fractional `maxzoom` forwarded into an
  integer-indexed `SourceCache`) upstream of any GL call. An agent with
  OpenGPA would still need to read `src/terrain/terrain.ts` to identify
  the missing `Math.ceil`.

## Observed OpenGPA Helpfulness
- **Verdict**: ambiguous
- **Evidence**: validation skipped (--no-validate)
