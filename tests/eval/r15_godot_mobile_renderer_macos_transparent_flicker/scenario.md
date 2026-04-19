# R15_GODOT_MOBILE_RENDERER_MACOS_TRANSPARENT_FLICKER: Godot 4.6 Mobile renderer flickers transparent materials on macOS/Metal

## User Report
### Tested versions

Reproducible in: v4.6-beta1
Not reproducible in: v4.5.1

### System information

MacOS 15.7.3 - Godot 4.6 beta1, Mobile Render, MacMini4 M4 Pro

### Issue description

A rendering error occurred when I upgraded Godot from 4.5.1 to 4.6 beta1. This issue is triggered by camera rotation, causing flickering in meshes using transparent materials during rendering.
When I disabled material transparency, the issue disappeared. There was no problem when using the Forward+ and Compatibility renderers. The issue also did not occur when running the project on an Android phone with the Mobile Renderer. This problem only exists on macOS when using the Mobile Renderer.

### Steps to reproduce

1) open the project
2) Click the Rotate Camera button several times(<10) until the issue occurs.

### Minimal reproduction project (MRP)

[test-1.zip] (attached)

## Expected Correct Output
A transparent textured mesh rendered stably each frame as the camera
rotates: alpha-blended fragments blend with the background at their correct
depth, and values for a given draw's per-object uniforms (MVP, colour,
alpha) are whatever the CPU-side scene state wrote for that frame.

## Actual Broken Output
The transparent mesh flickers: on some frames portions of the mesh appear
to jump, show at wrong positions/orientations, or have wrong alpha/colour —
consistent with draws reading stale or garbled per-object uniforms from an
earlier frame's buffer slice in the dynamic UBO ring.

## Ground Truth
When a Godot 4.6 project using the Mobile renderer is run on macOS with the
Metal backend, meshes with transparent materials flicker / show stray
fragments whenever the camera (or animated node) rotates. Disabling
transparency hides the symptom. Reproducible only on macOS + Metal — not on
MoltenVK (Vulkan-on-macOS), not on Compatibility, not on Linux/Vulkan, not
on Android Mobile. Does not reproduce in Godot 4.5.1.

Per the upstream maintainer in the issue thread:

> I can reproduce – must be an issue with the dynamic uniform buffers. They
> are used for the forward+ and mobile renderers, and at least in mobile
> they are appear to be corrupted.

Bisection in comment 4 (by @Calinou) narrows the regression to two Metal
commits:
- `afd12e32ad66fabff5df35312311e38b0c396271` — surfaces the visible
  rendering issue via an animation-playback side effect
- `230adb7511b5298d67970f14990ae53f8be96e17` — the actual rendering
  regression, introduced "slightly further than the upgrade to Metal 4"

The pattern is classic dynamic-UBO-ring corruption: the Metal renderer
writes per-frame uniform data into a ring of GPU buffers and binds a slice
per draw; if fencing / slice-offset / in-flight tracking breaks, draw N
ends up reading the slice that frame N-1 (or N+1) is still writing. The
MVP and alpha fields are what change frame-to-frame with rotation, which
is exactly what flickers. MoltenVK, Compatibility (OpenGL), and the Vulkan
driver on Linux/Android all take different buffering paths and are
unaffected.

No fix has been merged as of draft date; diagnosis above is from the
maintainer and bisecting reporter, not from a fix commit.

## Difficulty Rating
4/5

## Adversarial Principles
- backend_specific_bug
- no_confirmed_fix
- dynamic_buffer_ring_corruption
- transparent_pass_only

## How OpenGPA Helps
OpenGPA does not target Metal, so it cannot capture the native Godot
process where this bug manifests. If the same pattern were reproduced
against an OpenGL/Vulkan backend, OpenGPA's per-draw uniform snapshot
(`get_draw_call` → UBO binding + contents) would expose stale MVP/alpha
values by diffing frame N against frame N-1 and showing a draw whose
uniforms match a prior frame's bound slice. But on the bug's actual
platform (Metal), OpenGPA is out of scope.

## Source
- **URL**: https://github.com/godotengine/godot/issues/114069
- **Type**: issue
- **Date**: 2026-04-18
- **Commit SHA**: (n/a — no fix merged)
- **Attribution**: Reported by GitHub user on issue #114069; bisected by @Calinou; diagnosis by @stuartcarnie (Godot Metal renderer maintainer)

## Tier
snapshot

## API
opengl

## Framework
none

## Upstream Snapshot
- **Repo**: https://github.com/godotengine/godot
- **SHA**: 5950fca36cb311edcc72e479effed5c477d20adb
- **Relevant Files**:
  - drivers/metal/rendering_device_driver_metal.mm
  - drivers/metal/rendering_device_driver_metal.h
  - drivers/metal/metal_objects.mm
  - drivers/metal/metal_objects.h
  - servers/rendering/renderer_rd/forward_mobile/render_forward_mobile.cpp
  - servers/rendering/renderer_rd/storage_rd/material_storage.cpp

## Bug Signature
```yaml
type: unexpected_state_in_draw
spec:
  draw_selector: transparent_pass
  state_field: uniform_buffer_contents
  expected_relation: matches_cpu_side_frame_state
  observed_relation: matches_prior_frame_slice_in_ring
```

## Predicted OpenGPA Helpfulness
- **Verdict**: no
- **Reasoning**: The bug is specific to Apple's Metal driver / Godot's Metal backend. OpenGPA intercepts OpenGL (and planned Vulkan) call streams via LD_PRELOAD / Vulkan layer on Linux; it has no Metal capture path and cannot attach to the macOS process where the corruption occurs. The analogous pattern (dynamic UBO ring slice aliasing) would be diagnosable by OpenGPA if it happened in GL/Vulkan, but this particular report will remain out of reach until a Metal-capable capture backend exists.

## Observed OpenGPA Helpfulness
- **Verdict**: ambiguous
- **Evidence**: validation skipped (--no-validate)
