# R27: Black squares on glass MeshPhysicalMaterial under direct light (r182)

## User Report
### Description

When I load the AnisotropyBarnLamp.glb model using the webgl_loaders_gltf
example and then add a DirectionalLight to the scene, small black squares
appear on the glass material.

I tried using SpotLight and PointLight as well, and the same issue occurs.
However, adding only an AmbientLight does not cause this problem.

If no light sources are added to the scene, the issue does not appear at all.

Additionally, when I increase the roughness of the glass material, the black
squares become larger until they cover the entire mesh.

### Reproduction steps

1. add AnisotropyBarnLamp.glb Model
2. add DirectionalLight

### Code (excerpted)

```js
import * as THREE from 'three';
import { GLTFLoader } from 'three/addons/loaders/GLTFLoader.js';
import { UltraHDRLoader } from 'three/addons/loaders/UltraHDRLoader.js';

const dl = new THREE.DirectionalLight(0xffffff, 30);
dl.position.set(0, 1, 0);
scene.add(dl);

new UltraHDRLoader()
    .setPath('textures/equirectangular/')
    .load('royal_esplanade_2k.hdr.jpg', function (texture) {
        texture.mapping = THREE.EquirectangularReflectionMapping;
        scene.background = texture;
        scene.environment = texture;
        // ... loadModel('AnisotropyBarnLamp')
    });

renderer = new THREE.WebGLRenderer({ antialias: true });
renderer.toneMapping = THREE.ACESFilmicToneMapping;
```

### Live example

* https://jsfiddle.net/Kasey/06xc9hnq/13/

### Screenshots

Without DirectionalLight: glass renders cleanly.

With DirectionalLight: small black squares appear on glass.

With DirectionalLight and glass material roughness 0.2: black squares cover
the mesh.

### Version

r182

## Expected Correct Output
Glass mesh lit by a DirectionalLight with smooth specular highlights and no black artifacts; roughness increases should blur the highlight, not produce black patches.

## Actual Broken Output
Black square patches appear wherever direct lighting and anisotropic specular interact; patches grow with roughness and cover the mesh at high roughness.

## Ground Truth
Comment 2 bisects the regression:
> After some debugging, #32330 introduced the regression.

PR #32330's description admits two shader changes that together produce out-of-range values clamped to black:

> * **Improved Diffuse Energy Conservation (GLSL & TSL)**: Changed the diffuse term calculation to conserve energy per-channel (`1.0 - totalScatteringDielectric`) rather than using the maximum component.
> * **Removed Redundant Saturation (GLSL & TSL)**: Removed `saturate()` from `V_GGX_SmithCorrelated_Anisotropic` as the visibility term is mathematically bounded.

Both claims fail in practice for anisotropic dielectrics under direct light:

1. `V_GGX_SmithCorrelated_Anisotropic` is `0.5 / (gv + gl)`. With strong anisotropy (`alphaT ≫ alphaB`) the denominator can approach zero at grazing tangent-view/light configurations, so the result is NOT bounded by 1 — the removed `saturate(v)` was load-bearing, not redundant.
2. With the visibility term blowing up, `totalScatteringDielectric` (= specular contribution) exceeds 1 on some channels. Per-channel `1.0 - totalScatteringDielectric` then goes negative, so `diffuseColor * diffuseScaling + specular` resolves to a negative number and clamps to black at the framebuffer. The previous max-component approach masked this because a single large channel pinned the diffuse scaling to zero uniformly rather than letting individual channels go negative.

The upstream repro also shows roughness sensitivity: higher roughness increases `alphaT * alphaB` asymmetry regions where `gv + gl` is small, widening the region of overshoot — matching the "black squares grow with roughness" observation.

The minimal C repro sweeps (view-angle, light-angle) across a quad with `alphaT=0.9, alphaB=0.02` and intentionally colored `F0`. The bad math reproduces: `Vis` overshoots, per-channel `1 - spec` goes negative, and patches of the quad read back as black.

## Difficulty Rating
4/5

## Adversarial Principles
- numeric_precision
- per_channel_energy_conservation_negative
- anisotropic_visibility_unbounded
- regression_from_refactor

## How OpenGPA Helps
Querying the framebuffer histogram in the lit region of the glass mesh reveals a bimodal distribution with a spike at (0,0,0) that shouldn't exist for a lit dielectric; combined with Tier-3 sidecar metadata identifying the draw as `MeshPhysicalMaterial` with `anisotropy > 0` and `transmission > 0`, the agent can cross-reference that the specific fragment shader chunk `lights_physical_pars_fragment.glsl` is in play and correlate the black pixels to negative values from the new per-channel diffuse term.

## Source
- **URL**: https://github.com/mrdoob/three.js/issues/33201
- **Type**: issue
- **Date**: 2026-04-19
- **Commit SHA**: (n/a)
- **Attribution**: Reported by @Kasey-zy; regression bisected by @Mugen87 to PR #32330

## Tier
core

## API
opengl

## Framework
none

## Bug Signature
```yaml
type: color_histogram_in_region
spec:
  region: { x: 0, y: 0, w: 512, h: 512 }
  forbidden_bucket: { r_max: 0.02, g_max: 0.02, b_max: 0.02 }
  min_fraction: 0.02
  description: "Black pixels (< 0.02 on all channels) should not appear in a lit-dielectric sweep; their presence indicates negative-after-clamp output from the broken energy-conservation + unsaturated anisotropic visibility math."
```

## Upstream Snapshot
- **Repo**: https://github.com/mrdoob/three.js
- **SHA**: 2c50dc2e3dd79338eea58bd41840db84d1087eee
- **Relevant Files**:
  - src/renderers/shaders/ShaderChunk/lights_physical_pars_fragment.glsl.js
  - src/nodes/functions/BSDF/V_GGX_SmithCorrelated_Anisotropic.js
  - src/nodes/functions/PhysicalLightingModel.js
  - src/renderers/shaders/ShaderChunk/lights_fragment_end.glsl.js

## Predicted OpenGPA Helpfulness
- **Verdict**: yes
- **Reasoning**: The bug manifests as anomalous black pixels in specific screen regions — exactly what framebuffer histogramming and per-draw state inspection are built for. OpenGPA's Tier-3 sidecar can identify the offending material (MeshPhysicalMaterial with anisotropy+transmission), and pixel-level queries can confirm the pre-clamp values are negative rather than dark-but-positive, pointing directly at the energy-conservation/visibility math rather than a lighting or geometry issue.

## Observed OpenGPA Helpfulness
- **Verdict**: ambiguous
- **Evidence**: validation skipped (--no-validate)
