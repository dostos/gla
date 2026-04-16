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
- NFR-4.2: OpenGL 3.3+ (core and compatibility profile), OpenGL ES 2.0/3.0 (via EGL).
- NFR-4.3: Vulkan 1.0+ with common extensions (KHR_swapchain, etc.).
- NFR-4.4: WebGL 1.0 and 2.0 in Chromium-based browsers.

**NFR-5: Security**
- NFR-5.1: The REST API must bind to localhost (127.0.0.1) only. No network-accessible listener.
- NFR-5.2: A shared secret (token) must be exchanged at shim-engine connection time and required on all REST/MCP requests. Generated per-session, passed to the shim via environment variable.
- NFR-5.3: The MCP server must use stdio transport (not SSE over HTTP) by default to avoid exposing a network endpoint.

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
- MCP server calls the Python query functions directly (same process, no HTTP round-trip), sharing the pybind11 bindings with the REST layer.
- Handles serialization (JSON for metadata, base64 PNG for images), pagination, and response formatting.
- Responsible for "LLM-friendly" response formatting: semantic summaries alongside raw data.

### 3.3 IPC Design

**Version Handshake:**
When a shim connects to the core engine, the first message on the Unix socket is a handshake containing: protocol version, FlatBuffers schema hash, API type (GL/VK/WebGL), and process ID. The engine rejects connections with incompatible versions and logs a diagnostic. This prevents silent corruption from version-mismatched shim/engine builds.

**Native shims (OpenGL, Vulkan) to Core Engine:**

```
Shared Memory (POSIX shm, ~256MB ring buffer):
  - Lifecycle: The CORE ENGINE creates the shm segment at startup with a
    well-known name (e.g., /gla_capture_{engine_pid}). The shim opens it
    by name (passed via GLA_SHM_NAME env var). On engine shutdown, the
    engine calls shm_unlink. On target app crash, the engine detects the
    broken socket connection and cleans up the shm segment.
  - Ring buffer protocol: N slots (default 4), each slot holds one frame's
    bulk data. Slot header: {state: FREE|WRITING|READY|READING, frame_id,
    data_size}. Shim claims a FREE slot (CAS to WRITING), writes data,
    sets READY. Engine claims READY slot (CAS to READING), processes,
    sets FREE. If no FREE slot: drop the frame (non-capture mode) or
    block (capture mode). POSIX semaphore signals slot transitions.
  - Multi-app: Each target app gets its own shm segment. The engine
    manages multiple segments identified by connection.

Unix Domain Socket (control channel):
  - Shim sends FlatBuffer-encoded frame metadata:
    {frame_id, draw_call_count, resource_table_offsets, shm_slot_index}
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
  - Performance note: Full-resolution readPixels (1920x1080 RGBA = ~8MB)
    is too expensive for every frame. Default: metadata-only capture.
    Full framebuffer readback is on-demand (triggered by query or explicit
    capture command). Optionally downscale to 1/4 resolution for preview.
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
- **Context handling**: Intercept `glXMakeCurrent`/`eglMakeCurrent` to track per-thread context. Maintain per-context shadow state. Handle shared contexts via `glXCreateContext(..., shareList)`. EGL path also covers OpenGL ES 2.0/3.0 applications (same interception mechanism, ES-specific entry points generated from `gl.xml` with ES profile).
- **Frame boundary**: Intercept `glXSwapBuffers`/`eglSwapBuffers`. Snapshot shadow state + issue readbacks. Block on condition variable if server requests pause.

#### 3.5.2 Vulkan Layer

- **Deployment**: Implicit layer registered via JSON manifest in `~/.local/share/vulkan/implicit_layer.d/gla_layer.json`. Activated via `VK_INSTANCE_LAYERS=VK_LAYER_GLA_capture` or always-on.
- **Dispatch chaining**: Implement `vkGetInstanceProcAddr`/`vkGetDeviceProcAddr`. Store next-layer function pointers in a dispatch table.
- **Command buffer recording**: Intercept `vkCmdDraw*`, `vkCmdBindPipeline`, `vkCmdBindDescriptorSets`, `vkCmdBeginRenderPass`, etc. Record metadata in a parallel structure alongside the application's command buffer.
- **Frame boundary**: Intercept `vkQueuePresentKHR`. During **non-capture** mode, record only lightweight metadata (no GPU sync, no readback) to meet NFR-1.1 (<5% overhead). During **capture** mode (triggered by pause or explicit capture command), inject a `VkFence` at the present call, wait on it to ensure GPU completion, then snapshot state and issue readbacks. This avoids the performance and correctness hazards of `vkQueueWaitIdle` (which would serialize all queues and risk deadlocking multi-queue applications with timeline semaphore dependencies).
- **Async handling**: Command buffers are recorded then submitted later. At `vkQueueSubmit`, associate recorded metadata with the submission. At present time, all metadata for the frame is available. Multi-queue applications are handled by tracking per-queue submissions independently and correlating them at present time via the swapchain image index.

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
  Note: Draw call attribution uses a per-draw-call ID buffer — see Section 3.8.

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
2. For meshes below a configurable threshold (default 100k vertices): full scan to compute AABB.
3. For larger meshes: stratified sampling (configurable rate, default 10%) with configurable margin (default 15%). These defaults are initial estimates and should be validated empirically during M3 development.
4. Transform AABB to world space using model matrix.

**Stage 5: Light and Material Detection** (best-effort)
1. Scan shader parameters for light-related names and structures.
2. Detect PBR parameters (metallic, roughness) and texture slot assignments.
3. Low confidence — always flagged as heuristic.

**Graceful Degradation:**
When the semantic pipeline fails entirely (e.g., obfuscated/auto-generated shader parameter names), `query_scene` returns a structured fallback:
- Camera: "undetected" with the raw matrices that were considered (if any).
- Objects: one SceneObject per draw call with confidence=0, using raw draw call data (vertex count, primitive type, pipeline state) instead of semantic info.
- Lights: empty list.
The response always includes a `reconstruction_quality` field: "full", "partial", or "raw_only".

### 3.8 Pixel Attribution (Draw Call ID Buffer)

Pixel-level queries ("which draw call produced the color at pixel (x,y)?") require a per-pixel draw call ID. Implementation:

1. **Capture-time**: When a frame capture is triggered, the engine replays the frame's draw calls into an offscreen framebuffer with a modified fragment shader that outputs the draw call ID as the color value (R=id&0xFF, G=(id>>8)&0xFF, B=(id>>16)&0xFF). This is a second rendering pass executed by the core engine, not the target app.
2. **OpenGL**: Use a FBO with an integer texture attachment. Inject a trivial fragment shader override via `glUseProgram` for each draw call, outputting `gl_PrimitiveID`-based or draw-call-index-based IDs.
3. **Vulkan**: Use a secondary render pass with a uint32 color attachment. Modify the fragment shader module in the pipeline to output the draw call index.
4. **Fallback**: If shader replacement is not possible (e.g., complex shader dependencies), use depth-buffer comparison: for each pixel, find the draw call whose depth output matches the final depth buffer value. This is approximate but avoids shader modification.
5. **Cost**: This is expensive (full-frame re-render). Pixel attribution is computed on-demand, not for every capture. The `/pixel/{x}/{y}/history` endpoint triggers it on first access for a given frame, then caches the ID buffer.

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

- Bazel (bzlmod) for C/C++ components (shims + core engine) and pybind11 bindings.
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

## 9. Evaluation Scenarios

This section defines concrete scenarios for evaluating GLA's effectiveness as a debugging tool for agents, with a focus on **token efficiency** — how many tokens an LLM needs to consume to solve a given 3D debugging problem with vs. without GLA.

### 9.1 Evaluation Framework

**Metrics:**
- **Token cost**: Total input + output tokens consumed by the LLM to reach a correct diagnosis/fix.
- **Tool calls**: Number of GLA queries needed to solve the problem.
- **Accuracy**: Whether the LLM correctly identifies the root cause.
- **Time-to-diagnosis**: Wall-clock time from problem statement to correct diagnosis.

**Baseline (without GLA):** The LLM has access to source code only. It must read shader code, scene setup code, rendering loop code, and reason about what the rendered output *would* look like — purely from code analysis.

**With GLA:** The LLM can query the actual rendered state: what's on screen, what the transforms are, what the pixel values are. It reasons from observed facts, not from code simulation.

### 9.2 Scenario Categories

#### Category A: Visual Correctness Bugs

Bugs where the rendered output is wrong but the code compiles and runs without errors. These are the hardest to debug from code alone because the LLM must mentally simulate the rendering pipeline.

**A1: Object Not Visible**
- **Setup**: A 3D scene where one object should be visible but isn't. Cause: incorrect model matrix (translated off-screen), backface culling with wrong winding order, or depth test failure (object behind the near plane).
- **Without GLA**: LLM reads the scene setup code, matrix math, camera setup, and tries to compute whether the object falls within the frustum. Requires understanding the full transform chain. Estimated: 5,000-15,000 tokens of code reading + multi-step reasoning.
- **With GLA**: `query_scene(objects)` → object not in list OR object listed with `visible: false` and its bounding box. `inspect_drawcall(dc_id, include=["pipeline"])` → reveals cull_mode or depth_func. 2-3 tool calls, ~500 tokens of query results.
- **Expected token reduction**: 5-10x.

**A2: Wrong Color / Lighting**
- **Setup**: An object renders but with incorrect color. Cause: wrong texture bound, shader uniform not set, or lighting calculation bug.
- **Without GLA**: LLM traces the texture loading path, uniform upload code, shader source. Must mentally execute the shader. Estimated: 8,000-20,000 tokens.
- **With GLA**: `query_pixel(x, y)` → actual color. `inspect_drawcall(dc_id, include=["shader", "textures"])` → see exactly which texture is bound and what uniform values the shader received. 2-3 tool calls, ~800 tokens.
- **Expected token reduction**: 10-20x.

**A3: Z-Fighting / Depth Artifacts**
- **Setup**: Two overlapping surfaces flicker because they're at the same depth.
- **Without GLA**: LLM must identify which objects overlap in 3D space from code, check if their z-values would be close enough to cause precision issues. Requires understanding depth buffer precision.
- **With GLA**: `query_pixel(x, y)` at flickering location → depth value. `compare_frames(frame_a, frame_b, depth="pixels")` → see which draw calls alternate at that pixel. Immediate root cause identification.
- **Expected token reduction**: 10-30x.

**A4: Incorrect Transform / Rotation**
- **Setup**: Object appears at wrong position or orientation. Cause: matrix multiplication order wrong, wrong coordinate system convention (Y-up vs Z-up), or wrong uniform uploaded.
- **Without GLA**: LLM reads matrix construction code, tries to compute final position mentally.
- **With GLA**: `query_scene(objects)` → actual world transform of the object. Compare against expected. `inspect_drawcall(dc_id, include=["shader"])` → see exact matrix values the shader received.
- **Expected token reduction**: 5-15x.

#### Category B: Performance Debugging

**B1: Redundant Draw Calls**
- **Setup**: Scene renders correctly but slowly. Cause: objects drawn multiple times, unnecessary render passes.
- **Without GLA**: LLM reads the rendering loop, tries to trace control flow to find duplicate draws. Hard if the rendering is data-driven.
- **With GLA**: `query_frame(overview)` → draw call count. `query_frame(drawcalls)` → scan for draw calls with identical vertex buffers / transforms. `compare_frames` → confirm same output with fewer draws.
- **Expected token reduction**: 3-10x.

**B2: Overdraw Analysis**
- **Setup**: Too many fragments processed. Cause: objects drawn front-to-back without depth pre-pass, or transparent objects covering large screen area.
- **With GLA**: `query_pixel(x, y).history` → see the full chain of draw calls that touched that pixel. Count how many fragments were processed for a given pixel across the frame.

#### Category C: Regression Detection / Automated QA

**C1: Visual Regression Test**
- **Setup**: After a code change, verify that the rendered output hasn't changed unexpectedly.
- **Agent workflow**: Capture frame before and after code change. `compare_frames(before, after, depth="pixels")` → list of pixels that differ. If diff is non-empty and unexpected, flag as regression.
- **Token efficiency**: A single `compare_frames` call replaces manual screenshot comparison. The structured diff (which draw calls changed, which pixels differ) lets the LLM immediately identify what changed rather than pixel-diffing images.

**C2: Shader Output Verification**
- **Setup**: LLM agent writes a shader. Verify it produces the expected output.
- **Agent workflow**: Compile and render a test scene. `query_pixel(x, y)` at several test locations. Compare against expected values. `query_scene(camera)` to confirm the camera is set up correctly.
- **Token efficiency**: Direct numerical verification instead of visual inspection. The LLM gets exact float values, not a screenshot to interpret.

#### Category D: Complex 3D Task Solving

**D1: Scene Understanding for Code Generation**
- **Setup**: LLM agent needs to modify a 3D scene (add an object, change a light, adjust camera) and verify the result.
- **Without GLA**: Agent writes code, runs it, has no feedback on what actually rendered. Must iterate blindly.
- **With GLA**: Agent writes code → runs it → `query_scene` → verifies objects are where expected → adjusts if needed. Closed-loop development with structured feedback.
- **Expected token reduction per iteration**: 3-5x (each iteration is cheaper because the feedback is precise structured data, not "look at this screenshot and figure out what went wrong").

**D2: Multi-Object Scene Debugging**
- **Setup**: A scene with 50+ objects. Several have incorrect materials/positions. Identify and fix all issues.
- **Without GLA**: LLM reads all scene setup code, reasons about each object. Scales linearly with scene complexity.
- **With GLA**: `query_scene(objects)` → structured list of all 50 objects with positions, bounds, materials. Filter for anomalies (objects at origin when they shouldn't be, objects with missing textures, objects outside expected bounds). Scales with the number of *problems*, not the number of objects.
- **Expected token reduction**: 10-50x for large scenes.

**D3: Deferred Rendering Pipeline Debugging**
- **Setup**: A deferred rendering pipeline where the G-buffer pass works but the lighting pass produces wrong results.
- **Without GLA**: LLM reads both passes' shader code + setup code. Must understand the full deferred pipeline to diagnose. Extremely token-expensive.
- **With GLA**: Capture the frame. Query the G-buffer render pass outputs (normals, albedo, depth) — verify they're correct. Then query the lighting pass — inspect its inputs (are the G-buffer textures bound correctly?) and outputs (is the lighting calculation producing expected values?). Isolate the bug to a specific pass with structured data.

### 9.3 Token Efficiency Hypothesis

**Core claim**: GLA reduces the token cost of 3D debugging tasks by converting *code simulation* problems into *data inspection* problems.

Without GLA, an LLM debugging a rendering issue must:
1. Read source code (shaders, scene setup, rendering loop): **2,000-20,000 tokens** depending on codebase size.
2. Mentally simulate the rendering pipeline (matrix transforms, rasterization, blending): **1,000-10,000 tokens** of chain-of-thought reasoning.
3. Hypothesize about what the output looks like: **unreliable**, often requiring multiple iterations.

With GLA:
1. Query the actual state (1-5 tool calls): **200-2,000 tokens** of structured results.
2. Compare observed vs. expected: **500-2,000 tokens** of reasoning.
3. Identify root cause from concrete discrepancy: **high reliability**, often single-iteration.

**Projected savings by category:**

| Category | Without GLA (tokens) | With GLA (tokens) | Reduction |
|----------|---------------------|-------------------|-----------|
| A: Visual bugs | 10,000-30,000 | 1,000-3,000 | 5-20x |
| B: Performance | 5,000-15,000 | 1,000-3,000 | 3-10x |
| C: Regression/QA | 5,000-10,000 | 500-2,000 | 5-10x |
| D: Complex 3D tasks | 20,000-100,000 | 2,000-10,000 | 10-50x |

### 9.4 Adversarial Scenarios (Category E)

These scenarios are intentionally designed to be **hard to debug from code alone**. The bugs are subtle, misleading, or involve interactions that require runtime observation to untangle. The code looks plausible — an LLM reading it would likely either miss the bug entirely or chase the wrong hypothesis.

#### E1: State Leak Between Draw Calls
- **Setup**: Object B renders with Object A's texture. Cause: `glBindTexture` is called for object A but not re-bound before object B's draw call. The code for object B *looks* correct in isolation — it sets up its shader, its vertex buffer, its uniforms — but never re-binds its texture because it assumes the "default" binding.
- **Why it's hard**: The bug is in the *absence* of a call, not a wrong call. The code for object B looks complete. An LLM reading B's rendering code sees nothing wrong. The bug only appears when you understand the *ordering* of A then B and that GL state persists.
- **With GLA**: `inspect_drawcall(B, include=["textures"])` → shows A's texture is bound. Immediate diagnosis.
- **Difficulty rating**: High (requires understanding implicit state machine semantics across draw calls).

#### E2: NaN Propagation Through Transforms
- **Setup**: One object's normal matrix is computed as `transpose(inverse(modelMatrix))`. The model matrix has a zero-scale axis (flatten to 2D for a shadow pass). `inverse()` produces Inf, `transpose()` of Inf stays Inf, then the shader normalizes a normal vector with Inf components → NaN. The NaN propagates through lighting → object renders as black.
- **Why it's hard**: The code `transpose(inverse(model))` is the *textbook-correct* way to compute normal matrices. The zero-scale axis is set 200 lines earlier in a different function. An LLM would have to trace the value through multiple function calls and recognize that a zero scale makes the matrix singular.
- **With GLA**: `inspect_drawcall(dc_id, include=["shader"])` → normal matrix parameter contains Inf/NaN values. Immediate root cause.
- **Difficulty rating**: Very high (requires numerical reasoning across distant code).

#### E3: Off-By-One Index Buffer Corruption
- **Setup**: A mesh renders with subtle triangle artifacts (some faces twisted or missing). Cause: index buffer upload uses `sizeof(indices)` instead of `indices.size() * sizeof(uint16_t)` — on some compilers/platforms this gives the size of the vector object (24 bytes) instead of the data. The first few triangles render fine (coincidence), but later triangles read garbage indices.
- **Why it's hard**: The first few triangles look correct, so a quick visual check might not catch it. The `sizeof` vs `.size() * sizeof()` pattern is a classic C++ trap that looks correct at a glance. The mesh partially renders, which suggests the setup is "mostly right."
- **With GLA**: `inspect_drawcall(dc_id, include=["vertices"])` → index buffer shows data truncated after N bytes. Vertex count vs index count mismatch. Or `query_pixel` at a corrupted triangle → trace to the draw call → see that index values exceed vertex count.
- **Difficulty rating**: High (subtle C++ trap, partial success masks the bug).

#### E4: Double-Negation Culling Bug
- **Setup**: An object renders its interior instead of its exterior. Cause: the model matrix has a negative scale (mirror transform) which flips winding order, AND the code sets `glFrontFace(GL_CW)` when it should be `GL_CCW` (or vice versa). The two errors partially cancel — some faces appear correct, others don't. The code has a comment: `// GL_CW because we're using a right-handed coordinate system` which misdirects.
- **Why it's hard**: Two compensating errors. Fixing either one alone makes things *worse* (now nothing renders, or everything is inverted). The misleading comment in the code would lead an LLM to trust the `GL_CW` choice. An LLM must reason about the interaction of negative scale + winding order + front face convention simultaneously.
- **With GLA**: `inspect_drawcall(dc_id, include=["pipeline", "shader"])` → see `cull_mode`, `front_face`, and the model matrix with negative determinant. The combination makes the bug obvious.
- **Difficulty rating**: Very high (compensating errors, misleading comments).

#### E5: Uniform Location Collision
- **Setup**: Two different shader programs use `glGetUniformLocation` and the results are cached in an array indexed by a material enum. After a refactor, material enum values were reordered but the uniform cache wasn't cleared. Now material A's uniforms are uploaded to material B's shader.
- **Why it's hard**: The uniform upload code looks correct — it uses the cached location, which was valid before the refactor. The refactored enum file is in a different directory. The bug only manifests for specific material combinations that happen to have colliding enum values.
- **With GLA**: `inspect_drawcall(dc_id, include=["shader"])` → uniform values don't match what the code *thinks* it's setting. Compare the shader parameter values across draw calls with different materials → see that two materials have swapped uniforms.
- **Difficulty rating**: Very high (requires understanding stale cache + enum reorder interaction).

#### E6: Depth Buffer Precision Trap
- **Setup**: A large outdoor scene with near=0.001, far=100000. Distant objects have severe z-fighting. The projection matrix code uses the "standard" perspective formula, which is technically correct but concentrates depth precision near the near plane.
- **Why it's hard**: The projection matrix code is textbook-correct. The near/far values are set in a config file loaded at runtime. An LLM would need to (a) find the config values, (b) compute the depth buffer precision distribution, (c) realize that the ratio far/near = 10^8 leaves essentially zero precision beyond ~100 units.
- **With GLA**: `query_scene(camera)` → near=0.001, far=100000. `query_pixel(x,y)` at a z-fighting location → depth values of two objects differ by < depth buffer epsilon. The numerical evidence makes the diagnosis trivial.
- **Difficulty rating**: High (requires numerical reasoning about depth buffer precision).

#### E7: Shader Include Order Bug
- **Setup**: A shader uses `#include` directives (via a custom preprocessor). Two included files both define a helper function `saturate()` but with different implementations (one clamps to [0,1], the other returns `max(0, x)`). Due to include order, the wrong `saturate()` is used in the lighting calculation, causing subtle over-brightening only for HDR values > 1.
- **Why it's hard**: The shader code itself calls `saturate()` which seems straightforward. The duplicate definition is in two different include files. The visual difference is subtle (over-bright highlights). An LLM would need to resolve the include chain and notice the shadowed definition.
- **With GLA**: `query_pixel(x,y)` at a highlight → color channel > 1.0 (should be clamped). `inspect_drawcall(include=["shader"])` → see the actual shader source after preprocessing. Compare pixel values in highlight vs. non-highlight regions.
- **Difficulty rating**: Medium-high (requires include resolution, subtle visual artifact).

#### E8: Race Condition in Multi-Threaded Resource Upload
- **Setup**: Textures are loaded asynchronously in a worker thread and uploaded to GL in the main thread. A missing mutex allows the render loop to use a texture that's only partially uploaded (some mip levels missing or buffer partially filled). The result: objects intermittently render with corrupted or black textures.
- **Why it's hard**: The bug is non-deterministic. The code structure (async load + main thread upload) is a common pattern. The mutex is missing from one of several upload paths — the others are correctly synchronized. Reading the code, each path looks similar, and the LLM might assume they're all correct.
- **With GLA**: `compare_frames(N, N+1)` → texture data changes between frames for the same object (should be static). `inspect_drawcall(include=["textures"])` → texture shows partial data or wrong dimensions in some frames. The non-deterministic nature becomes visible as frame-to-frame differences.
- **Difficulty rating**: Very high (non-deterministic, requires understanding threading + GL resource lifecycle).

#### E9: Scissor Rect Not Reset
- **Setup**: A UI overlay pass sets a scissor rect for clipping. The 3D scene pass afterward doesn't disable scissor test. Result: 3D objects outside the UI rect's bounds are clipped. The scene looks correct in the center of the screen but objects near the edges are cut off.
- **Why it's hard**: The 3D rendering code is entirely correct on its own. The bug is a missing `glDisable(GL_SCISSOR_TEST)` between the UI pass and the 3D pass. The UI code is in a different module. The visual symptom (objects clipped at edges) might be mistaken for a frustum culling bug.
- **With GLA**: `inspect_drawcall(dc_id, include=["pipeline"])` for a clipped 3D object → shows scissor rect is enabled and set to the UI region. Immediate diagnosis: scissor state leaked from UI pass.
- **Difficulty rating**: Medium-high (cross-module state leak, misleading symptom).

#### E10: Compensating Bugs in View/Projection Setup
- **Setup**: The view matrix is constructed with the wrong handedness (left-handed instead of right-handed), AND the projection matrix uses the wrong NDC range ([-1,1] instead of [0,1] or vice versa). For simple scenes viewed from certain angles, these errors compensate and the output looks correct. But when the camera rotates past a certain angle, objects mirror or clip unexpectedly.
- **Why it's hard**: The scene looks correct for the default camera position (which is how it was tested). Both the view and projection code individually look wrong to an expert, but together they produce correct-looking output for the common case. An LLM might even "fix" one and make the problem worse.
- **With GLA**: `query_scene(camera)` → camera forward/right vectors are mirrored. `inspect_drawcall(include=["shader"])` → compare raw view/projection matrices against expected values for the given camera position. The numerical values reveal both errors.
- **Difficulty rating**: Extremely high (compensating bugs, angle-dependent symptoms).

### 9.5 Adversarial Design Principles

The adversarial scenarios above are constructed using these principles that make bugs hard for LLMs to diagnose from code alone:

| Principle | Description | Examples |
|-----------|-------------|----------|
| **Absent code** | The bug is a missing call, not a wrong call | E1, E9 |
| **Distant cause** | Root cause is far from the symptom in code distance | E2, E5, E6 |
| **Compensating errors** | Two bugs partially cancel, fixing one makes things worse | E4, E10 |
| **Stale state** | Cached/global state from a previous operation corrupts a later one | E1, E5, E9 |
| **Subtle numerics** | Requires floating-point reasoning (Inf, NaN, precision) | E2, E6 |
| **Looks correct** | Code follows textbook patterns but preconditions are violated | E2, E3, E6 |
| **Non-deterministic** | Bug depends on timing/ordering, not present in every frame | E8 |
| **Misleading comments** | Code comments direct the reader toward wrong conclusions | E4 |
| **Partial success** | Output is mostly correct, making the bug easy to overlook | E3, E7, E10 |

**Key insight for evaluation**: These bugs are specifically designed so that **code inspection alone scales poorly** (the LLM must read and correlate code across multiple files, reason about implicit state, and simulate numerical computation) while **runtime state inspection via GLA scales well** (1-3 targeted queries expose the root cause directly).

### 9.6 Evaluation Test Suite

To validate these claims, GLA should ship with a test suite of intentionally broken 3D scenes:

```
tests/eval/
  # Category A: Visual correctness
  a1_missing_object/       # object translated off-screen
  a2_wrong_color/          # wrong texture bound
  a3_z_fighting/           # overlapping coplanar surfaces
  a4_wrong_transform/      # matrix multiplication order bug

  # Category B: Performance
  b1_redundant_draws/      # same object drawn 3x

  # Category C: Regression/QA
  c1_visual_regression/    # before/after scene pair

  # Category D: Complex 3D tasks
  d1_scene_modification/   # "add a red cube at (5,0,0)" task
  d2_multi_object_debug/   # 50-object scene with 5 broken objects
  d3_deferred_pipeline/    # broken lighting in deferred renderer

  # Category E: Adversarial (hard to debug from code)
  e1_state_leak/           # GL state leaks between draw calls
  e2_nan_propagation/      # singular matrix -> NaN in normals
  e3_index_buffer_obo/     # sizeof vs size()*sizeof trap
  e4_double_negation_cull/ # negative scale + wrong winding cancel
  e5_uniform_collision/    # stale uniform cache after enum reorder
  e6_depth_precision/      # near/far ratio destroys z-buffer precision
  e7_shader_include_order/ # shadowed function definition in includes
  e8_race_texture_upload/  # missing mutex on async texture upload
  e9_scissor_not_reset/    # UI pass scissor leaks into 3D pass
  e10_compensating_vp/     # wrong handedness + wrong NDC cancel out
```

Each scenario includes:
1. A minimal OpenGL application with the bug.
2. A description of the expected correct output.
3. A ground-truth diagnosis (what the bug is and how to fix it).
4. A difficulty rating and which adversarial principles it uses.
5. A script that runs an LLM agent (with and without GLA) and measures tokens consumed, tool calls, and whether the correct diagnosis was reached.

This test suite serves dual purposes: validating GLA's usefulness and benchmarking LLM capability on graphics debugging tasks.

## 10. References

- [apitrace](https://github.com/apitrace/apitrace) — OpenGL/Vulkan call tracing (MIT)
- [RenderDoc](https://github.com/baldurk/renderdoc) — Frame capture and debugging (MIT)
- [Vulkan Layer Guide](https://renderdoc.org/vulkan-layer-guide.html) — RenderDoc's Vulkan layer documentation
- [Spector.js](https://github.com/BabylonJS/Spector.js) — WebGL debugging (Apache 2.0)
- [WGPU](https://github.com/gfx-rs/wgpu) — WebGPU implementation with multi-backend HAL
- [WebGPU Spec](https://www.w3.org/TR/webgpu/) — Normalized graphics API specification
- [FlatBuffers](https://google.github.io/flatbuffers/) — Zero-copy serialization
- [PLTHook](https://github.com/nicholashagen/plthook) — PLT-based function hooking (MIT)
- [Khronos gl.xml](https://github.com/KhronosGroup/OpenGL-Registry/blob/main/xml/gl.xml) — OpenGL API registry for code generation
