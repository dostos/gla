# R57_KTX2_TEXTURE_WITH_ALPHAHASH_RENDERS_A: KTX2 texture with material.alphaHash renders noise artifacts

## User Report
If I am using a KTX2 texture with `material.alphaHash = true` there's visual
artifacts like semi-transparent noise. If I am using the webp version of the
texture, it's fine. This problem appears only on Windows, no such problem
on macOS and iOS or iPadOS. I don't know in what texture format ktx2
transcodes on Windows, but seems like problem only with it.

If I disable `alphaHash` and enable `material.transparent = true`, there's
no artifacts even with ktx2 texture.

I am using ktx2 UASTC with UASTC Zstandard supercompression and pregenerated
mipmaps.

Reproduction steps:
1. `material.alphaHash = true`
2. `material.map = ktx2Texture`
3. Noise artifacts on Windows

Version: r181. Browser: Chrome. OS: Windows.

## Expected Correct Output
With `alphaHash = true` and a KTX2-compressed texture whose alpha channel
encodes "mostly transparent edge + fully opaque body", the rendered quad
should show a clean alpha-hashed stipple at the silhouette and no visible
noise in the opaque body. A pixel sampled inside the opaque body region
reads an alpha-hashed value of 1.0 → the underlying RGB color, e.g.
`(200, 200, 200)` ± 5.

## Actual Broken Output
On Windows, the opaque body of the quad renders a coarse salt-and-pepper
stipple — pixels alternate between visible and discarded under the
alpha-hash test, even where the source alpha is 1.0. The GPU-side alpha
values come back as noisy, uncorrelated with the authored alpha. Captured
at the GL level, the draw call's bound texture reports
`internalformat = 0x83F2` (i.e. `33778`, `COMPRESSED_RGBA_S3TC_DXT3_EXT`)
for a transcode that should be `0x83F3` / `33779` / DXT5.

## Ground Truth
DXT3 (aka BC2) and DXT5 (aka BC3) are two 128-bit-per-block BC compression
formats that differ **only** in how the alpha channel is encoded. DXT3
stores alpha as uncompressed 4-bit-per-texel values; DXT5 stores alpha via
an interpolated 2-endpoint block scheme that matches how color is stored.

Transcoders like the one KTX2Loader uses for `VK_FORMAT_BC3_*` produce a
BC3 (DXT5) payload. If the loader then *labels* that payload as DXT3 when
handing it to WebGL, the GPU reinterprets DXT5-encoded alpha bits using
the DXT3 decoder — giving random-looking alpha noise exactly because the
two encoders produce completely different bit layouts for alpha. RGB
happens to decode fine because BC2 and BC3 share the RGB endpoint
scheme; only alpha is wrong. This matches the reporter's symptoms:
- "noise artifacts" (alpha read from the wrong decoder)
- only visible with `alphaHash = true` (which tests alpha per fragment)
- opaque `transparent = true` path is unaffected (alpha blending smooths
  the noise in a way alpha hashing doesn't).

three.js r181 `KTX2Loader.js` contained a typo in the `FORMAT_MAP` table:

```js
[ VK_FORMAT_BC3_SRGB_BLOCK ]:  RGBA_S3TC_DXT3_Format,   // wrong (DXT3 = BC2)
[ VK_FORMAT_BC3_UNORM_BLOCK ]: RGBA_S3TC_DXT3_Format,   // wrong
```

The PR description (PR #32772):

> Fixes KTX2Loader when loading alpha channels in BC3 textures. The bug
> affects only BC3-compressed textures, textures using Basis Universal
> compression and transcoding to BC3 were unaffected. The loader should
> have been mapping BC3 to DXT5, instead of DXT3.

The fix flips both entries to `RGBA_S3TC_DXT5_Format` and removes the now-
unused `RGBA_S3TC_DXT3_Format` import. A single-file change in
`examples/jsm/loaders/KTX2Loader.js`.

The minimal GL repro in `main.c` uses the raw GL compressed-texture upload
path. It pre-bakes a 4×4 BC3 block whose alpha channel should decode to 1.0
everywhere, and calls `glCompressedTexImage2D` with the **wrong**
`internalformat` — `COMPRESSED_RGBA_S3TC_DXT3_EXT` (0x83F2) instead of
`COMPRESSED_RGBA_S3TC_DXT5_EXT` (0x83F3). The DXT3 decoder reinterprets the
DXT5 alpha endpoints/indices as uncompressed 4-bit alpha and produces a
noisy alpha pattern; sampling the middle of the quad with alpha-test
rejecting any fragment whose alpha < 0.5 yields a mottled, not solid,
output.

## Fix
```yaml
fix_pr_url: https://github.com/mrdoob/three.js/pull/32772
fix_sha: a477148f9569aca66be8413c563412c4160caa8a
fix_parent_sha: fb28a2e295a53628d27dbcb0a0b8435b5fd75b62
bug_class: framework-internal
files:
  - examples/jsm/loaders/KTX2Loader.js
change_summary: >
  Map `VK_FORMAT_BC3_SRGB_BLOCK` and `VK_FORMAT_BC3_UNORM_BLOCK` to
  `RGBA_S3TC_DXT5_Format` instead of `RGBA_S3TC_DXT3_Format` in
  `KTX2Loader`'s `FORMAT_MAP`. BC3 and DXT5 agree on alpha encoding
  (interpolated endpoints); DXT3 uses uncompressed 4-bit-per-texel alpha
  and therefore decodes the BC3 payload's alpha channel as noise. The
  now-unused DXT3 import is dropped.
```

### Captured-literal breadcrumb (for GPA trace validation)
At reproduction time, the `glCompressedTexImage2D` call for a KTX2 BC3
texture uploads with `internalformat = 0x83F2` (decimal `33778`,
`GL_COMPRESSED_RGBA_S3TC_DXT3_EXT`). The correct value is `0x83F3`
(decimal `33779`, `GL_COMPRESSED_RGBA_S3TC_DXT5_EXT`). The wrong literal
`33778` is ultimately written because `KTX2Loader.js`'s `FORMAT_MAP`
returns `RGBA_S3TC_DXT3_Format` (three.js internal constant value `33778`)
for `VK_FORMAT_BC3_*` inputs, which `WebGLTextures.js` then translates to
the matching GL enum `0x83F2`. `gpa trace value 33778` (or `gpa trace
value 0x83F2`) on the project source routes to
`examples/jsm/loaders/KTX2Loader.js` as the write-site, because the
`FORMAT_MAP` lookup literally stores the format constant there. A
secondary hit on `src/constants.js` (where `RGBA_S3TC_DXT3_Format = 33778`
is defined) is expected but the surrounding context disambiguates
KTX2Loader as the fix file.

## Upstream Snapshot
- **Repo**: https://github.com/mrdoob/three.js
- **SHA**: fb28a2e295a53628d27dbcb0a0b8435b5fd75b62
- **Relevant Files**:
  - examples/jsm/loaders/KTX2Loader.js
  - src/renderers/webgl/WebGLTextures.js
  - src/constants.js

## Difficulty Rating
4/5

## Adversarial Principles
- enum-typo-dxt3-vs-dxt5
- only-affects-alpha-channel
- platform-gated-transcode-path
- symptom-is-noise-not-missing-data

## How OpenGPA Helps
A single `gpa report` query shows the texture-upload draw binding a
`COMPRESSED_RGBA_S3TC_DXT3_EXT` texture where the mesh uses
`alphaHash = true` and the downstream alpha noise is the root cause. The
captured `internalformat` literal (`0x83F2` / `33778`) is specific enough
that a reverse lookup against the project source routes directly to
`KTX2Loader.js`'s `FORMAT_MAP`. Without the capture, the agent would need
to chase the transcoding pipeline (Basis → KTX2 → WebGL) across multiple
files before finding the wrong enum mapping.

## Source
- **URL**: https://github.com/mrdoob/three.js/issues/32533
- **Type**: issue
- **Date**: 2025-12-07
- **Commit SHA**: a477148f9569aca66be8413c563412c4160caa8a
- **Attribution**: Reported by @guga (three.js #32533); fixed in PR #32772 (KTX2Loader: Fix alpha for BC3 textures).

## Tier
snapshot

## API
opengl

## Framework
three.js

## Bug Signature
```yaml
type: unexpected_color
spec:
  region: { x: 128, y: 128, w: 1, h: 1 }
  expected_rgb: [200, 200, 200]
  actual_rgb:   [0, 0, 0]
  tolerance: 32
  note: >
    Center pixel of an "opaque body" region of an alpha-hashed BC3
    texture. Expected to survive the alpha test and render the diffuse
    gray; broken path decodes the alpha channel as DXT3 noise so the
    fragment discards at random and the pixel reads the clear color.
```

## Predicted OpenGPA Helpfulness
- **Verdict**: yes
- **Reasoning**: The captured GL internalformat is a specific numeric
  constant (`0x83F2`) that, when reverse-searched, surfaces exactly the
  one source file that maps Vulkan BC3 to a WebGL DXT enum. The user's
  description ("noise on Windows") gives no source location; the enum
  mismatch in the capture is the diagnostic breadcrumb.

## Observed OpenGPA Helpfulness
- **Verdict**: ambiguous
- **Evidence**: validation skipped (--no-validate)
