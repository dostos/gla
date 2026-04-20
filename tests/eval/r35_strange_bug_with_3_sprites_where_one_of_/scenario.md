# R35: Strange bug with 3 sprites where one uses a gdshader with a uniform

## User Report
Hi guys, I am porting a circle android jump game to Godot 4 using the Vulkan renderer. I am using an old phone Xiaomi Mi A2 (Android 10, Vulkan 1.0, GLES 3.2).

I found a strange bug where I am rendering 3 sprites: two sprites use a PNG, the third uses a PNG with a gdshader.

Tested situations:

1. When I hide one of them (doesn't matter which) everything is working. So with one sprite with PNG and a second with gdshader, everything is working.
2. When I remove the gdshader from the sprite, everything is working.
3. When I remove the gdshader but add more sprites, everything is working.

The shader is:
```
shader_type canvas_item;

uniform vec4 color : source_color;

void fragment() {
    COLOR.rgb = color.rgb;
}
```

I did tests on other phones like Moto G5 (Android 12) and Samsung A52 (Android 12), and on PC as well, and everything is working. It also works in the Compatibility renderer.

Later narrowed down: the crash happens because of the line `uniform vec4 color : source_color;` — when I don't use it, it works fine. Also reproduces with an empty `fragment()` body as long as the uniform is declared. Reproduces on Godot 4.0, 4.1, 4.1.1, 4.2.dev2, and 4.2.1. Godot 3.5.2 works as expected.

A second reporter experiences a similar issue on Sony Xperia XZ1 Compact running Android 11, narrowed the problem to the `uniform` feature, and confirms that hardcoding the value makes the crash go away.

## Expected Correct Output
Three sprites render: two PNG-textured sprites plus a third sprite whose fragment color is driven by a `uniform vec4 color` in a `canvas_item` shader. The frame reaches `vkQueuePresentKHR` without a device lost / driver abort.

## Actual Broken Output
On the affected Android Vulkan drivers (Xiaomi Mi A2 / Adreno-class Android 10, Sony Xperia XZ1 Compact / Android 11) the app crashes during frame submission as soon as the scene contains 3+ canvas_item quads and at least one of them binds a material whose shader declares any `uniform` (even unused). Removing the uniform, removing one sprite, or using the Compatibility (OpenGL) renderer avoids the crash. Newer Android phones (Moto G5 Android 12, Samsung A52 Android 12, Samsung Tab S7) are unaffected.

## Ground Truth
No upstream fix has landed for this issue — it remains open with no maintainer patch merged. The authoritative narrowing comes from the reporter and a second affected user, not a Godot contributor diagnosis.

The reporter narrowed the trigger precisely to the `uniform` declaration in the canvas_item shader:

> @Alex2782 crash happens because of this line: `uniform vec4 color : source_color;` — when I don't use it, works fine

and showed the crash survives removing the uniform's use (empty `fragment()` body) and removing the `: source_color` hint, and reproduces with `uniform vec3` too:

> yup, problem is in word `uniform` :/ this doesn't work as well:
> ```
> shader_type canvas_item;
> uniform vec4 color;
> void fragment() { }
> ```

A second affected user independently corroborated the narrowing:

> I experience a similar issue on Sony Xperia XZ1 Compact running Android 11. I narrowed down the problem to the `uniform` feature. If I hardcode the value, the game no longer crashes.

And the sprite-count dependency:

> problem happens when I use 3 sprites, and one of them uses `uniform vec4 color : source_color;` if I use 2 sprites, everything works. Probably the problem is in vulkan driver, because when I use the newer phone, motorola g5, works fine.

What the upstream record does NOT establish: the exact RenderingDeviceDriverVulkan code path at fault, whether it is a Godot uniform-buffer binding bug that only trips old Adreno drivers or a pure driver bug. Maintainers themselves concluded the issue is likely device/driver-specific and not reproducible without the hardware:

> Since only a single device-type shows this problem, it might be hardware-related. That would make it difficult to fix this on the Godot-side.

So the corroborated ground-truth diagnosis is: **on older Android Vulkan drivers (pre-Vulkan-1.1 on Adreno-class GPUs circa Android 10/11), binding a canvas_item material whose shader declares a `uniform` at the same time as 3+ canvas_item draw calls triggers a driver-side abort during command submission**. Triggering does not require the uniform to be read, only declared. The issue remains open as of the latest comment; no maintainer has bisected to a specific commit or proposed a workaround at the Godot level.

## Difficulty Rating
5/5

## Adversarial Principles
- Device-specific reproduction (the bug cannot be observed on the reviewer's hardware, so the agent must reason from logs and narrowing experiments alone)
- Minimum-count threshold (the bug only triggers with 3+ canvas_item draws — 2 is fine — so single-draw-call inspection misses it)
- Declaration-only trigger (the uniform does not need to be used; static shader analysis of the fragment body will not reveal the link)
- Cross-stack ambiguity (is it Godot's uniform-set binding code, the SPIR-V it emits, or the Adreno driver? Upstream never resolved this)
- No upstream fix exists; agent must report honest uncertainty rather than claim a root cause

## How OpenGPA Helps
The 3-sprite threshold is observable as a state-change signature: OpenGPA's `list_draw_calls` on an affected capture shows the uniform-bearing program bound alongside two uniform-less programs, and `get_draw_call` reveals that the uniform buffer for the third sprite's material is allocated and bound even when the shader body reads nothing. That lets the agent corroborate the reporter's narrowing ("declaration, not use") by inspecting the captured uniform-buffer bindings per draw call rather than relying on shader source alone.

## Source
- **URL**: https://github.com/godotengine/godot/issues/79760
- **Type**: issue
- **Date**: 2023-07-23
- **Commit SHA**: (n/a)
- **Attribution**: Reported by @marko995; corroborated by a second user on Sony Xperia XZ1 Compact

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
  draw_call_min_count: 3
  expected_program_uniform_binding: present_without_read
  notes: |
    Scenario is device-specific (older Android Vulkan drivers). The minimal
    C repro here renders 3 quads where the third uses a fragment shader
    declaring a `uniform vec4 color` but not reading it from any mandatory
    path; on desktop the frame renders correctly and OpenGPA can confirm
    that the uniform buffer for draw call #3 is bound even without a read.
    Matching signature is: a draw call exists whose program declares a
    uniform, the uniform is bound, and the same frame contains 2+ other
    sprite draws using different programs without uniforms.
```

## Upstream Snapshot
- **Repo**: https://github.com/godotengine/godot
- **SHA**: 6c11fcd01a44d1e252489e33b40402ad959e6dc8
- **Relevant Files**:
  - drivers/vulkan/rendering_device_driver_vulkan.cpp
  - servers/rendering/renderer_rd/shaders/canvas.glsl
  - servers/rendering/renderer_rd/storage_rd/material_storage.cpp
  - servers/rendering/renderer_rd/renderer_canvas_render_rd.cpp
  - servers/rendering/shader_compiler.cpp

## Predicted OpenGPA Helpfulness
- **Verdict**: ambiguous
- **Reasoning**: OpenGPA can confirm the reporter's narrowing on a desktop capture (the uniform buffer for the third sprite's material is bound even when the fragment body is empty), which validates the "declaration, not use" hypothesis without needing the affected Android device. But the actual crash is inside a specific Adreno Vulkan driver on hardware OpenGPA cannot observe, so it cannot identify the ultimate fault line; it can only help the agent reach the same narrowed diagnosis the reporter did.

## Observed OpenGPA Helpfulness
- **Verdict**: ambiguous
- **Evidence**: validation skipped (--no-validate)
