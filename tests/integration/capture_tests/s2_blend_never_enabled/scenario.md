# S2: Blend Equation Never Enabled

## Bug

`glBlendFunc(GL_SRC_ALPHA, GL_ONE_MINUS_SRC_ALPHA)` is called to configure
alpha blending, but `glEnable(GL_BLEND)` is never called. OpenGL only
performs blending when `GL_BLEND` is explicitly enabled; the blend function
configuration is ignored when blending is disabled.

**Location:** `s2_blend_never_enabled.c`, inside the render loop before the
overlay draw call.

## Problem Description (What the User Sees)

The white background renders correctly. The semi-transparent red overlay
(color `(1, 0, 0, 0.5)`) should blend with the white background to produce
pink (`(1, 0.5, 0.5, 1)`), but instead renders as fully opaque red. The
alpha channel in the fragment color is ignored because blending is disabled.
There is no error message or warning from the GL driver.

## Source Attribution

Inspired by Godot Engine issue #76334:
https://github.com/godotengine/godot/issues/76334

## Difficulty Rating

**Easy (2/5)**

The symptom (wrong opaque color instead of blended transparency) is visually
obvious. The fix is a single missing `glEnable(GL_BLEND)` call. However,
the presence of `glBlendFunc` in the source creates a false sense of
correctness — an agent that searches for blend configuration calls will find
one, making the bug easy to overlook during code review.

## Adversarial Principles

- **Presence of related-but-incomplete code**: `glBlendFunc` is present and
  correct; only `glEnable(GL_BLEND)` is missing. An agent may conclude
  blending is configured when it finds `glBlendFunc`.
- **Absence-of-evidence**: The bug is a missing enable call, not a wrong
  parameter.
- **Silent failure**: The GL driver silently ignores the blend function when
  `GL_BLEND` is disabled; no error or warning is issued.

## How OpenGPA Helps

```
inspect_drawcall(draw_id=2, query="pipeline_state")
```

OpenGPA captures the full pipeline state at each draw call. The output for
draw 2 (the overlay) would show:

```json
{
  "blend_enabled": false,
  "blend_src_rgb": "GL_SRC_ALPHA",
  "blend_dst_rgb": "GL_ONE_MINUS_SRC_ALPHA"
}
```

The `blend_enabled: false` flag immediately identifies the issue. A
code-only agent must check both whether `glBlendFunc` was called (it was)
and whether `glEnable(GL_BLEND)` was called (it was not), which requires
scanning two separate call sites.
