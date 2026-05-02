# R61_NODEMATERIAL_TEXTURE_RENDERS_BLACK_ON_FAST_LOAD: Texture stays black when image loads instantly

## User Report
Under WebGPURenderer (with the WebGL fallback backend), I'm assigning a
freshly-loaded image to `material.map`. Sometimes the texture displays
correctly, but sometimes — especially when the image is small or comes
from the disk cache and loads instantly — the material renders with the
default solid black texture forever. The same image works fine if I add
a small artificial delay before assigning it.

It feels like a race condition: when the image happens to finish loading
before the renderer's internal state is initialized, the rendering
pipeline never picks up the loaded image and keeps using the default
black texture, even after `texture.needsUpdate = true`.

Reproduction steps:
1. WebGPURenderer with WebGL backend (`forceWebGL: true`).
2. Use a `MeshBasicNodeMaterial` and set `material.map` to a freshly
   created `TextureLoader().load(...)`.
3. If the image loads within the first frame, the material renders black
   forever. If it takes longer (e.g. uncached network fetch), it renders
   correctly.

Version: r183. Browser: Chrome. OS: macOS.

## Expected Correct Output
After the image finishes loading, the next render should sample the
loaded texture. Reading back the center pixel of the textured quad
should yield the texture's color, e.g. an off-white roughly `(220, 220,
220)` for a near-white asset. The render must work whether the image
loaded before or after the renderer's first internal state snapshot.

## Actual Broken Output
When the image happens to load before the renderer's first state
snapshot, the texture sampler keeps reading from the default 1x1 black
placeholder texture (the value the renderer initializes the binding
to before any user texture is bound). The center pixel of the quad
reads `(0, 0, 0)` indefinitely, even after `texture.needsUpdate = true`.
A captured frame's bound texture for the draw call shows the default
1x1 black texture object, NOT the loaded texture object — confirming
the upload simply never happens.

## Ground Truth
WebGPURenderer's `NodeMaterialObserver` watches material properties to
detect when the renderer needs to rebuild GPU state for a material.
For texture properties it caches the texture's `id` and `version` on
the first observation. On subsequent renders it compares the cached
`version` against the live texture's `version`; if they match, it
considers the texture unchanged and skips the rebuild.

The pre-fix code initialised the cache with the texture's *current*
`version` at observation time:

```js
data[ property ] = { id: value.id, version: value.version };
```

`Texture.version` defaults to `0` and is only bumped to `1` when the
image finishes loading (or `needsUpdate = true` is set). If the image
loads BEFORE `NodeMaterialObserver` first observes the property,
`value.version` is already `1` at observation time. The cache stores
`1`. The observer then compares the next frame's `value.version` (`1`)
against the cache (`1`) — *no change*, no rebuild. The texture upload
is never triggered, so the GPU keeps using the default placeholder.

If the image loads AFTER the first observation, the cache is
initialised with `0` and the next-frame compare with `1` correctly
fires the rebuild.

PR description from #33422:

> The default version value of textures in `NodeMaterialObserver` is
> wrong. It must be `0`, not `value.version`. If the texture loads
> quickly (e.g. typically on local systems), the observer misses a
> texture update and you keep seeing the black default texture.

The fix is one character: `version: value.version` → `version: 0`.
Touches one file: `src/materials/nodes/manager/NodeMaterialObserver.js`.

The minimal GL repro in `main.c` mirrors the same shape: an "observer"
struct caches a texture's `version` on first observation. The
"renderer's update loop" later compares the live version against the
cached one and conditionally calls `glTexImage2D` to upload the new
data. If the cache is initialised with the live version (the buggy
path), the upload is skipped forever and the GPU samples the default
all-zeros texture; the center pixel reads `(0, 0, 0)`.

## Fix
```yaml
fix_pr_url: https://github.com/mrdoob/three.js/pull/33422
fix_sha: 7ec51d05c1c0e6ac2a8ba1b5dc98ad57a3960af8
fix_parent_sha: 9df98d3b7e846e084128430f1d62abcd6c617e0c
bug_class: framework-internal
files:
  - src/materials/nodes/manager/NodeMaterialObserver.js
change_summary: >
  Initialise the cached texture-version inside `NodeMaterialObserver`
  with `0` instead of `value.version`. If the texture happened to load
  before the observer's first observation (typical for small or
  disk-cached images), the cached version equalled the live version and
  the dirty-check never fired, leaving the GPU's bound texture stuck
  at the default placeholder. Forcing the cache to `0` guarantees the
  first-frame compare-vs-live mismatches and triggers the upload.
```

### Captured-literal breadcrumb (for GPA trace validation)
At reproduction time, the bound `GL_TEXTURE_2D` for the affected draw
call's sampler has `width × height = 1 × 1` and `pixels = (0, 0, 0,
255)` — the renderer's default placeholder. The expected value is the
loaded image's full-size texture object. The captured texture
`internalformat` and `pixels` differ from the loaded image's by ID
and content. The "wrong literal" the breadcrumb points to is the
JavaScript value `value.version` (a property reference) being used as
the *initial* value of the cached version field. The write site is
`src/materials/nodes/manager/NodeMaterialObserver.js`'s observed-data
initialisation block where texture properties are cached:
`data[ property ] = { id: value.id, version: value.version };`.
`gpa trace value "version: value.version"` (or just
`"value.version"` filtered to `nodes/manager/`) routes the agent to
this single line. Compared against the rest of the framework, where
`version` initial values are `0` or `null`, this expression is the
outlier — and exactly the line the fix changes to `version: 0`.

## Upstream Snapshot
- **Repo**: https://github.com/mrdoob/three.js
- **SHA**: 9df98d3b7e846e084128430f1d62abcd6c617e0c
- **Relevant Files**:
  - src/materials/nodes/manager/NodeMaterialObserver.js
  - src/textures/Texture.js
  - src/loaders/TextureLoader.js
  - src/renderers/common/RenderObject.js

## Difficulty Rating
4/5

## Adversarial Principles
- race-condition-load-vs-observe-order
- dirty-check-uses-current-as-initial-cache
- symptom-only-on-fast-load-paths
- silent-failure-no-error-no-log

## How OpenGPA Helps
A `gpa report` query shows the bound texture for the affected draw
call has dimensions `1 × 1` — the renderer's default placeholder, not
the user's loaded image. Comparing two frames (one before the load
fires, one after) shows the bound texture object never changes. A
`gpa trace value 1` filtered by texture binding context (or
`gpa trace value "value.version"` against the project source) routes
to `NodeMaterialObserver.js` as the only file that initialises a
cached version with the *live* value rather than `0` — the missing
sentinel that prevents the first-frame dirty-check from firing.

## Source
- **URL**: https://github.com/mrdoob/three.js/pull/33422
- **Type**: pull_request
- **Date**: 2026-04-04
- **Commit SHA**: 7ec51d05c1c0e6ac2a8ba1b5dc98ad57a3960af8
- **Attribution**: Reported and fixed by @Mugen87 in PR #33422 (NodeMaterialObserver default version).

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
  expected_rgb: [220, 220, 220]
  actual_rgb:   [0, 0, 0]
  tolerance: 16
  note: >
    Center pixel of a textured quad whose source image was assigned to
    `material.map` after the image had already finished loading.
    Expected the loaded texture color; broken path keeps sampling the
    1x1 black placeholder because the dirty-check cache was initialised
    with the live texture version, so the compare never fires.
```

## Predicted OpenGPA Helpfulness
- **Verdict**: yes
- **Reasoning**: The bound texture for the affected draw call is the
  1×1 default placeholder — an immediate breadcrumb that the user's
  texture was never uploaded. Reverse-searching how the version-based
  dirty check is initialised surfaces `NodeMaterialObserver.js` as the
  one file using `value.version` (instead of `0`) as the initial cache
  value. Without the trace, the agent has to walk the render-object
  rebuild logic top-down to find the missing first-frame trigger.
