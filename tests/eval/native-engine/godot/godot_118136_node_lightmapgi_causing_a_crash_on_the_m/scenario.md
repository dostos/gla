# R1_NODE_LIGHTMAPGI_CAUSING_A_CRASH_ON_THE_M: LightmapGI bake crashes on Adreno 710 mobile

> This scenario is snapshot-tier: diagnosis requires reading upstream code; capture is a context stub.

## User Report
### Tested versions

Tested on versions v4.6.0 to v4.6.2, both "stable".

### System information

Godot Engine v4.6.2.stable.official.71f334935 - https://godotengine.org OpenGL API OpenGL ES 3.2 V@0615.80 (GIT@406382a20f, I986008d073, 1704447428) (Date:01/05/24) - Compatibility - Using Device: Qualcomm - Adreno (TM) 710

### Issue description

It's hard to explain, but basically I built a scene using Gridmap3D and added some lights once I was sure the scene was finished, setting all the lights to static. Then I added LightmapGI to the scene and clicked "Bake." As expected, it froze for a few seconds since it's very demanding on the hardware, but it had never happened before that the node would crash the program. I tested it on simpler scenes and the bake worked normally, although the system would still freeze during the bake, which is expected.

I'm not sure if the issue is related to compatibility mode (OpenGL), but right now I'm unable to add lighting to my project because LightmapGI is crashing the engine. Note: the ".exr" file doesn't even get created, so it might be crashing before LightmapGI even starts calculating anything.

### Steps to reproduce

I built a scene using Gridmap3D and tried to bake it. All the meshes in tile format already have UVs for the Lightmap.

### Minimal reproduction project (MRP)

LightmapGI_Crash.zip (attached)

## Expected Correct Output
The bake completes, the engine writes a `.exr` lightmap file next to the
scene, and the scene renders with static indirect lighting contributed by the
LightmapGI node.

## Actual Broken Output
The engine process aborts mid-bake. No `.exr` is produced. Only this
specific scene (`level_0.res`) reproduces; simpler scenes bake (slowly but)
without crashing on the same device.

## Ground Truth
On the Compatibility (OpenGL ES) renderer of Godot 4.6, clicking "Bake" on a
`LightmapGI` node causes the engine to crash on an Adreno 710 mobile GPU. The
`.exr` output is never written, suggesting the crash happens before the bake
pipeline produces its first output.

No upstream diagnosis exists for this report. The maintainers have not
commented; a second tester on a different Adreno part was unable to
reproduce:

> I can't reproduce on my phone. A MRP or more details about the issue
> will be nedeed.
> Godot v4.6.2.stable - Android ... Adreno (TM) 506

The reporter's device is an Adreno 710 and the non-reproducing tester's is
an Adreno 506, so the crash is at least correlated with a specific Adreno
SKU and/or driver build (`V@0615.80 ... Date:01/05/24`). Because the report
is device-specific, happens inside a complex bake pipeline, and no fix PR or
commit identifies a root cause, the crash cannot be attributed to a specific
GL call pattern from the issue text alone.

## Difficulty Rating
5/5

## Adversarial Principles
- device_specific_driver_bug
- no_upstream_diagnosis
- second_tester_could_not_reproduce

## How OpenGPA Helps
If the crash is reached through a specific GL call on Adreno, OpenGPA's
per-draw call log plus framebuffer completeness queries would show which
operation immediately preceded the abort — information the reporter cannot
extract from a stock Godot build on a phone. Without an upstream diagnosis,
OpenGPA's contribution here is limited to surfacing the last GL state
before the crash.

## Source
- **URL**: https://github.com/godotengine/godot/issues/118136
- **Type**: issue
- **Date**: 2026-04-19
- **Commit SHA**: (n/a)
- **Attribution**: Reported by the Godot issue author; non-reproduction
  comment by @matheusmdx.

## Tier
snapshot

## API
opengl

## Framework
none

## Bug Signature
```yaml
type: unexpected_state_in_draw
spec:
  expectation: bake pipeline completes without GL error or context loss
  observed: process abort on Adreno 710 before .exr output
```

## Predicted OpenGPA Helpfulness
- **Verdict**: no
- **Reasoning**: No confirmed root cause exists upstream, the bug is
  device-specific to one Adreno SKU, and a second tester could not
  reproduce. OpenGPA cannot add value to a report that is not reproducible
  on the evaluator's hardware and has no grounded diagnosis to validate
  against.

## Observed OpenGPA Helpfulness
- **Verdict**: ambiguous
- **Evidence**: validation skipped (--no-validate)

## Upstream Snapshot
- **Repo**: https://github.com/godotengine/godot
- **SHA**: b508fa698b943c1881269062c757e2738c7471c4
- **Relevant Files**:
  - scene/3d/lightmap_gi.cpp (inferred — LightmapGI bake entry point)
  - modules/lightmapper_rd/lightmapper_rd.cpp (inferred — bake driver)
  - drivers/gles3/rasterizer_scene_gles3.cpp (inferred — compat-mode path)
