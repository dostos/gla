# S3: Depth Buffer Never Cleared Between Frames

## Bug

After the first frame, `glClear` is called with only `GL_COLOR_BUFFER_BIT`.
`GL_DEPTH_BUFFER_BIT` is omitted. The depth values written to the depth
buffer in frame 1 (from the quad at z=-0.2) persist into frame 2 and
subsequent frames. The quad drawn at z=-0.8 fails the depth test against
the stale z=-0.2 values and is not rendered.

**Location:** `s3_depth_never_cleared.c`, inside the render loop on frames
1 through 4 — the `glClear` call uses `GL_COLOR_BUFFER_BIT` only.

## Problem Description (What the User Sees)

Frame 1 renders a green quad at z=-0.2 correctly. From frame 2 onward, the
orange quad at z=-0.8 should appear, but the screen shows only the clear
color (dark olive). The geometry is completely invisible because every
fragment fails the `GL_LESS` depth test against the stale z=-0.2 depth
values left over from frame 1.

## Source Attribution

Inspired by p5.js issue #5514:
https://github.com/processing/p5.js/issues/5514

## Difficulty Rating

**Medium (3/5)**

The symptom (geometry disappears after the first frame) is dramatic and
obvious to a user but the cause is non-trivial. An agent must identify
that the depth test is enabled, that `glClear` is missing
`GL_DEPTH_BUFFER_BIT`, and connect the stale depth values from frame 1 to
the failing depth test in frame 2. There is no GL error.

## Adversarial Principles

- **Cross-frame state**: The depth buffer is cleared in frame 0 correctly;
  the bug only affects frames 1+. An agent inspecting a single frame's
  draw call stream will see a correct-looking `glClear`.
- **Absence-of-evidence**: The bug is a missing flag in an otherwise valid
  `glClear` call, not an incorrect call.
- **Conditional code path**: The clear logic is branched on `frame == 0`,
  making it easy to miss that the branches differ in their clear mask.

## How OpenGPA Helps

```
inspect_drawcall(draw_id=1, query="depth_state")
```

OpenGPA can report the depth buffer contents and the clear mask used at the
start of each frame. For frame 2 the output would show:

```json
{
  "clear_mask": "GL_COLOR_BUFFER_BIT",
  "depth_test_enabled": true,
  "depth_func": "GL_LESS",
  "depth_buffer_cleared_this_frame": false
}
```

The `depth_buffer_cleared_this_frame: false` flag immediately surfaces the
bug. A code-only agent must cross-reference the `glClear` call, the
`glDepthFunc` setting, and the z-coordinates of both quads across two
separate frame code paths.
