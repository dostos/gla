# three.js capture POC — verdict and paths forward

*Investigation: 2026-04-30. Goal: make R13 maintainer-framing scenarios
(r1, r3, r6, r13) runnable under the OpenGPA OpenGL shim so we can
generate captured frames and run with_gpa eval mode against them.*

## TL;DR

**Blocked, but not fundamentally.** The simplest path (Node.js +
`headless-gl`) doesn't capture frames out of the box because
`headless-gl` never calls `glXSwapBuffers` — and `glXSwapBuffers` is
the OpenGPA shim's only frame-boundary trigger. Three concrete paths
forward, in increasing order of leverage and effort.

## What was tried

### Path 1: Node.js + headless-gl + LD_PRELOAD ❌

Setup: `npm install gl` (in `/data3/threejs-poc`), Node 20, Xvfb on
`:99`, OpenGPA engine running on `localhost:18080`, `LD_PRELOAD` set
to `libgla_gl.so`.

Test script clears to red, reads back pixels, exits cleanly.

**Result:**
- Shim *does* attach to the Node process (no LD_PRELOAD warning,
  `webgl.node` dlopens libGL.so at runtime via ANGLE — so the
  interposition surface is there).
- But the frame count on the engine stays at 14 before and after.
  Zero frames captured.

**Why:** headless-gl uses ANGLE → desktop GL, but creates a true
*offscreen* context with no swapchain and never calls
`glXSwapBuffers`. The shim's frame-emit path is gated on
`glXSwapBuffers` (`src/shims/gl/gl_wrappers.c:358-364` —
`gpa_frame_on_swap()` is the only call site that flushes a frame to
the engine). No swap = no frame.

### Path 2: chromium-headless + LD_PRELOAD (not tested)

Chromium *does* call `glXSwapBuffers` from its GPU process (when
launched with `--use-gl=desktop --disable-gpu-sandbox --no-sandbox`).
This would let three.js examples render in a real browser context with
the shim attached.

**Not tested in this session** — would need an HTML harness, a way to
load the buggy three.js commit per scenario, and likely Puppeteer or
similar to drive the page. Probably 2-4 hours of additional work.

### Path 3: Programmatic frame trigger (not implemented)

Add a small exported C symbol to the shim — e.g.
`extern void gpa_emit_frame(void);` — that does the same work as the
inside of the `glXSwapBuffers` wrapper:

```c
void gpa_emit_frame(void) {
    gpa_init();
    gpa_frame_on_swap();
    gpa_frame_reset_draw_calls();
    gpa_shadow_new_frame(&gpa_shadow);
}
```

Any process under LD_PRELOAD can then `dlsym` and call this from
JavaScript via Node's FFI / N-API, from Python via ctypes, etc.
**~10 LoC change**, plus a small N-API wrapper or `node-ffi-napi`
binding to expose it to Node.

## Recommendation

**Do Path 3 first.** It's the smallest change, unlocks the
already-existing headless-gl path, and is a generally useful capability
(any Node/Python/whatever app can drive frame capture without needing a
windowed context). Then revisit Path 2 if we want to capture *real*
three.js examples in a browser harness.

For the R13 maintainer-framing eval specifically:
- r1, r3, r6 reproduce on three.js WebGL — once Path 3 lands, port the
  buggy three.js commit's WebGL example into a Node.js + headless-gl
  + three.js Node-render harness, call `gpa_emit_frame()` between
  rendering steps, capture.
- r13 (autoClear + WebGPURenderer) is WebGPU-only and headless-gl
  doesn't support WebGPU. r13 stays blocked until either (a) we add
  a Vulkan-side WebGPU translation path or (b) Path 2 gives us
  Chromium with WebGPU enabled. Defer.

## Concrete artifacts

- `/data3/threejs-poc/test.js` — minimal headless-gl test script
  (proves headless-gl works, demonstrates the LD_PRELOAD attaches but
  no frame is captured).
- `/data3/threejs-poc/package.json` — `npm install gl`.
- This document.

No code changes were committed to the repo. Picking Path 3 next would
require a small commit to `src/shims/gl/gl_wrappers.c` + corresponding
header + a Node-side glue module.

## Decision points for the user

1. **Path 3 (programmatic emit)** — ~30 min implementation + Node FFI
   wrapper, unblocks all WebGL-based R13 scenarios.
2. **Path 2 (chromium harness)** — half-day setup, captures real
   browser three.js including ANGLE-translated paths.
3. **Defer, prioritize Bevy** — the parallel B task already produced
   5 Bevy scenarios that *don't* need this work; we could run those
   under the verified Vulkan shim path first and only revisit three.js
   when bandwidth allows.
