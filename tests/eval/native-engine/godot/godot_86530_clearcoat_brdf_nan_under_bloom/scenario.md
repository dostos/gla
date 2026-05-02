# R21_CLEARCOAT_BRDF_NAN_UNDER_BLOOM: Clearcoat BRDF produces NaN pixels that leak through occluders under bloom

## User Report
### Tested versions

Found in v4.2.1.stable.official [b09f793f5]
and v4.3.stable.steam [77dcf97d8]

### System information

Godot v4.2.1.stable - Windows 11 (22621.2861) - Vulkan (Forward+) - dedicated NVIDIA GeForce RTX 3060 (NVIDIA; 31.0.15.4633) - 11th Gen Intel(R) Core(TM) i7-11700 @ 2.50GHz (16 Threads)

**Update** January 9 2025 system information,
Godot 4.3.stable.steam - Windows 11 (22631) - nVIDIA GeForce RTX 4070 Super (32.0.15.6636)

### Issue description

Lights are visible through objects with a material with Clearcoat enabled. It looks like a lens flare with a black point center, and it flickers between visible and invisible every frame that the camera is moved. Changing the Glow parameters affects how the artifact appears.

With a camera parameters with auto-exposure enabled it will cause the auto-exposure to jump all over the place to compensate for the bright spot.

### Steps to reproduce

- Make a new project
- 3D scene, with the default environment on, Glow on.
- Add a mesh instance in the scene, cube, with a standard material, enable Clearcoat.
- Add an OmniLight to the scene and move it away from the mesh.
- View the mesh with the light behind it (occluded). Moving the camera around shows the flicker.

### Minimal reproduction project (MRP)

MRP.zip (attached)

## Expected Correct Output
A uniformly-shaded 256×256 quad whose HDR RGBA16F target contains only finite,
non-negative values. Every pixel's red channel should be a finite specular
intensity (or zero), never NaN or ±Inf.

## Actual Broken Output
The center region of the rendered target reads back as NaN in the R/G/B
channels. On llvmpipe under Xvfb this usually shows as a black pixel
(NaN compared against the clear color collapses to zero after the blit);
on a real GPU with HDR + bloom the NaN propagates through the separable
Gaussian kernel and blooms out to a bright speck that appears to pass
through any geometry in front of the poisoned pixel.

## Ground Truth
A fragment shader implementing a GGX-style clearcoat distribution writes NaN
to an HDR color attachment for configurations where the clearcoat roughness
is clamped to zero (and NdotH ≈ 1). The NaN is invisible in a direct
tonemap but contaminates any downstream blur/downsample stage — exactly
matching the reported "lights visible through all objects" flicker when glow
is enabled in the Godot forward renderer.

The upstream issue's title states the root cause in one line:

> Lights are visible through all objects with a material with Clearcoat enabled due to NaN pixels being rendered

The body confirms the glow-dependent visual signature that is characteristic
of NaN contamination in an HDR target rather than a depth/z-fighting or
blend-state bug:

> It looks like a lens flare with a black point center, and it flickers between visible and invisible every frame that the camera is moved. Changing the Glow parameters affects how the artifact appears.

A second user independently confirmed the glow-dependent amplification and
ruled out it being a display-only artifact:

> For me this is only really visible when glow is on in the world environment. Without glow I just get a single black pixel or in some scenes I get 2 black pixels.

Two facts follow from these citations alone, without having to guess at the
exact shader line:

1. The shading pass is producing NaN pixel values in the HDR target used
   specifically by clearcoat-enabled materials. (Named in the title.)
2. The glow/bloom pass in the post-processing chain is reading those NaN
   pixels, spreading them across its blur kernel, and turning the
   single-pixel NaN into a visible bright disc. (Confirmed by both the
   reporter and the first commenter.)

The GGX microfacet distribution `D = a^2 / (pi * ((NdotH^2)(a^2-1) + 1)^2)`
is the standard term Godot uses for clearcoat. When the clearcoat roughness
is clamped to zero (`a = 0`) and the light-view-halfway geometry gives
`NdotH = 1` (i.e., a specular back-reflection coincidence), the denominator
becomes `1*0 + 1 - 1 = 0` and the term evaluates to `0 / 0 = NaN`. This is
the minimal configuration required to reproduce both facts listed above; no
upstream PR diagnosing the exact line was linked in the thread, so the
reproducer asserts only the shape of the failure rather than a specific
source-line fix.

## Difficulty Rating
4/5

## Adversarial Principles
- invisible-unless-post-processed: the bug does not manifest in the raw color
  buffer on every backend; it only becomes visible after the bloom pass reads
  the NaN.
- single-pixel-in-full-frame: a textual frame summary that just reports
  dominant color or a mean RGB will completely miss a single NaN pixel.
- configuration-dependent: reproduces only when clearcoat-enabled materials
  are drawn, so a blanket "NaN in shader" fuzzer is unlikely to find it.

## How OpenGPA Helps
The agent can ask OpenGPA for the clearcoat draw call's bound fragment
shader source alongside a per-pixel readback of its render target; a
histogram query over the HDR attachment immediately flags the NaN bin,
pointing the agent at the exact draw that emits it rather than at the
bloom pass where the symptom is visible.

## Source
- **URL**: https://github.com/godotengine/godot/issues/86530
- **Type**: issue
- **Date**: 2023-12-26
- **Commit SHA**: (n/a)
- **Attribution**: Reported by @KingTrance on godotengine/godot; MRP
  contributed by a commenter in the same thread.

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
  region: [0, 0, 256, 256]
  forbid_nan: true
  forbid_inf: true
  max_channel_value: 1.0e6
  description: |
    The clearcoat HDR target must contain only finite, bounded values.
    Any NaN or Inf pixel, or any value above 1e6, indicates the
    GGX-denominator-collapses-to-zero path has been hit.
```

## Upstream Snapshot
- **Repo**: https://github.com/godotengine/godot
- **SHA**: 4d1f26e1fd1fa46f2223fe0b6ac300744bf79b88
- **Relevant Files**:
  - servers/rendering/renderer_rd/shaders/scene_forward_lights_inc.glsl  # base of fix PR #108378 (clearcoat BRDF epsilon)
  - servers/rendering/renderer_rd/shaders/scene_forward_clustered.glsl
  - servers/rendering/renderer_rd/shaders/scene_forward_mobile.glsl

## Predicted OpenGPA Helpfulness
- **Verdict**: yes
- **Reasoning**: A textual frame summary will miss a single NaN pixel, but a
  per-pixel histogram or NaN-pixel-count query over the clearcoat pass's
  render target surfaces the bug immediately and identifies the specific
  draw call that emits it. Without that, an LLM staring at the post-bloom
  screenshot has no way to distinguish "NaN poisoned by bloom" from
  "lights genuinely visible through geometry" — the two look identical.

## Observed OpenGPA Helpfulness
- **Verdict**: ambiguous
- **Evidence**: validation skipped (--no-validate)
