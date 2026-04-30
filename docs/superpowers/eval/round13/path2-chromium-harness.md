# Path 2 — chromium-headless capture harness (BLOCKED)

*Investigation: 2026-04-30. Re-verified after `eglSwapBuffers` wrapper
added: still blocked. See "Follow-up" section below for the GPU-process
maps showing chromium loads its **bundled** ANGLE EGL stack, not the
system libEGL — so eglSwapBuffers interception bypasses chromium for
the same reason glXSwapBuffers did. Goal: verify chromium-headless under Xvfb
captures frames via the OpenGPA OpenGL shim (LD_PRELOAD libgpa_gl.so),
then build a minimal three.js harness for R13 maintainer-framing
scenarios (r1, r3, r6).*

## TL;DR

**Blocked at the ANGLE layer, not at the LD_PRELOAD layer.** The shim
loads correctly into chromium's GPU process and `libGL.so.1` is mapped
in `/proc/$GPU/maps`, but ANGLE resolves GL entrypoints by calling
`dlsym()` against a libGL handle it dlopened — not through the dynamic
linker's normal symbol search — so LD_PRELOAD interposition is bypassed
entirely. **Zero** calls to `glXSwapBuffers`, `glClear`, `glDrawArrays`,
or any other OpenGL function reach our shim's wrappers.

This is a structural mismatch, not a missing flag. Path 2 cannot
unlock R13 scenarios with the current shim design.

Recommended pivot: **Path 3 (programmatic `gpa_emit_frame()` exported
symbol)** — already implemented in the shim per
`docs/superpowers/eval/round13/threejs-capture-poc.md`. Drive the
three.js bug repros from a Node + headless-gl harness that calls
`gpa_emit_frame()` between renders.

## What worked (mechanically)

- A clean engine on port 18084, socket `/tmp/gpa_p2.sock`,
  shm `/gpa_p2`, started no-auth.
- Xvfb on `:99` (already running on this host).
- A non-snap chromium (Playwright-managed
  `~/.cache/ms-playwright/chromium-1208/chrome-linux64/chrome`) launched
  with `LD_PRELOAD=/tmp/libgpa_gl_p2.so`, our copy of the shim binary
  resolved from `find /home/jingyulee/.cache/bazel -name libgpa_gl.so |
  head -1` — necessary because `bazel-bin/src/shims/gl/libgpa_gl.so`
  resolves into a per-cache symlink and the worktree didn't have one
  at the time.
- A minimal three.js page (`tests/p2-poc/index.html`) drawing a single
  static triangle, with a `setTimeout(window.close, 8000)` exit hatch.

The flag set that **does propagate the shim into chromium's GPU
process** (verified via `grep libgpa_gl /proc/$GPU/maps`):

```bash
LD_PRELOAD=/tmp/libgpa_gl_p2.so \
GPA_SOCKET_PATH=/tmp/gpa_p2.sock \
GPA_SHM_NAME=/gpa_p2 \
DISPLAY=:99 \
$CHROME \
  --headless=new \
  --no-sandbox \
  --disable-gpu-sandbox \
  --use-gl=angle --use-angle=gl \
  --enable-webgl --ignore-gpu-blocklist --enable-unsafe-swiftshader \
  --window-size=400,300 \
  --user-data-dir=/tmp/p2-prof \
  file:///tmp/p2-index.html
```

Each flag rationale:

- `--headless=new`: legacy headless doesn't render WebGL.
- `--no-sandbox` + `--disable-gpu-sandbox`: keep LD_PRELOAD attached
  across chromium's child processes; the namespace sandbox would re-exec
  with a sanitized env.
- `--use-gl=angle --use-angle=gl`: route WebGL through ANGLE's
  desktop-GL backend, which on Linux maps to libGL.so / libGLX.so.
  This was the **only** combination that actually loaded `libGL.so.1`
  into the GPU process. `--use-gl=desktop` is rejected by chromium's
  internal allow-list (`Requested GL implementation (gl=none,angle=none)
  not found in allowed implementations: [(gl=egl-angle,angle=default)]`).
- `--enable-webgl`: explicit safety belt.
- `--ignore-gpu-blocklist`: without this, headless chromium puts WebGL
  on the blocklist when its Vulkan probe fails (it always does on
  software-only Mesa LLVMpipe stacks).
- `--enable-unsafe-swiftshader`: required since chromium 145+ for
  non-blocklisted WebGL on CPU-only stacks; without it three.js receives
  `WebGL: CONTEXT_LOST_WEBGL`.
- `--window-size=400,300`: matches the canvas in the HTML.

Snapshot of the chromium GPU process at the moment of attempted
WebGL render (PID 1708252 in our trace):

```
[1708252] --type=gpu-process shim=4
  libs:
    /home/.../chromium-1208/chrome-linux64/libEGL.so
    /home/.../chromium-1208/chrome-linux64/libGLESv2.so
    /tmp/libgpa_gl_p2.so                          ← our shim is loaded
    /usr/lib/x86_64-linux-gnu/libGL.so.1.7.0      ← system desktop GL
    /usr/lib/x86_64-linux-gnu/libGLX_mesa.so.0.0.0
    /usr/lib/x86_64-linux-gnu/libGLX.so.0.0.0
```

three.js confirmed it received a real WebGL context (with the windowed
chromium variant, log line):

```
INFO:CONSOLE: WebGL: CONTEXT_LOST_WEBGL: loseContext: context lost
INFO:CONSOLE: THREE.WebGLRenderer: Context Lost.
INFO:CONSOLE: THREE.WebGLRenderer: Context Restored.
INFO:CONSOLE: GL Driver Message (OpenGL, Performance, GL_CLOSE_PATH_NV,
              High): GPU stall due to ReadPixels
```

That last line ("GPU stall due to ReadPixels") proves three.js issued
draw calls and chromium read pixels back — there is real GL traffic.

## What didn't work (and why)

### Frame count: 0 before, 0 after (every variant)

```
$ curl -s http://127.0.0.1:18084/api/v1/frames | jq .count
0    # before launching chromium
0    # after launching chromium and rendering for 12 s
```

### Root cause: ANGLE bypasses LD_PRELOAD via direct dlsym

Built a control probe shim
(`/tmp/probe4.so` — separate from `libgpa_gl.so`) that exports its own
`glXSwapBuffers`, `glClear`, `glDrawArrays`, `glViewport`, etc., and
prints the call to stderr from a thin wrapper.

Sanity check — the probe **does** intercept calls from a known good
binary (one of our eval scenarios):

```
$ LD_PRELOAD=/tmp/probe4.so DISPLAY=:99 \
  bazel-bin/tests/eval/r15_godot_mobile_renderer_macos_transparent_flicker \
  2> /tmp/probe.log
$ grep "probe4 pid" /tmp/probe.log | head -5
[probe4 pid=1727050] glXMakeCurrent #1
[probe4 pid=1727050] glClearColor #1
[probe4 pid=1727050] glClear #1
[probe4 pid=1727050] glDrawArrays #1
[probe4 pid=1727050] glXSwapBuffers #1
```

Same probe attached to chromium-headless rendering three.js for 10 s:

```
$ ./scripts/p2_chromium_capture.sh tests/p2-poc/index.html  # with probe4
loaded events:           7    # 7 chromium child processes, all
                              # have probe4.so in their maps
glXSwapBuffers events:   0
eglSwapBuffers events:   0
glFlush events:          0
glFinish events:         0
glClear events:          0
glDrawArrays events:     0
glDrawElements events:   0
glViewport events:       0
glXMakeCurrent events:   0
glXChooseFBConfig events: 0
glXCreateContext events: 0
```

**Zero LD_PRELOAD interceptions across every GL function.** The probe is
demonstrably loaded into the GPU process (`probe=5` in
`/proc/$GPU/maps`) but its symbols are never invoked.

How chromium achieves this: ANGLE's GL backend (the implementation
behind `--use-angle=gl`) calls `dlopen("libGL.so", ...)` and then
`dlsym(handle, "glDrawArrays")` against that specific handle. Symbols
returned by `dlsym(handle, ...)` are resolved within the dlopened
library only, **never** going through the global symbol search that
LD_PRELOAD intercepts. Search-path interposition, in other words, is
defeated by handle-scoped lookup. Confirmed by `nm -D
chromium-1208/chrome-linux64/libGLESv2.so` showing `U dlsym@GLIBC_2.2.5`
and a litany of `glXGetProcAddress`-style entries.

### Other dead ends tried (all attested in `/data3/p2-poc/*.log`)

1. **Snap chromium** (`/snap/bin/chromium`): snap-confine's wrapper
   strips `LD_PRELOAD` from the env before re-execing the chrome
   binary. Even copying the shim to `/tmp` (which the snap apparmor
   profile allows reading) didn't help — the env is gone. The shim
   loads into `chromium` (the snap launcher script) but never into
   the actual chrome process.

2. **Running the chrome binary directly out of the snap squashfs**:
   fails with `version GLIBC_2.38 not found` because the snap bundles
   its own newer glibc. Not workable without snap-confine's pivot-root.

3. **`--disable-features=Vulkan` / `--use-vulkan=disabled`**: doesn't
   skip the `gpu_init.cc` Vulkan probe — `vkCreateInstance() failed:
   -7` still appears in the log and still trips the WebGL blocklist.

4. **`--no-zygote`**: removes the GPU process entirely (everything
   collapses into the browser process), so the question becomes moot —
   no rendering happens.

5. **`--test-type`**: causes chromium to dump histograms and exit
   before three.js has time to run.

6. **`chrome-headless-shell` (Playwright's purpose-built headless
   binary)**: same ANGLE bypass; observed three.js logs WebGL context
   loss / restore, observed `WebGL2 blocklisted` / `WebGL1
   blocklisted` errors, no swap calls.

## Frame count evidence (paste actual numbers)

```
=== Engine 18084 fresh, 0 frames ===
$ curl -s http://127.0.0.1:18084/api/v1/frames | jq
{"frames":[],"count":0}

=== After chromium-headless --use-angle=gl + three.js for 12s ===
$ curl -s http://127.0.0.1:18084/api/v1/frames | jq
{"frames":[],"count":0}

=== Same shim, same engine, same socket: a known-good GL eval bin ===
$ LD_PRELOAD=$SHIM GPA_SOCKET_PATH=/tmp/gpa_p2.sock GPA_SHM_NAME=/gpa_p2 \
    bazel-bin/tests/eval/r15_godot_mobile_renderer_macos_transparent_flicker
... runs, glXSwapBuffers fires ...
$ curl -s http://127.0.0.1:18084/api/v1/frames | jq .count
1                # captured. Path 2 is uniquely broken.
```

The shim, engine, socket, and shm are all healthy. The chromium-side
ANGLE dispatch is the lone broken link.

## Estimated next steps to load a real R13 scenario

The Path 2 chromium harness is essentially complete from the launcher
side — `scripts/p2_chromium_capture.sh` parametrizes HTML path and
engine port, and would point at a buggy three.js commit's example
HTML out-of-the-box. What it cannot do, given the ANGLE bypass:
**capture frames**.

To unblock for R13 (r1, r3, r6, r13), three concrete options ranked by
effort:

1. **(recommended) Use Path 3 (`gpa_emit_frame`) with a Node + headless-gl
   + three.js harness.** The shim already exports `gpa_emit_frame`
   (verified via `nm -D libgpa_gl.so | grep gpa_emit_frame`). Wire a
   small N-API binding that calls it from JS between three.js
   `renderer.render()` calls, then port each R13 scenario's example
   HTML to a Node ESM module that drives three.js against a
   headless-gl context. ~1 day of work, unblocks r1/r3/r6 immediately.
   r13 (autoClear + WebGPURenderer) stays blocked until WebGPU support
   is added — out of scope for this approach.

2. **Add `eglSwapBuffers` interception to the shim.** Even though
   chromium ANGLE bypasses the dynamic linker for GL functions, **EGL**
   functions are called via the normal symbol search (since EGL is
   chromium's "outer API" — chromium itself loads `libEGL.so` and
   imports `eglSwapBuffers` directly). Worth testing as a 30-minute
   experiment: add `eglSwapBuffers` wrapper to `gl_wrappers.c` (mirroring
   the `glXSwapBuffers` block), rebuild, re-run the harness in this
   doc. **If chromium calls `eglSwapBuffers` through the normal symbol
   table** (untested), this single change unlocks Path 2. If ANGLE also
   does direct dlsym for EGL, this won't help.

3. **Wrap libGL itself instead of using LD_PRELOAD.** Build a
   replacement `libGL.so` that re-exports the system libGL plus our
   shim's wrappers, drop it on chromium's library search path. Defeats
   ANGLE's dlopen by giving its `dlopen("libGL.so")` a wrapped library.
   Significant build/packaging surgery — not worth it for an eval-only
   capability.

## Artifacts

- `scripts/p2_chromium_capture.sh` — runnable harness with the verified
  flag set, parameterised by HTML path and engine port.
- `tests/p2-poc/index.html` — minimal one-static-triangle three.js page
  used for this investigation.
- `/data3/p2-poc/*.log` — chromium console captures, probe dumps, and
  engine logs. Not committed (large, host-specific, ephemeral).

## 2026-04-30 follow-up: eglSwapBuffers wrapper added; chromium still blocked

Added `eglSwapBuffers` interception to the shim (`src/shims/gl/gl_wrappers.c`)
on the hypothesis that chromium might call `eglSwapBuffers` via the normal
dynamic-link path. It doesn't. Re-running the harness after the change:
`frames_before = 0`, `frames_after = 0`. Same as before.

Why: the GPU process maps show chromium loads its own **bundled** EGL stack
from `chrome-linux64/libEGL.so` and `chrome-linux64/libGLESv2.so` (ANGLE),
not the system `/usr/lib/x86_64-linux-gnu/libEGL.so.1`. Chromium's GPU code
calls `eglSwapBuffers` against the bundled libEGL handle it dlopened —
bypassing global symbol resolution exactly like the desktop GL calls.

GPU process maps (filtered) at the moment of attempted capture:
```
/home/jingyulee/.cache/ms-playwright/chromium-1208/chrome-linux64/libEGL.so
/home/jingyulee/.cache/ms-playwright/chromium-1208/chrome-linux64/libGLESv2.so
/tmp/libgpa_gl_p2.so
/usr/lib/x86_64-linux-gnu/libGL.so.1.7.0
/usr/lib/x86_64-linux-gnu/libGLX_mesa.so.0.0.0
/usr/lib/x86_64-linux-gnu/libGLX.so.0.0.0
```

The system `libGL.so.1.7.0` is loaded (so ANGLE's desktop-GL backend can
dlopen it for actual rasterization), but chromium itself never makes
direct GL calls into the global symbol space.

The eglSwapBuffers wrapper is preserved because it's a free win for any
pure-EGL app (Wayland compositors, embedded EGL stacks, headless pbuffer
demos that link libEGL via DT_NEEDED rather than dlopen). It just doesn't
help chromium.

**Verdict update: chromium capture is fundamentally blocked at the
OpenGPA-shim layer.** Reaching real chromium GL calls requires either:

- Building chromium with a non-bundled, non-ANGLE GL backend (not a
  supported chromium build configuration on Linux as of 2026).
- Patching ANGLE itself to route through global symbols (vendored ANGLE,
  large change, has to be re-done each chromium update).
- A different capture stratum: hook ANGLE's swap path *inside* chromium
  via a chromium-specific instrumentation (e.g. an extension or a custom
  build with capture hooks). Not LD_PRELOAD scope.

For the three.js eval cluster, **stick with Path 1 (Node + headless-gl +
gpa_emit_frame)** for what it can capture, and accept that per-draw GL
state from headless-gl is similarly invisible (same ANGLE bypass).
