# OpenGPA — Open Graphics Profiler for Agents

A live graphics debugger designed for AI agents. Intercepts OpenGL/Vulkan/WebGL
calls, captures frame state, and exposes it via REST API and MCP tools so LLMs
can inspect, understand, and debug 3D rendered output.

---

## Quick Start

```bash
# Build C++ core and Python bindings
bazel build //...

# Install Python dependencies
pip install -e ".[dev]"

# Start OpenGPA engine (native capture mode)
python -m gla.launcher --port 18080
# Prints:
#   GLA_SOCKET_PATH=/tmp/gla.sock
#   GLA_SHM_NAME=/gla_capture
#   GLA_AUTH_TOKEN=<token>

# Run your OpenGL app with capture
LD_PRELOAD=bazel-bin/src/shims/gl/libgla_gl.so \
    GLA_SOCKET_PATH=/tmp/gla.sock \
    GLA_SHM_NAME=/gla_capture \
    GLA_AUTH_TOKEN=<token> \
    ./your_gl_app

# Query via REST
export TOKEN=<token>
curl -H "Authorization: Bearer $TOKEN" \
    http://localhost:18080/api/v1/frames/current/overview
```

To load a RenderDoc capture file instead of live capture:

```bash
python -m gla.launcher --backend renderdoc --capture-file trace.rdc --port 18080
```

---

## Architecture

```
+---------------------------------------------+
|            Target Application               |
|                                             |
|  GL Shim        VK Layer      WebGL Shim    |
|  (C,LD_PRELOAD) (C,implicit)  (TS,extension)|
+----+----------------+---------------+-------+
     | shm+socket     | shm+socket    | websocket
     v                v               v
+---------------------------------------------+
|          OpenGPA Core Engine (C++)          |
|                                             |
|  Capture       State Store    Semantic      |
|  Ingestion     (ring buffer,  Reconstructor |
|  (FlatBuffers  60-frame)      (matrix cls,  |
|   + raw bin)                  camera, AABB) |
|                                             |
|  Query Engine (filter, spatial, pixel)      |
+---------------------+-----------------------+
                      | pybind11
                      v
+---------------------------------------------+
|         OpenGPA Python Interface            |
|                                             |
|  REST API (FastAPI)    MCP Server (stdio)   |
+---------------------------------------------+
```

**Shim Layer** — Intercepts API calls inside the target process. Writes bulk data
(vertex buffers, textures, framebuffer pixels) into a shared memory ring buffer.
Sends FlatBuffers-encoded frame metadata over a Unix socket. Never crashes the host.

**Core Engine** — C++ process. Receives captures, stores per-frame snapshots in a
ring buffer (default: last 60 frames). Computes normalized representation and
semantic reconstruction on demand, then caches results.

**Python Interface** — FastAPI REST server and stdio MCP server, both backed by
pybind11 bindings to the C++ query engine.

---

## Capture Backends

| Backend | Use case | How to activate |
|---------|----------|-----------------|
| **Native** (default) | Live capture from a running GL/VK/WebGL app | `--backend native` (default) |
| **RenderDoc** | Offline analysis of `.rdc` capture files | `--backend renderdoc --capture-file trace.rdc` |

The native backend supports:
- **OpenGL 3.3+** via `LD_PRELOAD` shim (`libgla_gl.so`)
- **Vulkan 1.0+** via implicit layer (`VK_LAYER_GLA_capture`)
- **WebGL 1.0/2.0** via Chromium browser extension + Node.js bridge

The RenderDoc backend provides full-fidelity offline analysis when live capture
is not practical.

---

## API Reference

### REST Endpoints

All endpoints require `Authorization: Bearer <token>`. The API binds to
`127.0.0.1` only.

```
# Frame
GET  /api/v1/frames/current/overview
GET  /api/v1/frames/{frame_id}/overview
GET  /api/v1/frames/{frame_id}/framebuffer          # color as PNG
GET  /api/v1/frames/{frame_id}/framebuffer/depth    # depth as PNG
GET  /api/v1/frames/{frame_id}/drawcalls            # ?limit=50&offset=0

# Draw call
GET  /api/v1/frames/{frame_id}/drawcalls/{dc_id}
GET  /api/v1/frames/{frame_id}/drawcalls/{dc_id}/shader
GET  /api/v1/frames/{frame_id}/drawcalls/{dc_id}/textures
GET  /api/v1/frames/{frame_id}/drawcalls/{dc_id}/vertices

# Pixel
GET  /api/v1/frames/{frame_id}/pixel/{x}/{y}            # color + depth
GET  /api/v1/frames/{frame_id}/pixel/{x}/{y}/history    # draw call chain

# Scene (semantic)
GET  /api/v1/frames/{frame_id}/scene
GET  /api/v1/frames/{frame_id}/scene/camera
GET  /api/v1/frames/{frame_id}/scene/objects
GET  /api/v1/frames/{frame_id}/scene/objects/{obj_id}
GET  /api/v1/frames/{frame_id}/scene/query?type=radius&origin=0,0,0&radius=10
GET  /api/v1/frames/{frame_id}/scene/query?type=ray&origin=0,0,0&direction=0,0,-1

# Frame comparison
GET  /api/v1/diff/{frame_a}/{frame_b}?depth=summary|drawcalls|pixels

# Control
POST /api/v1/control/pause
POST /api/v1/control/resume
POST /api/v1/control/step?count=N
GET  /api/v1/control/status
```

Full response schema and examples: [`docs/superpowers/specs/2026-04-16-gla-design.md`](docs/superpowers/specs/2026-04-16-gla-design.md), Section 3.6.

### MCP Tools

Six tools optimized for LLM interaction:

| Tool | Description |
|------|-------------|
| `query_frame(frame_id, view, limit, offset)` | Frame overview, draw call list, or framebuffer. `view`: `overview` \| `drawcalls` \| `framebuffer`. Use `"latest"` for `frame_id`. |
| `inspect_drawcall(frame_id, dc_id, aspect)` | Draw call detail. `aspect`: `detail` \| `shader` \| `textures` \| `vertices`. |
| `query_pixel(frame_id, x, y)` | RGBA color and depth at pixel `(x, y)`. |
| `query_scene(frame_id, aspect)` | Semantic scene info. `aspect`: `scene` \| `camera` \| `objects`. |
| `compare_frames(frame_id_a, frame_id_b, depth)` | Frame diff. `depth`: `summary` \| `drawcalls` \| `pixels`. |
| `control_capture(action, count)` | `pause` \| `resume` \| `step` \| `status`. |

---

## MCP Integration (Claude Code)

Add to your project's `.mcp.json` to use OpenGPA tools directly from Claude Code.
Start OpenGPA first, then note the printed `GLA_AUTH_TOKEN`.

```json
{
  "mcpServers": {
    "gla": {
      "command": "python",
      "args": ["-m", "gla.mcp.server"],
      "env": {
        "GLA_BASE_URL": "http://127.0.0.1:18080/api/v1",
        "GLA_TOKEN": "<paste GLA_AUTH_TOKEN here>"
      }
    }
  }
}
```

The MCP server uses stdio transport and makes no outbound network connections.

---

## Eval Suite

OpenGPA ships with an adversarial evaluation suite of intentionally broken OpenGL
scenes. Each scenario is designed so that code inspection alone scales poorly
while 1-3 OpenGPA queries expose the root cause directly.

**10 adversarial scenarios (Category E):**

| ID | Bug | Principle |
|----|-----|-----------|
| E1 | GL state leak between draw calls (missing `glBindTexture`) | Absent code |
| E2 | NaN from singular normal matrix via zero-scale axis | Distant cause, subtle numerics |
| E3 | Index buffer truncation (`sizeof` vs `.size() * sizeof`) | Looks correct, partial success |
| E4 | Double-negation cull bug (negative scale + wrong winding cancel) | Compensating errors |
| E5 | Stale uniform cache after enum reorder | Stale state, distant cause |
| E6 | Depth buffer precision destroyed by near/far ratio 10^8 | Subtle numerics |
| E7 | Shadowed `saturate()` from conflicting shader includes | Partial success |
| E8 | Race condition on async texture upload (missing mutex) | Non-deterministic |
| E9 | UI scissor rect not reset before 3D pass | Absent code, stale state |
| E10 | Compensating wrong handedness + wrong NDC range | Compensating errors |

Scenario sources live in `tests/eval/`. Each includes a minimal GL application
with the bug, expected output, ground-truth diagnosis, and a difficulty rating.

**Run the eval harness:**

```bash
# Run all Category E scenarios
python -m gla.eval.cli run --category E

# Run a single scenario
python -m gla.eval.cli run --scenario e1_state_leak

# Print metrics (token cost, tool calls, accuracy — with vs. without OpenGPA)
python -m gla.eval.cli report
```

See the full scenario descriptions and token-efficiency analysis in
[`docs/superpowers/specs/2026-04-16-gla-design.md`](docs/superpowers/specs/2026-04-16-gla-design.md), Section 9.

---

## Building

**Requirements:** Bazel 7+, Python 3.11+, GCC/Clang with C++17, Vulkan SDK
(for Vulkan layer), Node.js + pnpm (for WebGL shim).

```bash
# Build everything
bazel build //...

# Build only the OpenGL shim
bazel build //src/shims/gl:libgla_gl

# Build only the C++ core
bazel build //src/core:gla_engine

# Build Python bindings
bazel build //src/bindings:_gla_core
```

**C++ dependencies** (fetched by Bazel via bzlmod):

| Dependency | Purpose |
|------------|---------|
| FlatBuffers | Zero-copy metadata serialization |
| GLM | Math (matrices, vectors) |
| GoogleTest | C++ unit tests |
| pybind11 | Python bindings |

**Python dependencies** (via pip):

```bash
pip install -e .          # runtime only
pip install -e ".[dev]"   # + pytest, httpx
```

**TypeScript components** (WebGL shim + Node.js bridge):

```bash
pnpm install
pnpm build
```

---

## Testing

**C++ unit tests:**

```bash
bazel test //tests/unit/core/...
bazel test //tests/unit/shims/...
```

**Python tests:**

```bash
pytest tests/unit/python/
```

Test coverage includes: frame store, IPC (control socket, shm ring buffer),
query engine, frame diff, matrix classifier, camera extractor, object grouper,
normalizer, all REST API route groups, backends, and eval harness scaffolding.

**Integration tests** (requires a built GL app):

```bash
bazel test //tests/integration/...
```

---

## Project Status

### Core Pipeline

| Milestone | Description | Status |
|-----------|-------------|--------|
| M1 | OpenGL shim (LD_PRELOAD, shadow state, frame capture, shared memory IPC) | Done |
| M2 | Query engine + REST API (normalizer, 22+ endpoints, pybind11, FastAPI) | Done |
| M3 | Semantic reconstruction | Removed (replaced by Tier 3 metadata — no heuristics) |
| M4 | MCP server (10 tools over stdio JSON-RPC) | Done |
| M5 | Vulkan implicit layer (dispatch table chaining, VK_LAYER_GLA_capture) | Done (scaffolded, not E2E tested) |
| M6 | WebGL browser extension + Node.js bridge | Done (scaffolded, not E2E tested) |
| M7 | Frame comparison (draw call + pixel diff at 3 depth levels) | Done |

### Framework Integration

| Feature | Description | Status |
|---------|-------------|--------|
| Debug markers | Intercept glPushDebugGroup/glPopDebugGroup, build tree | Done |
| Metadata sidecar | POST /frames/{id}/metadata for framework scene graph | Done |
| Correlation engine | Join GL capture + markers + metadata via draw call IDs | Done |
| Framework queries | query_object, explain_pixel, list_render_passes, query_material | Done |
| Three.js plugin | Scene graph capture + HTTP POST (~120 LOC) | Done |
| RenderDoc backend | Read .rdc capture files via replay API | Done |

### Eval Suite

| Feature | Description | Status |
|---------|-------------|--------|
| Synthetic scenarios | 10 adversarial GL apps (e1-e10) | Done |
| Real-world scenarios | 8+ from Three.js/Godot GitHub issues (r-prefix) | Done |
| Mined state bugs | 4 from real projects (s-prefix: texture cache, blend, depth, FBO) | Done |
| Multi-model eval runner | Cross-model comparison (Haiku/Sonnet/Opus) | Done |
| Hint-stripped code | No BUG/should-be comments in source | Done |

### Known Limitations

| Issue | Impact | Priority |
|-------|--------|----------|
| Vec3 uniform serialization | Multi-component uniforms need verification | P0 (fix in progress) |
| Pixel attribution (draw call ID buffer) | explain_pixel can't map pixel → draw call | P1 |
| glClear not intercepted | Can't detect missing clears (r31 scenario) | P2 |
| FBO attachment tracking | Can't detect feedback loops (r5 scenario) | P3 |
| Engine launcher shutdown crash | terminate called on process exit | P3 |

### Out of Scope (v1)

Windows/macOS support, DirectX interception, compute shaders, shader hot-reload,
continuous trace recording, GPU performance profiling.

---

## License

MIT License. See [LICENSE](LICENSE).
