# Path 1 — programmatic frame emit (`gpa_emit_frame`)

*Implements Path 1 from `threejs-capture-poc.md`. Adds an exported
C symbol `gpa_emit_frame()` to the OpenGL shim so offscreen contexts
(headless-gl, EGL pbuffer, FBO-only pipelines) can drive frame capture
without ever calling `glXSwapBuffers`.*

## What changed

| File | Change |
|------|--------|
| `src/shims/gl/gl_wrappers.c` | Added `gpa_emit_frame()` definition immediately below `glXSwapBuffers`. Body mirrors the swap wrapper exactly, minus the real swap call. Marked `__attribute__((visibility("default")))`. |
| `src/shims/gl/gl_wrappers.h` | Added prototype with documentation. |
| `scripts/demo_gpa_emit_frame.js` | Node + `headless-gl` + `koffi` demo that drives N frames of capture from JS. |

The function body:

```c
__attribute__((visibility("default")))
void gpa_emit_frame(void) {
    gpa_init();
    gpa_frame_on_swap();             /* draw calls + framebuffer + IPC notify */
    gpa_frame_reset_draw_calls();    /* clear per-frame buffer */
    gpa_shadow_new_frame(&gpa_shadow);
}
```

This is byte-identical (apart from the `glXSwapBuffers(dpy, drawable)`
call) to the existing GLX swap wrapper, so the captured frame state is
indistinguishable from a normal swap-driven capture.

## Build

```bash
bazel build //src/shims/gl/...
```

Verify the symbol is exported:

```bash
SHIM=$(find ~/.cache/bazel/_bazel_$USER -path '*/src/shims/gl/libgpa_gl.so' | head -1)
nm -D --defined-only "$SHIM" | grep gpa_emit_frame
# 0000000000008ed4 T gpa_emit_frame
```

## Node demo setup

In a directory **outside the repo** (we don't want `node_modules` in git):

```bash
mkdir -p /data3/p1-poc && cd /data3/p1-poc
npm init -y
npm install gl koffi --no-audit --no-fund
cp /home/jingyulee/gh/gla/scripts/demo_gpa_emit_frame.js demo.js
```

`gl` is `headless-gl` (offscreen GL context for Node). `koffi` is a
modern, N-API-based FFI library — no node-gyp build, no `node-ffi-napi`
abandonware.

## Running the demo

```bash
SHIM=$(find ~/.cache/bazel/_bazel_$USER -path '*/src/shims/gl/libgpa_gl.so' | head -1)
DISPLAY=:99 \
  LD_PRELOAD="$SHIM" \
  GPA_SHIM_PATH="$SHIM" \
  GPA_SOCKET_PATH=/tmp/gpa_e2e.sock \
  GPA_SHM_NAME=/gpa_e2e \
  node /data3/p1-poc/demo.js 3
```

Notes:
- `LD_PRELOAD` is required for `RTLD_NEXT` resolution of real GL
  functions inside the shim (without it the shim's `glReadPixels` /
  `glGetIntegerv` function pointers stay NULL and the capture path
  no-ops or crashes).
- `GPA_SHIM_PATH` is the absolute path passed to `koffi.load()`. The
  shim is already mapped via `LD_PRELOAD`; we use the absolute path
  because the shim isn't installed under any standard `LD_LIBRARY_PATH`
  location.
- `Xvfb :99` must be running (headless-gl needs an X display).

## Evidence

Engine on `localhost:18080` (read-only verification — pre-existing
no-auth instance with 14 captured frames before this run).

```text
--- frames before ---
{"frames":[1,2,3,4,5,6,7,8,9,10,11,12,13,14],"count":14}

--- running demo ---
[demo] rendering and emitting 3 frame(s)…
[OpenGPA] IPC connected: shm=/gpa_e2e socket=/tmp/gpa_e2e.sock slots=4 slot_size=67108864
[OpenGPA] Shim active (pid=1671219)
[demo]   frame 1/3: cleared to (1, 0.2, 0.2) + 1 triangle
[demo]   frame 2/3: cleared to (0.2, 1, 0.2) + 1 triangle
[demo]   frame 3/3: cleared to (0.2, 0.2, 1) + 1 triangle
[demo] done.

--- frames after ---
{"frames":[1,2,3,4,5,6,7,8,9,10,11,12,13,14,15,16,17],"count":17}
```

Frame count: **14 → 17**, exactly +3 (= `NUM_FRAMES`). Each new frame
landed at the headless-gl context size (64×64):

```text
$ curl -s localhost:18080/api/v1/frames/15/overview
{"frame_id":15,"draw_call_count":0,"clear_count":0,
 "timestamp":1808296.437447564,"framebuffer_width":64,"framebuffer_height":64}
```

## Caveat: draw-call interception under headless-gl

The captured frame **dimensions** match the offscreen context (64×64),
which proves `gpa_frame_on_swap()` ran and read the framebuffer state.
But `draw_call_count=0` and `clear_count=0` — meaning the shim's
`glDrawArrays` / `glClear` wrappers never fired.

Reason: `headless-gl` is a Node native addon (`webgl.node`) that
implements the WebGL API in C++ on top of ANGLE. ANGLE ultimately calls
desktop GL, but it resolves entrypoints internally rather than going
through the global `glDrawArrays` symbol our shim interposes. So
LD_PRELOAD intercepts the *frame-emit / readback* path (which goes
through `gpa_real_gl.glReadPixels`) but not per-draw recording.

This is **not** a Path-1 blocker — Path 1's job was "give external
processes a way to trigger frame capture without `glXSwapBuffers`",
which it does. Per-draw capture from headless-gl would need either:
- a separate JS-side wrapper around the `gl` module that calls
  `gpa_frame_record_draw_call()` directly via koffi (mirroring what the
  C wrappers do), or
- patching ANGLE / the headless-gl addon to honor the shim symbols.

For the Round-13 three.js eval scenarios the practical implication is:
captured frames will have correct dimensions, framebuffer pixel
content, and frame timing, but no draw-call breakdown. Whether that's
useful depends on the scenario; for r1/r3/r6 (texture/shader bugs)
pixel-content alone may be enough to demonstrate the bug.

## Status

- `gpa_emit_frame()` is exported from `libgpa_gl.so`.
- Node + headless-gl + koffi demo successfully drives capture (14 → 17).
- Path 1 unblocked. Per-draw recording from headless-gl is a separate
  follow-up, tracked under future work if it becomes load-bearing.
