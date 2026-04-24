# R11_WEBGLRENDERER_UBO_UNIFORM_BUFFER_OBJECT_: three.js UBO packs vec2 after float at the wrong offset

## User Report
I'm trying to give a go to `UBO / UniformBufferObject` but I noticed one weird thing.
I'm setting a vec2 but looks like is keeping only one value (y) and set the other to 0

```js
globalUniforms.resolution = new Uniform(new Vector2(11, 33))
globalUniforms.add(globalUniforms.resolution)
```

But if you check the screenshot, it's correct as vec2 of floats but as you can notice values are 33 and 0, instead of 11 and 33.

After that i tried to bind a `Vector3` and so far is binded correctly:

```js
globalUniforms.resolution = new Uniform(new Vector3(11, 33, 77))
globalUniforms.add(globalUniforms.resolution)
```

**Live example:** https://stackblitz.com/edit/vitejs-vite-z3emzj?file=main.js

Version: three.js r166. Device: Desktop, Mobile. Browser: Chrome, Firefox. OS: MacOS.

---

Follow-up observations from the thread:

- If I set ONLY the resolution, it is bound correctly.
- If I add a `float` (e.g. `time`) BEFORE the `resolution` vec2, it is NOT working — the vec2 reads back as `(33, 0)` instead of `(11, 33)`.
- If I switch the order (resolution then time), it is bound correctly.
- With `float + vec3`, it works fine (vec3 ends up at offset 16).

```js
const globalUniforms = new THREE.UniformsGroup();
globalUniforms.setName('Global');
globalUniforms.time = new THREE.Uniform(0);
globalUniforms.add(globalUniforms.time);
globalUniforms.resolution = new THREE.Uniform(new THREE.Vector2(11, 33));
globalUniforms.add(globalUniforms.resolution);
```

Reporter's own guess: "the write is wrong, the read is correct" — the CPU-side buffer is packed in one layout but the shader reads it under a different one.

## Expected Correct Output
The fragment shader reads `resolution = vec2(11.0, 33.0)` and writes it to the
framebuffer as `vec4(resolution.x/100, resolution.y/100, 0, 1)`. Center pixel
rgba should be approximately `(28, 84, 0, 255)` (i.e. `~0.11` red, `~0.33`
green).

## Actual Broken Output
Center pixel rgba is `(84, 0, 0, 255)`. The shader reads `resolution =
vec2(33.0, 0.0)` — the x component holds what was written as the y component,
and the y component is zero.

## Ground Truth
The fragment shader declares `Global` with `layout(std140)`. Under std140, the
base alignment of a `vec2` is 8 bytes and the base alignment of a `float` is 4
bytes. A `float` followed by a `vec2` must therefore be laid out as
`[float @ 0][pad 4..8][vec2 @ 8..16]` — the 4 bytes between the float and the
vec2 are padding that the CPU writer must skip.

The three.js 0.166 `WebGLUniformsGroups` code computed offsets by simply
accumulating each uniform's size and did not round the running offset up to
the element's std140 base alignment before writing. So it wrote the vec2 at
offset 4 (right after the float) instead of offset 8. The GPU still reads the
vec2 at the std140-mandated offset 8, so `resolution.x` picks up what the
writer meant as `resolution.y` (33) and `resolution.y` picks up the zero at
offset 12 — exactly the `(33, 0)` the reporter observed. The reproducer in
`main.c` does the same sequential packing and demonstrates the same shifted
readback on a pure-OpenGL driver, independent of three.js.

Maintainer @Mugen87 summarised it verbatim in the thread:

> I think the issue is that the `vec2` data start at the wrong location in
> the buffer. Normally a 8 byte boundary for `vec2` is required but that is
> currently ignored.

The fix landed in PR #28834 ("WebGLUniformsGroups: Fix buffer offset
calculation.") which corrects the offset computation in
`src/renderers/webgl/WebGLUniformsGroups.js`.

The vec3-after-float case works by accident because `vec3` has base
alignment 16: the naive sequential layout already happens to round up to 16
before writing the vec3, so the CPU and GPU views agree.

## Fix
```yaml
fix_pr_url: https://github.com/mrdoob/three.js/pull/28834
fix_sha: 5457a9d378e9a45e133099063994086fdf84a996
fix_parent_sha: 4c14bb184ca3f1a6085473de6cd2c279253f28b4
bug_class: framework-internal
files:
  - src/renderers/webgl/WebGLUniformsGroups.js
change_summary: >
  Corrects the running-offset computation in `WebGLUniformsGroups` so each
  uniform is written at an offset that respects its std140 base alignment.
  In particular, a `vec2` that follows a `float` is now placed on an 8-byte
  boundary (skipping 4 bytes of padding) instead of immediately after the
  float, matching what the shader reads.
```

## Upstream Snapshot
- **Repo**: https://github.com/mrdoob/three.js
- **SHA**: 4c14bb184ca3f1a6085473de6cd2c279253f28b4
- **Relevant Files**:
  - src/renderers/webgl/WebGLUniformsGroups.js
  - src/core/UniformsGroup.js
  - src/core/Uniform.js

## Difficulty Rating
4/5

## Adversarial Principles
- cross-layer-mismatch
- silent-spec-violation
- alignment-invisible-from-source

## How OpenGPA Helps
Dumping the bound UBO's raw bytes alongside the fragment shader's reflected
std140 member offsets makes the mismatch obvious: the CPU has `33.0f` at byte
offset 4 while the shader reads `resolution.x` from byte offset 8. A single
`overview` + `uniform-buffer-dump` pair at the failing draw call pinpoints
the packing error without needing to read any three.js source.

## Source
- **URL**: https://github.com/mrdoob/three.js/issues/28818
- **Type**: issue
- **Date**: 2024-07-06
- **Commit SHA**: (n/a)
- **Attribution**: Reported by @marco-pagliaro (three.js #28818); diagnosis confirmed by @Mugen87; fix by @Mugen87 in PR #28834.

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
  region:
    kind: pixel
    x: 128
    y: 128
  expected_rgba: [28, 84, 0, 255]
  actual_rgba:   [84, 0, 0, 255]
  tolerance: 2
```

## Predicted OpenGPA Helpfulness
- **Verdict**: yes
- **Reasoning**: The bug is entirely in the byte-level contents of a uniform buffer versus the std140 layout the shader expects. OpenGPA's per-draw-call uniform-buffer dump plus reflected block layout gives both sides of that mismatch in one query, whereas a source-only reviewer has to manually trace three.js's offset bookkeeping and mentally simulate std140 alignment to see the discrepancy.

## Observed OpenGPA Helpfulness
- **Verdict**: ambiguous
- **Evidence**: validation skipped (--no-validate)
