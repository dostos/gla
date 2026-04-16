# GLA: Graphics Library for Agents — Design Specification

## 1. Overview

GLA is a live graphics debugger designed for AI agents. It intercepts graphics API calls from a running application, captures per-frame state, and exposes it through a queryable interface so that LLMs and automated tools can inspect, understand, and debug 3D rendered output.

**Name**: GLA (Graphics Library for Agents)
**Repository**: git@github.com:dostos/gla.git

## 2. Requirements

### 2.1 Functional Requirements

**FR-1: Graphics API Interception**
- FR-1.1: Intercept OpenGL (3.3+ core and compatibility) calls on Linux via `LD_PRELOAD`.
- FR-1.2: Intercept Vulkan (1.0+) calls on Linux via the implicit layer mechanism.
- FR-1.3: Intercept WebGL (1.0 and 2.0) calls in Chromium-based browsers via a browser extension.
- FR-1.4: Interception must be transparent — the target application runs unmodified.

**FR-2: Frame Capture**
- FR-2.1: Capture the complete set of draw calls per frame, including all associated state.
- FR-2.2: For each draw call, capture: vertex/index data, shader program, shader parameters (uniforms/push constants/descriptors), bound textures, and pipeline state (viewport, scissor, depth, blend, cull).
- FR-2.3: Capture framebuffer contents (color, depth, stencil) at frame boundaries.
- FR-2.4: Store raw API-level data as the source of truth. Compute normalized representations on demand.

**FR-3: Live Debugging**
- FR-3.1: Attach to a running application without restarting it (via LD_PRELOAD at launch or Vulkan layer injection).
- FR-3.2: Pause the target application at frame boundaries (after swap/present).
- FR-3.3: Resume the application or step forward by N frames on command.
- FR-3.4: While paused, allow unlimited queries against the captured frame state.

**FR-4: Query Interface**
- FR-4.1: Expose a REST API for querying frame state, draw calls, pixel data, and scene information.
- FR-4.2: Expose an MCP server that wraps the REST API for direct use by LLM agents.
- FR-4.3: Support frame-level queries: overview, draw call listing, framebuffer retrieval.
- FR-4.4: Support draw-call-level queries: shader parameters, vertex data, textures, pipeline state.
- FR-4.5: Support pixel-level queries: color/depth at coordinates, draw call attribution per pixel.
- FR-4.6: Support scene-level queries: visible objects with transforms, camera parameters, spatial queries (radius, ray cast).
- FR-4.7: Support frame comparison: diff draw calls, state, and pixel output between two frames.

**FR-5: Semantic Reconstruction**
- FR-5.1: Auto-detect matrix semantics (model, view, projection) from shader parameter names and structural analysis.
- FR-5.2: Extract camera parameters (position, orientation, FOV, near/far) from view and projection matrices.
- FR-5.3: Group draw calls into logical objects based on shared model matrix and vertex buffer coherence.
- FR-5.4: Compute bounding boxes (AABB) for objects from vertex data and transforms.
- FR-5.5: Attempt light and material detection via naming heuristics on shader parameters and textures.
- FR-5.6: Report confidence levels for all reconstructed semantics. Mark ambiguous or undetectable information explicitly rather than guessing.

### 2.2 Non-Functional Requirements

**NFR-1: Performance**
- NFR-1.1: Interception overhead must be < 5% of frame time during normal (non-capture) execution.
- NFR-1.2: Frame capture (full state snapshot + framebuffer readback) must complete in < 100ms for a typical frame (< 1000 draw calls, < 50MB total state).
- NFR-1.3: Query response time must be < 200ms for metadata queries and < 1s for queries involving large data (vertex buffers, textures).

**NFR-2: Reliability**
- NFR-2.1: The shim must never crash the target application. Capture failures must be silently skipped or reported via the control channel.
- NFR-2.2: The system must handle applications that use multiple GL contexts or Vulkan devices.
- NFR-2.3: The system must tolerate partial captures (e.g., if a texture readback fails, the rest of the frame data is still usable).

**NFR-3: Extensibility**
- NFR-3.1: Adding support for a new graphics API (e.g., DirectX via Wine/Proton, Metal via MoltenVK) must not require changes to the core engine, query layer, or MCP server — only a new shim.
- NFR-3.2: Adding new query types must not require changes to the shim or IPC layer.
- NFR-3.3: The normalized data model must be API-agnostic. No API-specific concepts may leak into the query interface.

**NFR-4: Compatibility**
- NFR-4.1: Linux x86_64 as the primary platform.
- NFR-4.2: OpenGL 3.3+ (core and compatibility profile), OpenGL ES 2.0/3.0.
- NFR-4.3: Vulkan 1.0+ with common extensions (KHR_swapchain, etc.).
- NFR-4.4: WebGL 1.0 and 2.0 in Chromium-based browsers.

### 2.3 Out of Scope (v1)

- Windows/macOS support (future — requires DLL injection, Metal layer).
- DirectX interception (future — via Wine/Proton or Windows port).
- Compute shader interception and debugging.
- Shader source editing / hot-reload.
- Continuous recording / trace file export (v1 is live-only).
- GPU performance profiling (timing, bandwidth counters).

## 3. Architecture

### 3.1 High-Level Architecture

```
+--------------------------------------------------------------+
|                     Target Application                        |
|                                                               |
|  +-------------+  +---------------+  +---------+--------+    |
|  | GL Shim     |  | VK Layer      |  | WebGL Shim       |    |
|  | (C, LD_     |  | (C, implicit  |  | (JS/TS, browser  |    |
|  | PRELOAD,    |  |  VK_LAYER,    |  |  extension,      |    |
|  | shadow      |  |  dispatch     |  |  prototype       |    |
|  | state)      |  |  table chain) |  |  monkey-patch)   |    |
|  +------+------+  +-------+-------+  +--------+---------+    |
+---------|-----------------|--------------------|---------------+
          | shm + socket    | shm + socket       | websocket
          v                 v                    v
+--------------------------------------------------------------+
|                  GLA Core Engine (C++)                         |
|                                                               |
|  +----------------+  +-----------------+  +----------------+  |
|  | Capture        |  | State Store     |  | Semantic       |  |
|  | Ingestion      |  | (ring buffer,   |  | Reconstructor  |  |
|  | (FlatBuffers   |  |  per-frame      |  | (matrix class, |  |
|  |  metadata,     |  |  snapshots)     |  |  camera, obj   |  |
|  |  raw binary    |  |                 |  |  grouping,     |  |
|  |  bulk data)    |  |                 |  |  AABB)         |  |
|  +----------------+  +-----------------+  +----------------+  |
|                                                               |
|  +--------------------------------------------------------+   |
|  | Query Engine (spatial queries, filtering, pixel trace)  |   |
|  +--------------------------------------------------------+   |
+--------------------------+------------------------------------+
                           | pybind11
                           v
+--------------------------------------------------------------+
|                  GLA Python Interface                          |
|                                                               |
|  +-----------------------+  +------------------------------+  |
|  | REST API (FastAPI)    |  | MCP Server (thin wrapper)    |  |
|  +-----------------------+  +------------------------------+  |
+--------------------------------------------------------------+
```

### 3.2 Component Responsibilities

**Shim Layer** — Per-API interception running inside the target process.
- Intercepts API calls, maintains shadow state (GL) or records metadata (VK).
- At frame boundaries (swap/present), snapshots state and bulk data into shared memory.
- Signals the core engine via Unix socket. Optionally blocks (pauses the app) until the engine signals resume.
- Must be minimal and safe — never crash the host app.

**Core Engine** — C++ process that owns all captured data and query logic.
- Receives captures from shims via shared memory (bulk data) and Unix sockets (metadata/control).
- Metadata arrives as FlatBuffers; bulk data (vertex buffers, textures, framebuffer pixels) as raw binary referenced by offset/size.
- Stores per-frame snapshots in a ring buffer (configurable depth, default: last 60 frames).
- Computes normalized representation and semantic reconstruction on demand (deferred), then caches results.
- Implements the query engine: draw call filtering, pixel attribution, spatial queries, frame diffing.

**Python Interface** — Thin layer exposing the engine's capabilities over HTTP and MCP.
- REST API via FastAPI, wrapping the C++ query engine through pybind11 bindings.
- MCP server as a thin adapter over the REST API.
- Handles serialization (JSON for metadata, base64 PNG for images), pagination, and response formatting.
- Responsible for "LLM-friendly" response formatting: semantic summaries alongside raw data.

### 3.3 IPC Design

**Native shims (OpenGL, Vulkan) to Core Engine:**

```
Shared Memory (POSIX shm, ~256MB ring buffer):
  - Pre-allocated at shim initialization.
  - Shim writes bulk data (vertex buffers, textures, framebuffer pixels)
    as raw binary at current write offset.
  - POSIX semaphore per ring buffer for synchronization.

Unix Domain Socket (control channel):
  - Shim sends FlatBuffer-encoded frame metadata:
    {frame_id, draw_call_count, resource_table_offsets, ...}
  - Engine sends control commands:
    {pause, resume, step_n_frames, capture_settings}
  - Lightweight, low-latency for signaling.
```

**WebGL shim to Core Engine:**

```
WebSocket (browser) -> Node.js Bridge -> Unix Domain Socket -> Core Engine

  - Browser extension opens WebSocket to local Node.js relay process.
  - Relay translates WebSocket frames to Unix socket messages.
  - Frame metadata as JSON (converted to FlatBuffers by the relay).
  - Bulk data (readPixels output) as binary WebSocket frames.
```

### 3.4 Data Model

#### 3.4.1 Raw Capture (Source of Truth)

Stored per-frame, per-API format. This is what the shim actually records:

```
RawFrameCapture {
    frame_id:     uint64
    timestamp:    float64
    api:          enum { OpenGL, Vulkan, WebGL }
    api_calls:    [RawApiCall]       // ordered sequence of intercepted calls
    bulk_data:    SharedMemoryRegion  // vertex buffers, textures, framebuffer
}
```

#### 3.4.2 Normalized Representation (Computed on Demand)

Derived from raw capture, modeled after WebGPU semantics:

```
NormalizedFrame {
    frame_id:     uint64
    timestamp:    float64

    render_passes: [RenderPass {
        target:       FramebufferRef
        clear_values: [ClearValue]
        draw_calls:   [DrawCall]
    }]

    resources: {
        buffers:      { id -> BufferData }
        textures:     { id -> TextureData }
        shaders:      { id -> ShaderProgram }
        framebuffers: { id -> FramebufferData }
    }

    framebuffer_snapshots: {
        color:   ImageData (RGBA)
        depth:   ImageData (float32)
        stencil: ImageData (uint8)
    }
}

DrawCall {
    id:              uint32
    primitive_type:  enum { triangles, lines, points, ... }
    vertex_count:    uint32
    index_count:     uint32
    instance_count:  uint32

    vertex_data: {
        buffers:     [{ ref, offset, stride }]
        attributes:  [{ location, format, offset, semantic }]
        index_buffer: { ref, offset, type }
    }

    shader:       ShaderRef
    parameters:   { name -> ShaderParameter }
    textures:     { slot -> TextureRef }

    pipeline_state: {
        viewport, scissor,
        depth_test, depth_write, depth_func,
        blend_enabled, blend_src, blend_dst,
        cull_mode, front_face
    }
}

ShaderParameter {
    type:     enum { float, vec2, vec3, vec4, mat3, mat4, int, ... }
    value:    bytes
    semantic: enum { model_matrix, view_matrix, proj_matrix,
                     mvp_matrix, normal_matrix, color,
                     light_position, unknown }
    confidence: float  // 0.0-1.0 for auto-detected semantics
}
```

#### 3.4.3 Semantic Scene (Derived from Normalized)

```
SceneInfo {
    camera: {
        position:    vec3
        forward:     vec3
        up:          vec3
        fov_y:       float (degrees)
        aspect:      float
        near:        float
        far:         float
        type:        enum { perspective, orthographic }
    }

    objects: [SceneObject {
        id:              uint32
        draw_call_ids:   [uint32]
        world_transform: mat4
        bounding_box:    AABB { min: vec3, max: vec3 }
        visible:         bool (frustum test)
        material_hint: {
            base_color:  vec4 (if detected)
            textures:    [{ type, ref }]
        }
        confidence:      float
    }]

    lights: [LightInfo {
        type:       enum { point, directional, spot, unknown }
        position:   vec3
        direction:  vec3
        color:      vec3
        intensity:  float
        confidence: float
    }]
}
```

### 3.5 Interception Layer Details

#### 3.5.1 OpenGL Shim

- **Deployment**: `LD_PRELOAD=libgla_gl.so ./target_app`
- **Function generation**: Auto-generated wrapper stubs from Khronos `gl.xml` registry. Each wrapper calls the real function (via stored original pointer) and records the call.
- **State tracking**: Shadow state — maintain an in-process mirror of the GL state machine. Intercept all state-setting calls (`glBindTexture`, `glUseProgram`, `glUniform*`, `glEnable`, etc.) and update the shadow. At capture time, serialize the shadow, not `glGet*` results.
- **Readback**: PBO (Pixel Buffer Object) double-buffering for async framebuffer and texture readback. `glFenceSync` to avoid GPU stalls.
- **Context handling**: Intercept `glXMakeCurrent`/`eglMakeCurrent` to track per-thread context. Maintain per-context shadow state. Handle shared contexts via `glXCreateContext(..., shareList)`.
- **Frame boundary**: Intercept `glXSwapBuffers`/`eglSwapBuffers`. Snapshot shadow state + issue readbacks. Block on condition variable if server requests pause.

#### 3.5.2 Vulkan Layer

- **Deployment**: Implicit layer registered via JSON manifest in `~/.local/share/vulkan/implicit_layer.d/gla_layer.json`. Activated via `VK_INSTANCE_LAYERS=VK_LAYER_GLA_capture` or always-on.
- **Dispatch chaining**: Implement `vkGetInstanceProcAddr`/`vkGetDeviceProcAddr`. Store next-layer function pointers in a dispatch table.
- **Command buffer recording**: Intercept `vkCmdDraw*`, `vkCmdBindPipeline`, `vkCmdBindDescriptorSets`, `vkCmdBeginRenderPass`, etc. Record metadata in a parallel structure alongside the application's command buffer.
- **Frame boundary**: Intercept `vkQueuePresentKHR`. Call `vkQueueWaitIdle` to ensure GPU completion, then snapshot. Block if pause requested.
- **Async handling**: Command buffers are recorded then submitted later. At `vkQueueSubmit`, associate recorded metadata with the submission. At present time, all metadata for the frame is available.

#### 3.5.3 WebGL Shim

- **Deployment**: Chromium browser extension. Injects content script that monkey-patches `WebGLRenderingContext.prototype` and `WebGL2RenderingContext.prototype` methods.
- **Interception**: Replace each method on the prototype with a wrapper that logs the call and forwards to the original. Covers `drawArrays`, `drawElements`, `uniform*`, `bindTexture`, `bindFramebuffer`, etc.
- **State capture**: Direct `gl.getParameter()` queries (WebGL is synchronous).
- **Readback**: `gl.readPixels()` for framebuffer. Base64-encode for WebSocket transport.
- **Frame boundary**: Hook into `requestAnimationFrame` — detect frame completion and snapshot.
- **Communication**: WebSocket to a local Node.js bridge process, which relays to the core engine via Unix socket.

### 3.6 Query API

#### 3.6.1 REST Endpoints

```
# Frame queries
GET  /api/v1/frames/current                         # latest captured frame
GET  /api/v1/frames/{frame_id}                       # frame metadata
GET  /api/v1/frames/{frame_id}/overview              # summary stats
GET  /api/v1/frames/{frame_id}/framebuffer           # color buffer as PNG
GET  /api/v1/frames/{frame_id}/framebuffer/depth     # depth buffer as PNG
GET  /api/v1/frames/{frame_id}/drawcalls             # paginated draw call list
     ?limit=50&offset=0&shader=...&render_target=...

# Draw call queries
GET  /api/v1/frames/{frame_id}/drawcalls/{dc_id}             # full details
GET  /api/v1/frames/{frame_id}/drawcalls/{dc_id}/vertices    # vertex data
GET  /api/v1/frames/{frame_id}/drawcalls/{dc_id}/textures    # bound textures
GET  /api/v1/frames/{frame_id}/drawcalls/{dc_id}/shader      # shader info + params

# Pixel queries
GET  /api/v1/frames/{frame_id}/pixel/{x}/{y}                 # color + depth
GET  /api/v1/frames/{frame_id}/pixel/{x}/{y}/history         # draw call chain

# Scene queries (semantic)
GET  /api/v1/frames/{frame_id}/scene                         # full scene info
GET  /api/v1/frames/{frame_id}/scene/camera                  # camera params
GET  /api/v1/frames/{frame_id}/scene/objects                 # object list
GET  /api/v1/frames/{frame_id}/scene/objects/{obj_id}        # single object
GET  /api/v1/frames/{frame_id}/scene/query                   # spatial query
     ?type=radius&origin=0,0,0&radius=10
     ?type=ray&origin=0,0,0&direction=0,0,-1

# Frame comparison
GET  /api/v1/diff/{frame_a}/{frame_b}                        # frame diff
     ?depth=summary|drawcalls|pixels

# Control
POST /api/v1/control/pause
POST /api/v1/control/resume
POST /api/v1/control/step                                    # step 1 frame
POST /api/v1/control/step?count=N                            # step N frames
GET  /api/v1/control/status                                  # paused/running, frame count
```

#### 3.6.2 MCP Tools

Six high-level tools optimized for LLM interaction:

```
query_frame(frame_id, query_type, pagination)
  query_type: "overview" | "drawcalls" | "framebuffer"
  Returns: frame summary, paginated draw call list, or base64 PNG

inspect_drawcall(frame_id, drawcall_id, include)
  include: ["shader", "vertices", "textures", "pipeline"]
  Returns: detailed draw call info with semantic summaries

query_pixel(frame_id, x, y)
  Returns: color, depth, stencil at (x,y) + which draw call produced it

query_scene(frame_id, query_type, spatial_params)
  query_type: "objects" | "camera" | "spatial"
  Returns: scene objects with transforms/bounds, camera info, or spatial query results

compare_frames(frame_id_a, frame_id_b, depth)
  depth: "summary" | "drawcalls" | "pixels"
  Returns: what changed between frames

control_capture(action, count)
  action: "pause" | "resume" | "step"
  Returns: current status
```

#### 3.6.3 Response Format

All responses are JSON. Design principle: **semantic summaries by default, raw data available on request.**

Example response for `query_scene(frame_id=42, query_type="camera")`:
```json
{
  "camera": {
    "summary": "Perspective camera at (5.0, 3.0, 2.0) looking toward (-0.7, -0.4, -0.6), FOV 60.0 deg",
    "position": [5.0, 3.0, 2.0],
    "forward": [-0.707, -0.408, -0.577],
    "up": [0.0, 1.0, 0.0],
    "fov_y_degrees": 60.0,
    "aspect_ratio": 1.778,
    "near": 0.1,
    "far": 1000.0,
    "type": "perspective",
    "confidence": 0.95,
    "raw_view_matrix": [[...], [...], [...], [...]],
    "raw_projection_matrix": [[...], [...], [...], [...]]
  }
}
```

Image data (framebuffers, textures) returned as base64-encoded PNG in JSON, or as raw binary via separate download endpoints.

### 3.7 Semantic Reconstruction Pipeline

The reconstructor runs on demand when scene queries are made. Results are cached per frame.

**Stage 1: Matrix Classification**
1. Name matching against known patterns (`model`, `view`, `proj`, `mvp`, `uModel`, `u_view`, etc.).
2. Structural analysis: orthonormal upper-left 3x3 + translation = rigid transform; perspective divide row = projection matrix.
3. Change-rate analysis: matrix that changes per draw call = likely model; constant across frame = likely view/projection.
4. Assign confidence score (0.0-1.0) based on number of heuristics that agree.

**Stage 2: Camera Extraction**
1. Identify view matrix (highest confidence "view" classification).
2. Camera position = inverse(view) * [0,0,0,1]. Forward/up/right from inverse columns.
3. Identify projection matrix. Decompose: FOV from P[1][1], aspect from P[0][0]/P[1][1], near/far from P[2][2] and P[3][2].
4. Detect perspective (P[3][3] ~ 0) vs orthographic (P[3][3] ~ 1).

**Stage 3: Object Grouping**
1. Group sequential draw calls sharing the same model matrix.
2. Merge groups sharing the same vertex buffer.
3. Handle instanced draws as single objects with instance count.
4. Tag multi-pass patterns (same geometry drawn to different render targets).

**Stage 4: Bounding Box Computation**
1. For each object group, read vertex positions from bulk data.
2. For meshes < 100k vertices: full scan to compute AABB.
3. For meshes >= 100k vertices: stratified 10% sample, add 15% margin.
4. Transform AABB to world space using model matrix.

**Stage 5: Light and Material Detection** (best-effort)
1. Scan shader parameters for light-related names and structures.
2. Detect PBR parameters (metallic, roughness) and texture slot assignments.
3. Low confidence — always flagged as heuristic.

## 4. Technology Stack

| Component | Language | Key Dependencies |
|-----------|----------|------------------|
| OpenGL shim | C | gl.xml code gen, POSIX shm/sem |
| Vulkan layer | C | Vulkan SDK headers |
| WebGL shim | TypeScript | Browser Extension API, WebSocket |
| Node.js bridge | TypeScript | ws (WebSocket library) |
| Core engine | C++ (17+) | FlatBuffers, GLM (math), stb_image (PNG) |
| Python bindings | C++/Python | pybind11 or nanobind |
| REST API | Python | FastAPI, uvicorn |
| MCP server | Python | mcp-python-sdk |

## 5. Build System

- CMake for C/C++ components (shims + core engine).
- pybind11/nanobind integrated via CMake for Python bindings.
- npm/pnpm for TypeScript components (WebGL shim + Node.js bridge).
- pip/uv for Python components (REST API + MCP server).

## 6. Project Structure

```
gla/
  src/
    shims/
      gl/             # OpenGL LD_PRELOAD shim (C)
      vk/             # Vulkan implicit layer (C)
      webgl/          # Browser extension (TypeScript)
      bridge/         # Node.js WebSocket-to-Unix relay (TypeScript)
    core/
      capture/        # Capture ingestion, FlatBuffers schemas
      store/          # Ring buffer state store
      normalize/      # Raw -> normalized representation
      semantic/       # Semantic reconstruction pipeline
      query/          # Query engine (filtering, spatial, pixel trace)
    bindings/         # pybind11 wrappers
    python/
      gla/
        api/          # FastAPI REST endpoints
        mcp/          # MCP server
  schemas/            # FlatBuffers schema definitions
  tests/
    shims/            # Per-API shim tests
    core/             # Core engine unit tests
    integration/      # End-to-end tests with sample GL/VK apps
    python/           # API and MCP tests
  docs/
  CMakeLists.txt
  package.json
  pyproject.toml
```

## 7. Milestones (suggested build order)

1. **M1: OpenGL shim + basic capture** — LD_PRELOAD shim that intercepts draw calls, shadows state, writes to shared memory. Minimal core engine that receives and stores one frame.
2. **M2: Query engine + REST API** — Normalized representation, query engine, FastAPI endpoints. Can query draw calls, pixel colors, pipeline state.
3. **M3: Semantic reconstruction** — Matrix classification, camera extraction, object grouping, bounding boxes. Scene query endpoints.
4. **M4: MCP server** — Wrap REST API in MCP tools. Test with Claude Code.
5. **M5: Vulkan layer** — Add Vulkan interception using implicit layer mechanism.
6. **M6: WebGL shim** — Browser extension + Node.js bridge.
7. **M7: Frame comparison + advanced queries** — Frame diffing, pixel archaeology (draw call attribution), spatial queries.

## 8. Key Design Decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Interception approach | Per-API shims | Modular, testable, uses each API's native extension mechanism |
| IPC | Shared memory (bulk) + Unix socket (control) | Avoids serialization overhead for large data; sockets for signaling |
| Serialization | FlatBuffers (metadata) + raw binary (bulk) | Zero-copy access for metadata; no encoding overhead for buffers/textures |
| Normalization timing | Deferred (on query, cached) | Avoids capture-time cost; raw data preserved as source of truth |
| Normalization model | WebGPU-aligned semantics | Battle-tested abstraction designed to map across modern APIs |
| Core engine language | C++ | Performance for large data processing (vertex buffers, textures, framebuffers) |
| Query interface language | Python | FastAPI for rapid iteration; pybind11 bridges to C++ core |
| MCP tool granularity | 6 high-level tools | LLMs work better with fewer, well-documented tools |
| GL state capture | Shadow state | Avoids expensive glGet* calls; captures state without GPU round-trips |
| Semantic confidence | Explicit confidence scores | Never guess silently; let the querying agent decide what to trust |
| Frame storage | Ring buffer (last 60 frames) | Bounded memory; sufficient for interactive debugging |

## 9. References

- [apitrace](https://github.com/apitrace/apitrace) — OpenGL/Vulkan call tracing (MIT)
- [RenderDoc](https://github.com/baldurk/renderdoc) — Frame capture and debugging (MIT)
- [Vulkan Layer Guide](https://renderdoc.org/vulkan-layer-guide.html) — RenderDoc's Vulkan layer documentation
- [Spector.js](https://github.com/BabylonJS/Spector.js) — WebGL debugging (Apache 2.0)
- [WGPU](https://github.com/gfx-rs/wgpu) — WebGPU implementation with multi-backend HAL
- [WebGPU Spec](https://www.w3.org/TR/webgpu/) — Normalized graphics API specification
- [FlatBuffers](https://google.github.io/flatbuffers/) — Zero-copy serialization
- [PLTHook](https://github.com/nicholashagen/plthook) — PLT-based function hooking (MIT)
- [Khronos gl.xml](https://github.com/KhronosGroup/OpenGL-Registry/blob/main/xml/gl.xml) — OpenGL API registry for code generation
