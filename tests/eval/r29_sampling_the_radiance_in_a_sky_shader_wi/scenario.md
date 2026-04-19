# R29: Sky shader RADIANCE sampling with EYEDIR returns wrong direction after octahedral rewrite

> This scenario is snapshot-tier: diagnosis requires reading upstream code; capture is a context stub.

## User Report
### Tested versions

- Reproducible in v4.6.stable.official [89cea1439]
- Not reproducible in v4.5.1.stable.official [f62fdbde1]

### System information

Godot v4.6.stable - Ubuntu 25.10 on Wayland - Vulkan (Forward+) - dedicated
AMD Radeon RX 9060 XT (RADV GFX1200) - Intel(R) Core(TM) i7-6700K

### Issue description

Sampling the RADIANCE map in a sky shader using the [documentation's approach](https://docs.godotengine.org/en/stable/tutorials/shaders/shader_reference/sky_shader.html)
does not work correctly. The sampling is not correct, specifically towards
the negative Z world direction.

By the documentation I mean sampling it with the EYEDIR.
```
COLOR = texture(RADIANCE, EYEDIR).rgb;
```

The video below shows the result of trying to render a cubemap which denotes
its +/- (x,y,z) faces. (see reproduction steps for exact code)

I assume this is the result of the change towards octahedral radiance maps in
https://github.com/godotengine/godot/pull/107902 and
https://github.com/godotengine/godot/pull/114773

### Steps to reproduce

Create a sky shader with the following code and render it using an
illustrative cubemap. The rendered sky does not render the cubemap correctly.

```
shader_type sky;

uniform samplerCube _cubemap;

void sky() {
    if (AT_CUBEMAP_PASS) {
        COLOR = texture(_cubemap, EYEDIR).rgb;
    } else {
        COLOR = texture(RADIANCE, EYEDIR).rgb;
    }
}
```

## Expected Correct Output
Sampling `RADIANCE` with `EYEDIR` should yield the radiance-probe color in the
world direction `EYEDIR`, so pointing the camera at each cube face shows that
face of the source cubemap.

## Actual Broken Output
The radiance lookup returns a garbled mapping. Toward `-Z` the sampled color is
visibly wrong (see the MRP video). The sky still draws, but the cube-face
labels do not match the camera direction.

## Ground Truth
The radiance probe's backing storage changed from a cubemap to an octahedral
2D map in PR #107902 ("Rewrite Radiance and Reflection probes to use Octahedral
maps"). The shader-compiler exposure of `RADIANCE` was not updated at the same
time — user shaders still call `texture(RADIANCE, EYEDIR)` as if it were a
`samplerCube`, but the underlying resource is now a `sampler2D` holding an
octahedral encoding, so the direction is interpreted as a 2D coordinate with no
octahedral decoding. PR #114773 explicitly calls this out:

> Radiance was a textureCube, but now it is a texture2D. For compatibility
> purposes we need to continue exposing a cube texture. So we need to add this
> scaffolding to properly sample from it.

The fix adds a compatibility handler that rewrites the user's
`texture(RADIANCE, dir)` call into an octahedral-UV lookup. The regression
window is Godot 4.6 pre-#114773 (reported against `4.6.stable [89cea1439]`).

## Difficulty Rating
4/5

## Adversarial Principles
- regression_from_refactor
- backend_storage_format_change_without_shader_shim
- silent_type_mismatch_direction_vs_uv
- octahedral_coordinate_conversion_missing

## How OpenGPA Helps
Querying the draw call's bound textures reveals that `RADIANCE` is a 2D
texture, not a cubemap — contradicting the shader's `textureCube`-style usage
pattern. Reading the compiled sky fragment shader shows the sampler type and
the direct `texture(sampler2D, vec3)` call with no octahedral conversion,
which immediately localizes the bug to missing RADIANCE scaffolding rather
than to a logic error in the user shader.

## Source
- **URL**: https://github.com/godotengine/godot/issues/115441
- **Type**: issue
- **Date**: 2025-11-30
- **Commit SHA**: (n/a)
- **Attribution**: Reported by Godot user; fix by @clayjohn in PR #114773

## Tier
snapshot

## API
opengl

## Framework
godot

## Bug Signature
```yaml
type: unexpected_color
spec:
  region: full_frame
  expected_pattern: radiance_probe_oriented_to_eyedir
  observed_pattern: sampled_as_2d_without_octahedral_decode
```

## Upstream Snapshot
- **Repo**: https://github.com/godotengine/godot
- **SHA**: 6f15a05b6cf5f87de80e09f960a0e7a7449db640
- **Relevant Files**:
  - servers/rendering/shader_compiler.cpp
  - servers/rendering/shader_compiler.h
  - servers/rendering/renderer_rd/shaders/environment/sky.glsl
  - servers/rendering/renderer_rd/environment/sky.cpp
  - servers/rendering/renderer_rd/environment/sky.h
  - drivers/gles3/shaders/sky.glsl
  - drivers/gles3/storage/light_storage.cpp

## Predicted OpenGPA Helpfulness
- **Verdict**: yes
- **Reasoning**: The root cause is a type/format mismatch between a shader's
  declared sampler usage and the actual bound texture. OpenGPA surfaces the
  bound texture target/format per draw call and the compiled shader source,
  which together expose the missing octahedral decode immediately. Without
  OpenGPA an agent would need to read Godot's shader-compilation pipeline end
  to end to find the same answer.

## Observed OpenGPA Helpfulness
- **Verdict**: ambiguous
- **Evidence**: validation skipped (--no-validate)
