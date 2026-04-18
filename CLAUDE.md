# GLA — Project Instructions

## What This Is

GLA (Graphics Library for Agents) — a live graphics debugger for AI agents. Intercepts GL/Vulkan calls, captures frame state, exposes via REST API + MCP tools.

## Build & Test

```bash
bazel build //...                                          # build everything
bazel test //tests/core/... //tests/shims/...              # C++ tests
PYTHONPATH=src/python python -m pytest tests/python/ -q    # Python tests
```

Python 3.11 (Bazel-managed) is required for the pybind11 module. System Python 3.10 works for pytest only.

## Architecture (Three Tiers)

- **Tier 1**: Raw GL capture via LD_PRELOAD shim. No heuristics — exposes raw facts only.
- **Tier 2**: Debug markers (glPushDebugGroup). Free if framework emits them.
- **Tier 3**: Framework metadata sidecar. Plugins POST scene graph JSON to REST API.

See `docs/framework-tiers.md` for full capability matrix.

## Key Design Principles

- **No heuristics in Tier 1.** Never guess which uniform is "the view matrix." Expose raw data, let the querying agent interpret.
- **FrameProvider ABC** (`src/python/gla/backends/base.py`) is the interface between capture backends and the query layer. All REST routes use this interface.
- **safe_json_response()** — all routes must return this (not raw dicts) to handle bytes from pybind11.
- **Lazy IPC init** — the shim connects to the engine at the first `glXSwapBuffers`, not at constructor time. This avoids fork issues from X11/DRI.

## Running the Eval

```bash
# 1. Start Xvfb (if headless)
Xvfb :99 -screen 0 800x600x24 &
export DISPLAY=:99

# 2. Build
bazel build //...

# 3. Start engine (use Python 3.11)
PY311="path/to/bazel/python3.11"
PYTHONPATH="src/python:bazel-bin/src/bindings" $PY311 -m gla.launcher \
    --socket /tmp/gla.sock --shm /gla --port 18080 --token TOKEN

# 4. Capture a scenario
LD_PRELOAD=bazel-bin/src/shims/gl/libgla_gl.so \
    GLA_SOCKET_PATH=/tmp/gla.sock GLA_SHM_NAME=/gla \
    bazel-bin/tests/eval/SCENARIO_NAME

# 5. Query
curl -H "Authorization: Bearer TOKEN" localhost:18080/api/v1/frames/current/overview
```

## Eval-Driven Development Loop

1. **Mine** — Find real-world graphics bugs from GitHub issues
2. **Evaluate** — Run with/without GLA, compare accuracy and tool usage
3. **Improve** — Fix capture bugs or add new capabilities based on eval gaps

Eval scenarios live in `tests/eval/`. Each has a `.c` file (GL app) and `.md` file (description). Source files must NOT contain hint comments (// BUG, // should be, etc.)

## Adding a New GL Function to Intercept

1. `src/shims/gl/gl_wrappers.h` — add function pointer to `GlaRealGlFuncs`
2. `src/shims/gl/gl_wrappers.c` — add dlsym in `gla_wrappers_init()`, add wrapper function, add to `gla_resolve_wrapper()`
3. `src/shims/gl/shadow_state.h/c` — add state tracking if needed
4. `src/shims/gl/frame_capture.c` — add to `GlaDrawCallSnapshot` if serialized per draw call
5. `src/core/engine.cpp` — add deserialization in `ingest_frame()`
6. `src/core/normalize/normalized_types.h` — add to `NormalizedDrawCall`
7. `src/bindings/py_gla.cpp` — expose to Python

## Adding a New Capture Backend

Implement `FrameProvider` from `src/python/gla/backends/base.py`:
- `get_frame_overview()`, `get_latest_overview()`
- `list_draw_calls()`, `get_draw_call()`
- `get_pixel()`
- `compare_frames()`
- Optional: `pause()`, `resume()`, `step()`, `status()`

See `native.py` and `renderdoc.py` for examples.

## Adding a New REST Endpoint

1. Create `src/python/gla/api/routes_NAME.py`
2. Use `safe_json_response()` for ALL returns (prevents pydantic bytes crash)
3. Register in `src/python/gla/api/app.py`
4. Add tests in `tests/python/test_api_NAME.py`

## Known Issues

- Engine launcher crashes on process exit (`terminate called without an active exception`) — the C++ engine thread's destructor fires during Python shutdown. Use `engine.stop()` before exit.
- Control socket tests use native endian for FrameReadyPayload (not network byte order).
- `r36_opengl_proximity_fade` scenario may need additional GL functions intercepted.

## File Locations

| What | Where |
|------|-------|
| GL shim (C) | `src/shims/gl/` |
| Vulkan layer (C) | `src/shims/vk/` |
| WebGL extension (JS) | `src/shims/webgl/` |
| Core engine (C++) | `src/core/` |
| Python bindings | `src/bindings/py_gla.cpp` |
| REST API | `src/python/gla/api/` |
| MCP server | `src/python/gla/mcp/` |
| Framework integration | `src/python/gla/framework/` |
| Capture backends | `src/python/gla/backends/` |
| Eval harness | `src/python/gla/eval/` |
| Eval scenarios | `tests/eval/` |
| Design specs | `docs/superpowers/specs/` |
| Plans | `docs/superpowers/plans/` |
