# R14: Bevy tilemap shows colors bleeding along tile edges

## User Report

I am using the tilemap chunk feature in Bevy 0.17.3. I set up a simple
'wires' chunk. The background of the image is transparent.

```rust
let chunk_size = UVec2::splat(3);
let tile_display_size = UVec2::splat(64);
let tile_data: Vec<Option<TileData>> = (0..chunk_size.element_product())
    .map(|i| i % 16)
    .map(|i| Some(TileData::from_tileset_index(i as u16)))
    .collect();
```

The tileset texture is 16 pixels wide and 256 tall. `ImagePlugin` is
set to nearest filtering:

```rust
app.add_plugins(DefaultPlugins.set(ImagePlugin::default_nearest()));
```

I expected a clear distribution of tiles. I found a distribution of
tiles but with slight color bleeding of assets along the edges of
each tile (see attached screenshot). The transparent background of
the source texture leaks across into adjacent tiles.

I would have to suspect this is either a bug with how the tilemap's
image is constructed in Bevy or a graphics-API issue with small
textures.

## Expected Correct Output

Each tile drawn into the chunk should sample only its own pixels from
the tileset and the boundary between tiles should be a sharp,
1-pixel-precise transition with no color leakage from neighboring
tile rows in the source image.

## Actual Broken Output

A faint stripe of color from the previous-row tile in the source
texture appears along the top edge of every tile (and similarly
along the bottom, if the next-row tile is opaque). The artifact is
1-2 pixels thick. With nearest filtering this should be impossible
unless the sampled UVs are landing on the wrong texel.

## Ground Truth

Per the fix PR ("Fix tilemap UV rounding error"):

The fragment shader for tilemap chunks computed the sub-region of
the tileset texture for a given tile by multiplying the tile index
by the tile's UV-size, but accumulated floating-point error pushed
the sampled UV across the boundary into the *neighbouring* tile by
half a texel. Snapping the per-tile UV origin to the nearest texel
center fixes the bleed.

## Fix
```yaml
fix_pr_url: https://github.com/bevyengine/bevy/pull/22449
fix_sha: 6fbb2a3c2b39e253312ba2e454946c897a5d4238
fix_parent_sha: 238e1ea665a12c4fb83b4d9e6f6546be62500094
bug_class: framework-internal
framework: bevy
framework_version: 0.17.3
files:
  - crates/bevy_sprite_render/src/tilemap_chunk/tilemap_chunk_material.wgsl
change_summary: >
  The tilemap-chunk fragment shader's per-tile UV computation
  accumulated a fractional error and ended up sampling the
  neighbouring tile's first row of texels. The fix snaps the
  computed UV origin to the texel grid before sampling, so the
  edges no longer pick up color from adjacent rows of the tileset.
```

## Upstream Snapshot
- **Repo**: https://github.com/bevyengine/bevy
- **SHA**: 238e1ea665a12c4fb83b4d9e6f6546be62500094
- **Relevant Files**:
  - crates/bevy_sprite_render/src/tilemap_chunk/tilemap_chunk_material.wgsl

## Flywheel Cell
primary: framework-maintenance.game-engine.code-navigation
secondary:
  - framework-maintenance.game-engine.captured-fragment-uv-trace

## Difficulty Rating
3/5

## Adversarial Principles
- visual-symptom-only-user-report
- subpixel-uv-defect-only-visible-on-small-textures
- bug-lives-in-fragment-shader-not-application-code

## How OpenGPA Helps

A pixel-level capture of the bleed pixel reveals which texel of the
tileset the fragment shader actually sampled. With per-pixel UV
trace from the GL/Vulkan shim, the agent sees that the bleed pixel
sampled v=`16.0/256` instead of `16.0/256 + 0.5/256` — a half-texel
miss, exactly the kind of floating-point UV error that the source
suspects ("bug with how the tilemap's image is constructed"). That
trace points at the tilemap fragment shader rather than at user
code or asset loading.

## Source
- **URL**: https://github.com/bevyengine/bevy/issues/22250
- **Type**: issue
- **Date**: 2025-12-10
- **Commit SHA**: 6fbb2a3c2b39e253312ba2e454946c897a5d4238
- **Attribution**: Reported in issue #22250; fix in PR #22449.

## Tier
visual-only

## API
vulkan

## Framework
bevy

## Bug Signature
```yaml
type: code_location
spec:
  expected_files:
    - crates/bevy_sprite_render/src/tilemap_chunk/tilemap_chunk_material.wgsl
  fix_commit: 6fbb2a3c2b39e253312ba2e454946c897a5d4238
```

## Predicted OpenGPA Helpfulness
- **Verdict**: yes
- **Reasoning**: The user-report names the API surface ("tilemap")
  but does **not** say "fragment shader" or "UV". Grep on
  "tilemap" returns multiple Rust crates; the fix is in a single
  WGSL file. Per-fragment UV trace from the capture would show the
  miss-by-half-a-texel, focusing the search on shader code rather
  than the tile data structures or texture loader.

## Observed OpenGPA Helpfulness
- **Verdict**: ambiguous
- **Evidence**: validation pending — code_only baseline not yet run.
