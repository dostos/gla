# R5_ENABLING_AUTOGENERATEMIPMAPS_BREAKS_FILT: Mipmap levels allocated but never populated cause filter sampling to read uninitialized data

## User Report
### PixiJS version

8.14.0

### Link to minimal reproduction

https://codesandbox.io/p/sandbox/hardcore-rosalind-89vxfs

### Steps to reproduce

Open the link and observe the bunny fading away with the pinch filter when
`PIXI.TextureSource.defaultOptions.autoGenerateMipmaps` is set to `true`.

### What is expected?

Setting `PIXI.TextureSource.defaultOptions.autoGenerateMipmaps` to `true`
shouldn't affect filter sampling as that doesn't make any sense. The bunny
should be fully visible and pinched correctly.

### What is actually happening?

Enabling mipmaps causes the `TexturePool` to create render textures with
mipmap levels which are never populated with any real data. This causes
filters that do scaled UV sampling to sample invalid or "corrupt" data.

### Environment

- **Browser & Version**: Chrome Version 141.0.7390.67 (Official Build) (64-bit)
- **OS & Version**: Windows 11 Home 26200.6725

### Any additional comments?

As per #11304 there is no other way to generate mipmaps for `Text` than to
enable the mipmap generation by default. While it would be possible to set
`PIXI.TexturePool.textureOptions.autoGenerateMipmaps = false` to fix the
filter issue, unfortunately the `TexturePool` is also used by the text
rendering which will also disable it for `Text` instances.

Ideally I would like to have the mipmaps enabled for text and disabled for
filters. That doesn't seem to be possible due to this issue.

## Expected Correct Output
The full-screen quad should show the scene rendered into level 0 (a UV-derived gradient). At the center of the window, the pixel should be a non-black color roughly `(128, 128, 51)` reflecting the fragment-shader output `vec4(uv, 0.2, 1)` at `uv=(0.5, 0.5)`.

## Actual Broken Output
The center pixel is black (or undefined / driver-dependent garbage), because the filter fragment shader sampled level 2 of the render-target texture, which was allocated but never written. The rendered scene content exists only on level 0 and is not visible in the composited frame.

## Ground Truth
The PixiJS `TexturePool` creates filter render targets with mipmap storage allocated whenever `TextureSource.defaultOptions.autoGenerateMipmaps = true` (needed so `PIXI.Text` can mipmap), but after rendering into the filter target it never calls `glGenerateMipmap`. Filter shaders that sample with a non-zero effective LOD then read uninitialized mip levels:

> Enabling mipmaps causes the `TexturePool` to create render textures with mipmap levels which are never populated with any real data. This causes filters that do scaled UV sampling to sample invalid or "corrupt" data.

The maintainer rejected the naive fix (disabling mipmaps globally in the pool, which regresses `Text` from issue #11304) and pointed at the actual design bug:

> The actual fix should add mipmap setting into the ids generated for the pool so that it wouldn't use textures with mipmaps for filters.

i.e. the pool cache key fails to distinguish mipmapped vs. non-mipmapped render targets, so a texture originally allocated with mipmap storage (for text) gets reused as a filter target and the filter shader ends up sampling uninitialized mip levels.

## Difficulty Rating
3/5

## Adversarial Principles
- silent_uninitialized_mip_levels
- lod_sampling_without_mipmap_generation
- cross_feature_state_pollution (text-mipmap setting leaks into filter pool via a cache key that ignores the mipmap flag)

## How OpenGPA Helps
OpenGPA's Tier-1 capture exposes per-texture metadata including the declared mip level range (`GL_TEXTURE_BASE_LEVEL`/`MAX_LEVEL`) and which levels actually received writes (via `glTexImage2D` with non-NULL data, FBO attachments, or `glGenerateMipmap`). A single `texture_mip_state` query on the filter render target immediately shows that levels 1..3 are allocated but unwritten while the sampler's min filter is `GL_LINEAR_MIPMAP_LINEAR`. That mismatch — declared vs. populated — is invisible to shader-level or code-level inspection alone.

## Source
- **URL**: https://github.com/pixijs/pixijs/issues/11717
- **Type**: issue
- **Date**: 2026-04-18
- **Commit SHA**: (n/a)
- **Attribution**: Reported via PixiJS issue #11717; maintainer diagnosis in comment 5 of the same thread.

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
  region: center_pixel
  probe_xy: [256, 256]
  expected_rgb_min: [32, 32, 16]
  expected_rgb_max: [255, 255, 255]
  broken_rgb: [0, 0, 0]
  note: "Correct frame has level-0 gradient visible at center (roughly (128,128,51)). Broken frame samples uninitialized mip level 2 → typically all-zero black."
```

## Upstream Snapshot
- **Repo**: https://github.com/pixijs/pixijs
- **SHA**: 2146b890a6a6ccda74d24dbff62cfc63e2a8787a
- **Relevant Files**:
  - src/rendering/renderers/shared/texture/TexturePool.ts  # base of fix PR #11865 (mipmap key in TexturePool)
  - src/filters/defaults/FilterPipe.ts
  - src/rendering/renderers/shared/texture/TextureSource.ts

## Predicted OpenGPA Helpfulness
- **Verdict**: yes
- **Reasoning**: The bug is a state-vs-content mismatch on a specific texture: the sampler requests a mipmap level that was never written. A graphics debugger that records per-texture mip-level write history and sampler settings surfaces this directly, whereas static code inspection of either the filter shader or the pool allocation path in isolation does not reveal the problem — both are individually "correct," and the bug only exists in the interaction.

## Observed OpenGPA Helpfulness
- **Verdict**: ambiguous
- **Evidence**: validation skipped (--no-validate)
