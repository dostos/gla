# S4: Stale Texture After FBO Switch

## Bug

After rendering into an FBO with `tex_render` bound to texture unit 0,
switching back to the default framebuffer for pass 2 does not rebind
`tex_scene`. `tex_render` (containing red pixels) is still bound to unit 0
when the screen-space quad is drawn, so the screen shows red instead of
the intended blue from `tex_scene`.

**Location:** `s4_fbo_texture_leak.c`, pass 2 render block — the
`glBindTexture(GL_TEXTURE_2D, tex_scene)` call is missing before
`glDrawArrays`.

## Problem Description (What the User Sees)

The screen should display a blue quad (from `tex_scene`). Instead it
displays a red quad (from `tex_render`). The FBO rendering in pass 1
appears to "leak" its texture binding into pass 2. There is no GL error;
the program runs and exits cleanly.

## Source Attribution

Inspired by wgpu issue #1188:
https://github.com/gfx-rs/wgpu/issues/1188

## Difficulty Rating

**Hard (4/5)**

The symptom (wrong color) is clear but diagnosing the root cause requires
understanding the interaction between FBO rendering, texture bindings, and
the persistence of GL texture unit state across framebuffer switches.
An agent must recognize that `glBindFramebuffer` does not reset texture
bindings, and then identify which pass introduced the stale binding. In a
real engine with many render passes and textures, tracing the binding
provenance is very difficult from source code alone.

## Adversarial Principles

- **Cross-pass state leakage**: The bug originates in pass 1 but only
  manifests in pass 2. Inspecting either pass in isolation looks correct
  (pass 1 sets up the binding correctly; pass 2 has a logically correct
  `glUniform1i` but a missing `glBindTexture`).
- **FBO/texture orthogonality confusion**: Developers often assume that
  switching framebuffers resets texture bindings; it does not.
- **Absence-of-evidence**: The missing `glBindTexture` call is invisible;
  there is no incorrect call at the bug site.

## How OpenGPA Helps

```
inspect_drawcall(draw_id=2, query="textures")
```

OpenGPA captures the texture unit state at every draw call, including the
source texture object ID and its pixel content. For pass 2 draw the output
would show:

```json
{
  "TEXTURE_UNIT_0": {
    "id": 1,
    "label": "tex_render",
    "size": "64x64",
    "sample": "#FF0000"
  }
}
```

The `label: "tex_render"` and `sample: "#FF0000"` immediately expose that
the FBO color attachment, not the scene texture, is being sampled. A
code-only agent must trace every `glBindTexture` call across both render
passes in execution order to reconstruct the unit-0 binding at the time of
the pass 2 draw.
