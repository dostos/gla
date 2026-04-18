# OpenGPA Core MVP (M1+M2) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a working end-to-end pipeline: OpenGL shim intercepts draw calls via LD_PRELOAD, captures frame state into shared memory, core engine stores it, and a REST API serves queries about draw calls, pipeline state, and pixel data.

**Architecture:** Per-API shim (C, LD_PRELOAD) communicates with a C++ core engine via shared memory (bulk data) + Unix socket (control). The engine stores per-frame snapshots, normalizes raw GL calls into an API-agnostic representation, and serves queries. A Python layer (FastAPI via pybind11) exposes the REST API.

**Tech Stack:** C (shim), C++17 (core engine), Python 3.11+ (REST API), Bazel (build), FlatBuffers (serialization), pybind11 (bindings), FastAPI (HTTP), GLM (math), Google Test (C++ tests), pytest (Python tests)

**Spec:** `docs/superpowers/specs/2026-04-16-gla-design.md`

**Scope:** Milestones M1 (OpenGL shim + basic capture) and M2 (Query engine + REST API). Milestones M3-M7 (semantic reconstruction, MCP server, Vulkan, WebGL, advanced queries) are separate plans.

---

## File Structure

```
gla/
  MODULE.bazel                            # Bazel module (bzlmod) — declares deps
  BUILD.bazel                             # Top-level build (may be empty)
  .bazelrc                                # Default build flags (C++17, etc.)
  pyproject.toml                          # Python package config (for pip install)
  schemas/
    BUILD.bazel
    frame_capture.fbs                     # FlatBuffers schema for IPC metadata
  src/
    shims/
      gl/
        BUILD.bazel                       # cc_shared_library for libgla_gl.so
        gl_shim.c                         # LD_PRELOAD entry: dlsym, function dispatch
        gl_wrappers.c                     # Intercepted GL function wrappers
        gl_wrappers.h
        shadow_state.c                    # GL state machine mirror
        shadow_state.h
        frame_capture.c                   # Snapshot state + readback at frame boundary
        frame_capture.h
        ipc_client.c                      # Shm + socket client to engine
        ipc_client.h
    core/
      BUILD.bazel                         # cc_library for gla_core
      engine.cpp                          # Main engine process entry point
      engine.h
      ipc/
        shm_ring_buffer.cpp              # POSIX shm ring buffer (4 slots, CAS)
        shm_ring_buffer.h
        control_socket.cpp               # Unix domain socket server
        control_socket.h
        protocol.h                       # Handshake + message types
      store/
        frame_store.cpp                  # Ring buffer of frame snapshots
        frame_store.h
        raw_frame.h                      # RawFrameCapture struct
      normalize/
        normalizer.cpp                   # Raw GL calls → NormalizedFrame
        normalizer.h
        normalized_types.h              # DrawCall, ShaderParameter, etc.
      query/
        query_engine.cpp                # Filtering, pixel lookup
        query_engine.h
    bindings/
      BUILD.bazel                       # pybind_extension for _gla_core.so
      py_gla.cpp                        # pybind11 bindings
    python/
      gla/
        __init__.py
        core.py                         # Thin wrapper around C++ bindings
        launcher.py                     # Main entry: engine + API in one process
        api/
          __init__.py
          app.py                        # FastAPI application + auth middleware
          routes_frames.py              # /api/v1/frames/* endpoints
          routes_drawcalls.py           # /api/v1/frames/*/drawcalls/* endpoints
          routes_pixel.py               # /api/v1/frames/*/pixel/* endpoints
          routes_control.py             # /api/v1/control/* endpoints
  tests/
    core/
      BUILD.bazel                       # cc_test targets
      test_shm_ring_buffer.cpp          # Ring buffer unit tests
      test_control_socket.cpp           # Socket + handshake tests
      test_frame_store.cpp              # Frame storage tests
      test_normalizer.cpp               # GL normalization tests
      test_query_engine.cpp             # Query engine tests
    shims/
      BUILD.bazel
      test_shadow_state.c               # Shadow state unit tests
    python/
      BUILD.bazel                       # py_test targets
      test_api_frames.py                # REST API frame endpoint tests
      test_api_drawcalls.py             # REST API draw call endpoint tests
      test_api_pixel.py                 # REST API pixel endpoint tests
      test_api_control.py               # REST API control endpoint tests
      conftest.py                       # Shared fixtures (mock engine, test client)
    integration/
      BUILD.bazel
      mini_gl_app.c                     # Minimal GL app for testing
      test_end_to_end.py                # Full pipeline: GL app → shim → engine → REST
```

---

## Task 1: Project Scaffolding + Build System

**Files:**
- Create: `MODULE.bazel`
- Create: `.bazelrc`
- Create: `BUILD.bazel`
- Create: `src/shims/gl/BUILD.bazel`
- Create: `src/core/BUILD.bazel`
- Create: `src/bindings/BUILD.bazel`
- Create: `schemas/BUILD.bazel`
- Create: `tests/core/BUILD.bazel`
- Create: `tests/shims/BUILD.bazel`
- Create: `pyproject.toml`
- Create: `src/python/gla/__init__.py`

- [ ] **Step 1: Create MODULE.bazel**

```starlark
module(name = "gla", version = "0.1.0")

# C/C++ dependencies
bazel_dep(name = "flatbuffers", version = "24.3.25")
bazel_dep(name = "glm", version = "1.0.1")
bazel_dep(name = "googletest", version = "1.15.2")
bazel_dep(name = "pybind11_bazel", version = "2.13.6")
bazel_dep(name = "rules_python", version = "1.0.0")
bazel_dep(name = "rules_cc", version = "0.1.0")
bazel_dep(name = "rules_flatbuffers", version = "24.3.25")

# Python toolchain
python = use_extension("@rules_python//python/extensions:python.bzl", "python")
python.toolchain(python_version = "3.11")
```

- [ ] **Step 2: Create .bazelrc**

```
# C/C++ settings
build --cxxopt=-std=c++17
build --copt=-std=c11
build --copt=-Wall
build --copt=-Wextra
build --copt=-fPIC

# Test output
test --test_output=errors
```

- [ ] **Step 3: Create src/shims/gl/BUILD.bazel**

```starlark
# Shadow state as a separate library (testable without LD_PRELOAD side effects)
cc_library(
    name = "shadow_state",
    srcs = ["shadow_state.c"],
    hdrs = ["shadow_state.h"],
    visibility = ["//tests/shims:__pkg__"],
)

# The full LD_PRELOAD shared library
cc_shared_library(
    name = "gla_gl",
    deps = [":gla_gl_impl"],
)

cc_library(
    name = "gla_gl_impl",
    srcs = [
        "gl_shim.c",
        "gl_wrappers.c",
        "frame_capture.c",
        "ipc_client.c",
    ],
    hdrs = [
        "gl_wrappers.h",
        "frame_capture.h",
        "ipc_client.h",
    ],
    deps = [":shadow_state"],
    linkopts = ["-ldl", "-lrt", "-lpthread"],
)
```

- [ ] **Step 4: Create src/core/BUILD.bazel**

```starlark
cc_library(
    name = "gla_core",
    srcs = [
        "ipc/shm_ring_buffer.cpp",
        "ipc/control_socket.cpp",
        "store/frame_store.cpp",
        "normalize/normalizer.cpp",
        "query/query_engine.cpp",
    ],
    hdrs = [
        "engine.h",
        "ipc/shm_ring_buffer.h",
        "ipc/control_socket.h",
        "ipc/protocol.h",
        "store/frame_store.h",
        "store/raw_frame.h",
        "normalize/normalizer.h",
        "normalize/normalized_types.h",
        "query/query_engine.h",
    ],
    deps = [
        "//schemas:frame_capture_fbs",
        "@glm",
    ],
    linkopts = ["-lrt", "-lpthread"],
    visibility = [
        "//src/bindings:__pkg__",
        "//tests:__subpackages__",
    ],
)

cc_binary(
    name = "gla_engine",
    srcs = ["engine.cpp"],
    deps = [":gla_core"],
)
```

- [ ] **Step 5: Create schemas/BUILD.bazel**

```starlark
load("@rules_flatbuffers//flatbuffers:flatbuffers.bzl", "flatbuffer_cc_library")

flatbuffer_cc_library(
    name = "frame_capture_fbs",
    srcs = ["frame_capture.fbs"],
    visibility = ["//visibility:public"],
)
```

- [ ] **Step 6: Create tests/core/BUILD.bazel**

```starlark
cc_test(
    name = "test_shm_ring_buffer",
    srcs = ["test_shm_ring_buffer.cpp"],
    deps = [
        "//src/core:gla_core",
        "@googletest//:gtest_main",
    ],
)

cc_test(
    name = "test_control_socket",
    srcs = ["test_control_socket.cpp"],
    deps = [
        "//src/core:gla_core",
        "@googletest//:gtest_main",
    ],
)

cc_test(
    name = "test_frame_store",
    srcs = ["test_frame_store.cpp"],
    deps = [
        "//src/core:gla_core",
        "@googletest//:gtest_main",
    ],
)

cc_test(
    name = "test_normalizer",
    srcs = ["test_normalizer.cpp"],
    deps = [
        "//src/core:gla_core",
        "@googletest//:gtest_main",
    ],
)

cc_test(
    name = "test_query_engine",
    srcs = ["test_query_engine.cpp"],
    deps = [
        "//src/core:gla_core",
        "@googletest//:gtest_main",
    ],
)
```

- [ ] **Step 7: Create tests/shims/BUILD.bazel**

```starlark
cc_test(
    name = "test_shadow_state",
    srcs = ["test_shadow_state.c"],
    deps = ["//src/shims/gl:shadow_state"],
)
```

- [ ] **Step 8: Create src/bindings/BUILD.bazel**

```starlark
load("@pybind11_bazel//:build_defs.bzl", "pybind_extension")

pybind_extension(
    name = "_gla_core",
    srcs = ["py_gla.cpp"],
    deps = ["//src/core:gla_core"],
    visibility = ["//visibility:public"],
)
```

- [ ] **Step 9: Create pyproject.toml**

```toml
[project]
name = "gla"
version = "0.1.0"
requires-python = ">=3.11"
dependencies = [
    "fastapi>=0.115",
    "uvicorn>=0.34",
]

[project.optional-dependencies]
dev = [
    "pytest>=8.0",
    "httpx>=0.27",
]
```

- [ ] **Step 10: Create .gitignore**

```
bazel-bin/
bazel-out/
bazel-gla/
bazel-testlogs/
__pycache__/
*.egg-info/
*.so
*.o
.cache/
```

- [ ] **Step 11: Create placeholder source files and __init__.py**

Create empty/stub files for all source files so the build system can be validated:
- `src/shims/gl/gl_shim.c` (empty)
- `src/shims/gl/gl_wrappers.c` + `.h` (empty)
- `src/shims/gl/shadow_state.c` + `.h` (empty)
- `src/shims/gl/frame_capture.c` + `.h` (empty)
- `src/shims/gl/ipc_client.c` + `.h` (empty)
- `src/core/engine.cpp` + `.h` (stubs with main)
- `src/core/ipc/shm_ring_buffer.cpp` + `.h` (empty)
- `src/core/ipc/control_socket.cpp` + `.h` (empty)
- `src/core/ipc/protocol.h` (empty)
- `src/core/store/frame_store.cpp` + `.h` (empty)
- `src/core/store/raw_frame.h` (empty)
- `src/core/normalize/normalizer.cpp` + `.h` (empty)
- `src/core/normalize/normalized_types.h` (empty)
- `src/core/query/query_engine.cpp` + `.h` (empty)
- `src/bindings/CMakeLists.txt` + `py_gla.cpp` (stubs)
- `src/python/gla/__init__.py` (empty)
- Test stubs for all test files

- [ ] **Step 12: Verify build system compiles**

Run: `bazel build //...`
Expected: Builds successfully with stub files (may have warnings for empty objects, that's fine)

- [ ] **Step 13: Commit**

```bash
git add -A
git commit -m "feat: project scaffolding with Bazel, FlatBuffers, pybind11, pytest"
```

---

## Task 2: FlatBuffers Schema for IPC Metadata

**Files:**
- Create: `schemas/frame_capture.fbs`
- Already handled: `schemas/BUILD.bazel` (flatbuffer_cc_library rule from Task 1)

- [ ] **Step 1: Write FlatBuffers schema**

```fbs
// schemas/frame_capture.fbs
namespace gla.schema;

enum ApiType : byte { OpenGL = 0, Vulkan = 1, WebGL = 2 }
enum PrimitiveType : byte { Triangles = 0, Lines = 1, Points = 2, TriangleStrip = 3, TriangleFan = 4, LineStrip = 5 }
enum ParamType : byte { Float = 0, Vec2 = 1, Vec3 = 2, Vec4 = 3, Mat3 = 4, Mat4 = 5, Int = 6, Sampler2D = 7 }

table ShaderParam {
  name: string;
  param_type: ParamType;
  data: [ubyte];     // raw bytes of the value
}

table TextureBinding {
  slot: uint32;
  texture_id: uint32;
  width: uint32;
  height: uint32;
  format: uint32;    // GL internal format enum
}

table PipelineState {
  viewport_x: int32;
  viewport_y: int32;
  viewport_w: uint32;
  viewport_h: uint32;
  scissor_enabled: bool;
  scissor_x: int32;
  scissor_y: int32;
  scissor_w: uint32;
  scissor_h: uint32;
  depth_test: bool;
  depth_write: bool;
  depth_func: uint32;
  blend_enabled: bool;
  blend_src: uint32;
  blend_dst: uint32;
  cull_enabled: bool;
  cull_mode: uint32;
  front_face: uint32;
}

table BulkDataRef {
  shm_offset: uint64;    // offset into shared memory
  size: uint64;           // size in bytes
}

table VertexAttribute {
  location: uint32;
  format: uint32;         // GL type enum
  components: uint32;
  stride: uint32;
  offset: uint32;
}

table DrawCallCapture {
  id: uint32;
  primitive_type: PrimitiveType;
  vertex_count: uint32;
  index_count: uint32;
  instance_count: uint32;
  shader_program_id: uint32;
  params: [ShaderParam];
  textures: [TextureBinding];
  pipeline: PipelineState;
  vertex_data: BulkDataRef;       // ref to vertex buffer in shm
  index_data: BulkDataRef;        // ref to index buffer in shm (if indexed)
  attributes: [VertexAttribute];
}

table FrameCapture {
  frame_id: uint64;
  timestamp: double;
  api: ApiType;
  draw_calls: [DrawCallCapture];
  framebuffer_color: BulkDataRef;   // RGBA pixels in shm
  framebuffer_depth: BulkDataRef;   // float32 depth in shm
  framebuffer_stencil: BulkDataRef; // uint8 stencil in shm
  framebuffer_width: uint32;
  framebuffer_height: uint32;
}

table Handshake {
  protocol_version: uint32;
  schema_hash: uint64;
  api_type: ApiType;
  process_id: uint32;
}

table ControlCommand {
  pause: bool;
  resume: bool;
  step_frames: uint32;
}

root_type FrameCapture;
```

- [ ] **Step 2: Verify schema compiles via Bazel**

The `flatbuffer_cc_library` rule in `schemas/BUILD.bazel` (created in Task 1) handles codegen automatically. The `//src/core:gla_core` target depends on `//schemas:frame_capture_fbs`.

Run: `bazel build //schemas:frame_capture_fbs`
Expected: Generates `frame_capture_generated.h` in bazel-bin

- [ ] **Step 3: Commit**

```bash
git add schemas/frame_capture.fbs
git commit -m "feat: add FlatBuffers schema for frame capture IPC"
```

---

## Task 3: Shared Memory Ring Buffer

**Files:**
- Create: `src/core/ipc/shm_ring_buffer.h`
- Create: `src/core/ipc/shm_ring_buffer.cpp`
- Create: `tests/core/test_shm_ring_buffer.cpp`

- [ ] **Step 1: Write failing tests for ring buffer**

Test cases:
1. Create ring buffer, verify shm segment exists
2. Writer claims slot, writes data, marks ready
3. Reader claims ready slot, reads data, marks free
4. Full ring buffer — writer gets nullptr (non-blocking mode)
5. Cleanup on destroy — shm_unlink called
6. Multiple sequential write/read cycles

```cpp
// tests/core/test_shm_ring_buffer.cpp
#include <gtest/gtest.h>
#include "ipc/shm_ring_buffer.h"

TEST(ShmRingBuffer, CreateAndDestroy) {
    auto buf = gla::ShmRingBuffer::create("/gla_test_rb", 4, 1024 * 1024);
    ASSERT_NE(buf, nullptr);
    // Verify shm exists
    int fd = shm_open("/gla_test_rb", O_RDONLY, 0);
    ASSERT_GE(fd, 0);
    close(fd);
    buf.reset();
    // Verify shm cleaned up
    fd = shm_open("/gla_test_rb", O_RDONLY, 0);
    ASSERT_EQ(fd, -1);
}

TEST(ShmRingBuffer, OpenExisting) {
    auto owner = gla::ShmRingBuffer::create("/gla_test_rb2", 4, 1024);
    auto client = gla::ShmRingBuffer::open("/gla_test_rb2");
    ASSERT_NE(client, nullptr);
}

TEST(ShmRingBuffer, WriteAndRead) {
    auto buf = gla::ShmRingBuffer::create("/gla_test_rb3", 4, 1024);
    auto slot = buf->claim_write_slot();
    ASSERT_NE(slot.data, nullptr);
    memcpy(slot.data, "hello", 5);
    buf->commit_write(slot.index, 5);

    auto rslot = buf->claim_read_slot();
    ASSERT_NE(rslot.data, nullptr);
    ASSERT_EQ(rslot.size, 5);
    ASSERT_EQ(memcmp(rslot.data, "hello", 5), 0);
    buf->release_read(rslot.index);
}

TEST(ShmRingBuffer, FullRingReturnsNull) {
    auto buf = gla::ShmRingBuffer::create("/gla_test_rb4", 2, 1024);
    auto s1 = buf->claim_write_slot();
    buf->commit_write(s1.index, 10);
    auto s2 = buf->claim_write_slot();
    buf->commit_write(s2.index, 10);
    // Ring is full (2 slots, both READY)
    auto s3 = buf->claim_write_slot();
    ASSERT_EQ(s3.data, nullptr);
}
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `bazel test //tests/core:test_shm_ring_buffer`
Expected: FAIL (functions not defined)

- [ ] **Step 3: Implement ShmRingBuffer**

`src/core/ipc/shm_ring_buffer.h`:
```cpp
#pragma once
#include <cstdint>
#include <cstddef>
#include <memory>
#include <atomic>
#include <string>

namespace gla {

struct SlotHeader {
    std::atomic<uint32_t> state;  // FREE=0, WRITING=1, READY=2, READING=3
    uint64_t frame_id;
    uint64_t data_size;
};

struct WriteSlot {
    void* data;
    uint32_t index;
};

struct ReadSlot {
    const void* data;
    uint64_t size;
    uint32_t index;
};

class ShmRingBuffer {
public:
    static std::unique_ptr<ShmRingBuffer> create(
        const std::string& name, uint32_t num_slots, size_t slot_size);
    static std::unique_ptr<ShmRingBuffer> open(const std::string& name);
    ~ShmRingBuffer();

    WriteSlot claim_write_slot();
    void commit_write(uint32_t index, uint64_t size);
    ReadSlot claim_read_slot();
    void release_read(uint32_t index);

    uint32_t num_slots() const { return num_slots_; }
    size_t slot_size() const { return slot_size_; }

private:
    ShmRingBuffer(const std::string& name, void* base, size_t total_size,
                  uint32_t num_slots, size_t slot_size, bool owner);

    SlotHeader* slot_header(uint32_t index);
    void* slot_data(uint32_t index);

    std::string name_;
    void* base_;
    size_t total_size_;
    uint32_t num_slots_;
    size_t slot_size_;
    bool owner_;  // responsible for shm_unlink
};

}  // namespace gla
```

Implement in `shm_ring_buffer.cpp`: shm_open/ftruncate/mmap for create, shm_open/mmap for open. CAS on slot state atomics. Slot layout: [RingHeader][SlotHeader0][Data0][SlotHeader1][Data1]...

- [ ] **Step 4: Run tests to verify they pass**

Run: `bazel test //tests/core:test_shm_ring_buffer`
Expected: All PASS

- [ ] **Step 5: Commit**

```bash
git add src/core/ipc/shm_ring_buffer.{h,cpp} tests/core/test_shm_ring_buffer.cpp
git commit -m "feat: shared memory ring buffer with CAS-based slot protocol"
```

---

## Task 4: Unix Domain Socket Control Channel

**Files:**
- Create: `src/core/ipc/protocol.h`
- Create: `src/core/ipc/control_socket.h`
- Create: `src/core/ipc/control_socket.cpp`
- Create: `tests/core/test_control_socket.cpp`

- [ ] **Step 1: Write failing tests**

Test cases:
1. Server starts listening on a Unix socket path
2. Client connects, sends handshake, server validates
3. Client sends frame-ready message, server receives
4. Server sends pause command, client receives
5. Version mismatch rejected

- [ ] **Step 2: Run tests to verify they fail**

- [ ] **Step 3: Implement protocol.h with message types**

Define: `MsgType` enum (HANDSHAKE, FRAME_READY, CONTROL), length-prefixed framing (4-byte length header + payload). Handshake contains protocol_version, api_type, pid. Frame-ready contains frame_id, shm_slot_index.

- [ ] **Step 4: Implement ControlSocket server and client**

Server: bind/listen on Unix socket, accept connections, read/write messages with framing. Client: connect, send handshake, send frame-ready notifications, receive control commands. Both use non-blocking I/O with poll().

- [ ] **Step 5: Run tests to verify they pass**

- [ ] **Step 6: Commit**

```bash
git add src/core/ipc/protocol.h src/core/ipc/control_socket.{h,cpp} tests/core/test_control_socket.cpp
git commit -m "feat: Unix domain socket control channel with handshake"
```

---

## Task 5: GL Shadow State Tracker

**Files:**
- Create: `src/shims/gl/shadow_state.h`
- Create: `src/shims/gl/shadow_state.c`
- Create: `tests/shims/test_shadow_state.c`

- [ ] **Step 1: Write failing tests**

Test cases:
1. Initialize shadow state — default values match GL spec defaults
2. Track texture bindings: `shadow_bind_texture(GL_TEXTURE_2D, 5)` → query returns 5
3. Track active texture unit: `shadow_active_texture(GL_TEXTURE1)` → slot 1
4. Track shader program: `shadow_use_program(3)` → query returns 3
5. Track uniforms: `shadow_set_uniform_mat4(loc, data)` → query returns data
6. Track enables: `shadow_enable(GL_DEPTH_TEST)` → query returns true
7. Track viewport: `shadow_viewport(0, 0, 800, 600)` → query returns values
8. Track blend state: `shadow_blend_func(GL_SRC_ALPHA, GL_ONE_MINUS_SRC_ALPHA)`
9. Track cull state: `shadow_cull_face(GL_BACK)`, `shadow_front_face(GL_CCW)`
10. Serialize to struct for snapshot

- [ ] **Step 2: Run tests to verify they fail**

- [ ] **Step 3: Implement shadow state**

A global struct (per-context, but start with single context) that mirrors the GL state we care about:
```c
typedef struct {
    // Texture units
    uint32_t active_texture_unit;
    uint32_t bound_textures[MAX_TEXTURE_UNITS];  // per unit, GL_TEXTURE_2D target

    // Shader
    uint32_t current_program;
    // Uniform cache: program_id -> {location -> value}
    // Use a simple array for v1 (max 256 uniforms per program)

    // Pipeline state
    int32_t viewport[4];
    int32_t scissor[4];
    bool depth_test_enabled;
    bool depth_write_enabled;
    uint32_t depth_func;
    bool blend_enabled;
    uint32_t blend_src, blend_dst;
    bool cull_enabled;
    uint32_t cull_mode;
    uint32_t front_face;
    bool scissor_test_enabled;
} GlaShadowState;
```

Functions: `gla_shadow_init()`, `gla_shadow_bind_texture()`, `gla_shadow_use_program()`, etc. One function per GL state-setting call we intercept. `gla_shadow_snapshot()` returns the current state as a serializable struct.

- [ ] **Step 4: Run tests to verify they pass**

- [ ] **Step 5: Commit**

```bash
git add src/shims/gl/shadow_state.{h,c} tests/shims/test_shadow_state.c
git commit -m "feat: GL shadow state tracker for stateless capture"
```

---

## Task 6: GL Function Wrappers + LD_PRELOAD Entry

**Files:**
- Create: `src/shims/gl/gl_shim.c`
- Create: `src/shims/gl/gl_wrappers.h`
- Create: `src/shims/gl/gl_wrappers.c`

- [ ] **Step 1: Implement gl_shim.c — LD_PRELOAD entry point**

Uses `dlsym(RTLD_NEXT, "glFunctionName")` to resolve real GL functions. Stores originals in a dispatch table. Intercepts `glXGetProcAddress`/`glXGetProcAddressARB` to return our wrappers for dynamically-loaded functions.

```c
// src/shims/gl/gl_shim.c
#define _GNU_SOURCE
#include <dlfcn.h>
#include "gl_wrappers.h"

// Dispatch table of real GL functions
GlaRealGlFuncs gla_real_gl;
static int initialized = 0;

static void gla_init(void) {
    if (initialized) return;
    initialized = 1;
    // Resolve all real GL functions
    gla_real_gl.glDrawArrays = dlsym(RTLD_NEXT, "glDrawArrays");
    gla_real_gl.glDrawElements = dlsym(RTLD_NEXT, "glDrawElements");
    gla_real_gl.glBindTexture = dlsym(RTLD_NEXT, "glBindTexture");
    gla_real_gl.glUseProgram = dlsym(RTLD_NEXT, "glUseProgram");
    // ... all intercepted functions
    gla_real_gl.glXSwapBuffers = dlsym(RTLD_NEXT, "glXSwapBuffers");

    gla_shadow_init();
    gla_ipc_connect();  // Connect to engine
}

// LD_PRELOAD constructor
__attribute__((constructor))
static void gla_preload_init(void) {
    gla_init();
}
```

- [ ] **Step 2: Implement gl_wrappers.c — v1 subset of GL functions**

For v1, intercept these functions (covers the critical path for draw calls + state):

**Draw calls:** `glDrawArrays`, `glDrawElements`, `glDrawArraysInstanced`, `glDrawElementsInstanced`
**Shaders:** `glUseProgram`, `glUniform1f/2f/3f/4f`, `glUniform1i`, `glUniformMatrix4fv`, `glUniformMatrix3fv`
**Textures:** `glActiveTexture`, `glBindTexture`
**State:** `glEnable`, `glDisable`, `glDepthFunc`, `glDepthMask`, `glBlendFunc`, `glCullFace`, `glFrontFace`, `glViewport`, `glScissor`
**Buffers:** `glBindBuffer`, `glBindVertexArray`
**Framebuffer:** `glBindFramebuffer`
**Frame boundary:** `glXSwapBuffers`, `eglSwapBuffers`

Each wrapper: calls shadow state tracker, calls real function, logs call for frame capture.

```c
// Example wrapper
void glDrawArrays(GLenum mode, GLint first, GLsizei count) {
    gla_init();
    gla_real_gl.glDrawArrays(mode, first, count);
    gla_frame_record_draw(mode, first, count, 0, 1);  // record for capture
}

void glBindTexture(GLenum target, GLuint texture) {
    gla_init();
    gla_shadow_bind_texture(target, texture);
    gla_real_gl.glBindTexture(target, texture);
}

void glXSwapBuffers(Display *dpy, GLXDrawable drawable) {
    gla_init();
    gla_frame_on_swap();  // trigger frame capture
    gla_real_gl.glXSwapBuffers(dpy, drawable);
}
```

- [ ] **Step 3: Verify shim compiles as shared library**

Run: `bazel build //src/shims/gl:gla_gl`
Expected: `libgla_gl.so` produced

- [ ] **Step 4: Commit**

```bash
git add src/shims/gl/gl_shim.c src/shims/gl/gl_wrappers.{h,c}
git commit -m "feat: GL function wrappers with LD_PRELOAD dispatch"
```

---

## Task 7: Frame Capture + Shim IPC Client

**Files:**
- Create: `src/shims/gl/frame_capture.h`
- Create: `src/shims/gl/frame_capture.c`
- Create: `src/shims/gl/ipc_client.h`
- Create: `src/shims/gl/ipc_client.c`

- [ ] **Step 1: Implement ipc_client — shim's connection to engine**

Opens the shared memory ring buffer (name from `GLA_SHM_NAME` env var). Connects to Unix socket (path from `GLA_SOCKET_PATH` env var). Sends handshake. Receives control commands.

```c
// src/shims/gl/ipc_client.h
int gla_ipc_connect(void);       // connect to engine, returns 0 on success
int gla_ipc_is_connected(void);
void* gla_ipc_claim_slot(uint32_t* slot_index);  // claim shm write slot
void gla_ipc_commit_slot(uint32_t slot_index, uint64_t size);
void gla_ipc_send_frame_ready(uint64_t frame_id, uint32_t slot_index);
int gla_ipc_should_pause(void);  // check for pause command
void gla_ipc_wait_resume(void);  // block until resume
```

- [ ] **Step 2: Implement frame_capture — snapshot at frame boundary**

On `glXSwapBuffers`:
1. If not connected to engine, skip (transparent passthrough)
2. Claim a shm write slot
3. Copy shadow state into FlatBuffer metadata
4. Issue `glReadPixels` for framebuffer color (via PBO if available, synchronous fallback for v1)
5. Copy framebuffer pixels into shm slot
6. Commit slot, send frame-ready message via socket
7. If engine requests pause, block on condition variable

```c
void gla_frame_on_swap(void) {
    if (!gla_ipc_is_connected()) return;

    uint32_t slot_index;
    void* slot = gla_ipc_claim_slot(&slot_index);
    if (!slot) return;  // no free slot, drop frame

    // Write framebuffer to shm
    uint64_t offset = 0;
    offset += gla_frame_read_framebuffer(slot, offset);

    // Serialize draw call metadata as FlatBuffer
    gla_ipc_commit_slot(slot_index, offset);
    gla_ipc_send_frame_ready(gla_frame_counter++, slot_index);

    if (gla_ipc_should_pause()) {
        gla_ipc_wait_resume();
    }
}
```

- [ ] **Step 3: Verify shim builds with IPC**

Run: `bazel build //src/shims/gl:gla_gl`
Expected: Builds successfully

- [ ] **Step 4: Commit**

```bash
git add src/shims/gl/frame_capture.{h,c} src/shims/gl/ipc_client.{h,c}
git commit -m "feat: frame capture at swap boundary with shm + socket IPC"
```

---

## Task 8: Frame Store (Core Engine)

**Files:**
- Create: `src/core/store/raw_frame.h`
- Create: `src/core/store/frame_store.h`
- Create: `src/core/store/frame_store.cpp`
- Create: `tests/core/test_frame_store.cpp`

- [ ] **Step 1: Write failing tests**

Test cases:
1. Store a frame, retrieve by frame_id
2. Store 60+ frames, oldest evicted (ring buffer)
3. Get latest frame
4. Get frame that doesn't exist returns nullptr
5. Frame data contains draw calls + framebuffer

- [ ] **Step 2: Run tests to verify they fail**

- [ ] **Step 3: Implement RawFrame + FrameStore**

`raw_frame.h`: POD struct containing deserialized frame data (frame_id, draw calls vector, framebuffer pixel data owned in a `std::vector<uint8_t>`).

`FrameStore`: circular buffer of `RawFrame` with configurable capacity (default 60). Methods: `store(RawFrame)`, `get(frame_id) -> const RawFrame*`, `latest() -> const RawFrame*`, `frame_count()`.

- [ ] **Step 4: Run tests to verify they pass**

- [ ] **Step 5: Commit**

```bash
git add src/core/store/ tests/core/test_frame_store.cpp
git commit -m "feat: frame store with ring buffer eviction"
```

---

## Task 9: Engine Main Loop + Capture Ingestion

**Files:**
- Modify: `src/core/engine.h`
- Modify: `src/core/engine.cpp`

- [ ] **Step 1: Implement Engine class**

```cpp
class Engine {
public:
    Engine(const std::string& socket_path, const std::string& shm_name,
           uint32_t shm_slots, size_t slot_size);
    void run();       // blocking main loop
    void stop();

    FrameStore& frame_store();
    // Control
    void request_pause();
    void request_resume();
    void request_step(uint32_t count);

private:
    void accept_connections();
    void handle_frame_ready(uint64_t frame_id, uint32_t slot_index);
    void ingest_frame(const void* shm_data, size_t size, /* flatbuf metadata */);

    std::unique_ptr<ShmRingBuffer> shm_;
    std::unique_ptr<ControlSocket> socket_;
    FrameStore store_;
    std::atomic<bool> running_;
    std::atomic<bool> paused_;
};
```

- [ ] **Step 2: Implement run loop**

`poll()` on the control socket. On FRAME_READY message: read slot from shm, deserialize FlatBuffer metadata, copy bulk data into a `RawFrame`, store in `FrameStore`, release shm slot. Handle pause/resume/step commands.

- [ ] **Step 3: Write integration test: mock shim → engine → frame stored**

Test: spawn engine in a thread, connect as a mock client (write test data to shm, send frame-ready), verify engine's `FrameStore` contains the frame.

- [ ] **Step 4: Run integration test**

- [ ] **Step 5: Commit**

```bash
git add src/core/engine.{h,cpp}
git commit -m "feat: engine main loop with capture ingestion"
```

---

## Task 10: Normalizer (Raw GL → Normalized DrawCalls)

**Files:**
- Create: `src/core/normalize/normalized_types.h`
- Create: `src/core/normalize/normalizer.h`
- Create: `src/core/normalize/normalizer.cpp`
- Create: `tests/core/test_normalizer.cpp`

- [ ] **Step 1: Define normalized types**

```cpp
// src/core/normalize/normalized_types.h
namespace gla {

struct NormalizedPipelineState {
    int32_t viewport[4];
    int32_t scissor[4];
    bool scissor_enabled;
    bool depth_test, depth_write;
    uint32_t depth_func;
    bool blend_enabled;
    uint32_t blend_src, blend_dst;
    bool cull_enabled;
    uint32_t cull_mode, front_face;
};

struct ShaderParameter {
    std::string name;
    ParamType type;
    std::vector<uint8_t> data;
};

struct NormalizedDrawCall {
    uint32_t id;
    PrimitiveType primitive;
    uint32_t vertex_count, index_count, instance_count;
    uint32_t shader_id;
    std::vector<ShaderParameter> params;
    std::vector<TextureBinding> textures;
    NormalizedPipelineState pipeline;
    // Vertex data references (offsets into frame's bulk data)
    size_t vertex_data_offset, vertex_data_size;
    size_t index_data_offset, index_data_size;
};

struct RenderPass {
    uint32_t target_framebuffer;  // 0 = default
    std::vector<NormalizedDrawCall> draw_calls;
};

struct NormalizedFrame {
    uint64_t frame_id;
    double timestamp;
    // Draw calls grouped under render passes (v1: single implicit pass)
    std::vector<RenderPass> render_passes;
    // Convenience: flat list of all draw calls across passes
    const std::vector<NormalizedDrawCall>& all_draw_calls() const;
    // Framebuffer
    uint32_t fb_width, fb_height;
    std::vector<uint8_t> fb_color;    // RGBA
    std::vector<float> fb_depth;      // float32
    std::vector<uint8_t> fb_stencil;  // uint8
};

}  // namespace gla
```

- [ ] **Step 2: Write failing tests**

Test: create a RawFrame with mock GL draw calls, normalize it, verify NormalizedFrame has correct draw call count, pipeline state, shader params.

- [ ] **Step 3: Implement Normalizer**

`Normalizer::normalize(const RawFrame&) -> NormalizedFrame`: iterate raw draw calls, map GL enum values to normalized types, extract shader params, build NormalizedDrawCall list. For v1, the mapping is mostly 1:1 since we only support GL.

- [ ] **Step 4: Run tests to verify they pass**

- [ ] **Step 5: Commit**

```bash
git add src/core/normalize/ tests/core/test_normalizer.cpp
git commit -m "feat: normalizer converts raw GL captures to API-agnostic format"
```

---

## Task 11: Query Engine

**Files:**
- Create: `src/core/query/query_engine.h`
- Create: `src/core/query/query_engine.cpp`
- Create: `tests/core/test_query_engine.cpp`

- [ ] **Step 1: Write failing tests**

Test cases:
1. `frame_overview(frame_id)` → returns draw call count, framebuffer size
2. `list_draw_calls(frame_id, limit, offset)` → paginated list of draw call summaries
3. `get_draw_call(frame_id, dc_id)` → full draw call details
4. `get_pixel(frame_id, x, y)` → RGBA color + depth value
5. `get_draw_call(frame_id, invalid_id)` → returns error/nullopt
6. `get_pixel(frame_id, out_of_bounds_x, y)` → returns error/nullopt

- [ ] **Step 2: Run tests to verify they fail**

- [ ] **Step 3: Implement QueryEngine**

```cpp
class QueryEngine {
public:
    QueryEngine(FrameStore& store, Normalizer& normalizer);

    struct FrameOverview {
        uint64_t frame_id;
        uint32_t draw_call_count;
        uint32_t fb_width, fb_height;
    };

    struct PixelResult {
        uint8_t r, g, b, a;
        float depth;
        uint8_t stencil;
    };

    std::optional<FrameOverview> frame_overview(uint64_t frame_id);
    std::vector<NormalizedDrawCall> list_draw_calls(
        uint64_t frame_id, uint32_t limit, uint32_t offset);
    std::optional<NormalizedDrawCall> get_draw_call(
        uint64_t frame_id, uint32_t dc_id);
    std::optional<PixelResult> get_pixel(
        uint64_t frame_id, uint32_t x, uint32_t y);

private:
    FrameStore& store_;
    Normalizer& normalizer_;
    // Cache: frame_id -> NormalizedFrame (bounded to store capacity,
    // evict entries whose frame_id is no longer in the FrameStore)
    std::unordered_map<uint64_t, NormalizedFrame> cache_;

    // Deferred normalization: called on first query for a frame.
    // Looks up RawFrame in store_, normalizes via normalizer_, caches result.
    // Returns nullptr if frame_id not in store (evicted or invalid).
    const NormalizedFrame* get_normalized(uint64_t frame_id);
};
```

`get_pixel`: index into framebuffer color array at `(y * width + x) * 4`. Depth at `y * width + x`.

- [ ] **Step 4: Run tests to verify they pass**

- [ ] **Step 5: Commit**

```bash
git add src/core/query/ tests/core/test_query_engine.cpp
git commit -m "feat: query engine with frame overview, draw call list, pixel lookup"
```

---

## Task 12: pybind11 Bindings

**Files:**
- Modify: `src/bindings/CMakeLists.txt`
- Modify: `src/bindings/py_gla.cpp`

- [ ] **Step 1: Write pybind11 module**

Expose: `Engine`, `QueryEngine`, `FrameOverview`, `NormalizedDrawCall`, `PixelResult`, `ShaderParameter`, `NormalizedPipelineState`.

```cpp
// src/bindings/py_gla.cpp
#include <pybind11/pybind11.h>
#include <pybind11/stl.h>
#include "engine.h"
#include "query/query_engine.h"

namespace py = pybind11;

PYBIND11_MODULE(_gla_core, m) {
    py::class_<gla::Engine>(m, "Engine")
        .def(py::init<const std::string&, const std::string&, uint32_t, size_t>())
        .def("run", &gla::Engine::run)
        .def("stop", &gla::Engine::stop)
        .def("request_pause", &gla::Engine::request_pause)
        .def("request_resume", &gla::Engine::request_resume)
        .def("request_step", &gla::Engine::request_step);

    py::class_<gla::QueryEngine::FrameOverview>(m, "FrameOverview")
        .def_readonly("frame_id", &gla::QueryEngine::FrameOverview::frame_id)
        .def_readonly("draw_call_count", &gla::QueryEngine::FrameOverview::draw_call_count)
        .def_readonly("fb_width", &gla::QueryEngine::FrameOverview::fb_width)
        .def_readonly("fb_height", &gla::QueryEngine::FrameOverview::fb_height);

    py::class_<gla::QueryEngine::PixelResult>(m, "PixelResult")
        .def_readonly("r", &gla::QueryEngine::PixelResult::r)
        .def_readonly("g", &gla::QueryEngine::PixelResult::g)
        .def_readonly("b", &gla::QueryEngine::PixelResult::b)
        .def_readonly("a", &gla::QueryEngine::PixelResult::a)
        .def_readonly("depth", &gla::QueryEngine::PixelResult::depth);

    // ... expose NormalizedDrawCall, ShaderParameter, etc.

    py::class_<gla::QueryEngine>(m, "QueryEngine")
        .def("frame_overview", &gla::QueryEngine::frame_overview)
        .def("list_draw_calls", &gla::QueryEngine::list_draw_calls)
        .def("get_draw_call", &gla::QueryEngine::get_draw_call)
        .def("get_pixel", &gla::QueryEngine::get_pixel);
}
```

- [ ] **Step 2: Update bindings CMakeLists.txt**

```cmake
# src/bindings/CMakeLists.txt
pybind11_add_module(_gla_core py_gla.cpp)
target_link_libraries(_gla_core PRIVATE gla_core)
```

- [ ] **Step 3: Verify Python module builds and imports**

Run: `bazel build //src/bindings:_gla_core && python -c "import sys; sys.path.insert(0, 'bazel-bin/src/bindings'); import _gla_core; print('OK')"`
Expected: "OK"

- [ ] **Step 4: Commit**

```bash
git add src/bindings/
git commit -m "feat: pybind11 bindings for engine + query engine"
```

---

## Task 13: FastAPI REST Endpoints

**Files:**
- Create: `src/python/gla/core.py`
- Create: `src/python/gla/api/__init__.py`
- Create: `src/python/gla/api/app.py`
- Create: `src/python/gla/api/routes_frames.py`
- Create: `src/python/gla/api/routes_drawcalls.py`
- Create: `src/python/gla/api/routes_pixel.py`
- Create: `src/python/gla/api/routes_control.py`
- Create: `tests/python/conftest.py`
- Create: `tests/python/test_api_frames.py`
- Create: `tests/python/test_api_drawcalls.py`
- Create: `tests/python/test_api_pixel.py`
- Create: `tests/python/test_api_control.py`

- [ ] **Step 1: Write failing API tests**

Use `httpx.AsyncClient` with FastAPI's `TestClient`. Mock the C++ engine/query engine at the Python layer for unit testing.

```python
# tests/python/conftest.py
import pytest
from unittest.mock import MagicMock
from gla.api.app import create_app

@pytest.fixture
def mock_query_engine():
    engine = MagicMock()
    engine.frame_overview.return_value = MagicMock(
        frame_id=1, draw_call_count=42, fb_width=800, fb_height=600
    )
    engine.get_pixel.return_value = MagicMock(r=255, g=0, b=0, a=255, depth=0.5)
    return engine

@pytest.fixture
def client(mock_query_engine):
    app = create_app(mock_query_engine, auth_token="test-token")
    from fastapi.testclient import TestClient
    return TestClient(app)
```

```python
# tests/python/test_api_frames.py
def test_frame_overview(client):
    resp = client.get("/api/v1/frames/1/overview",
                      headers={"Authorization": "Bearer test-token"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["frame_id"] == 1
    assert data["draw_call_count"] == 42

def test_frame_overview_no_auth(client):
    resp = client.get("/api/v1/frames/1/overview")
    assert resp.status_code == 401

def test_frame_not_found(client, mock_query_engine):
    mock_query_engine.frame_overview.return_value = None
    resp = client.get("/api/v1/frames/999/overview",
                      headers={"Authorization": "Bearer test-token"})
    assert resp.status_code == 404
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/python/ -v`
Expected: FAIL (modules don't exist)

- [ ] **Step 3: Implement app.py with auth middleware**

```python
# src/python/gla/api/app.py
from fastapi import FastAPI, Request, HTTPException
from .routes_frames import router as frames_router
from .routes_drawcalls import router as drawcalls_router
from .routes_pixel import router as pixel_router
from .routes_control import router as control_router

def create_app(query_engine, auth_token: str) -> FastAPI:
    """Create the OpenGPA REST API. MUST be served on 127.0.0.1 only (NFR-5.1)."""
    app = FastAPI(title="OpenGPA", version="0.1.0")
    app.state.query_engine = query_engine
    app.state.auth_token = auth_token

    @app.middleware("http")
    async def check_auth(request: Request, call_next):
        token = request.headers.get("Authorization", "").removeprefix("Bearer ")
        if token != request.app.state.auth_token:
            raise HTTPException(status_code=401, detail="Invalid token")
        return await call_next(request)

    app.include_router(frames_router, prefix="/api/v1")
    app.include_router(drawcalls_router, prefix="/api/v1")
    app.include_router(pixel_router, prefix="/api/v1")
    app.include_router(control_router, prefix="/api/v1")
    return app
```

- [ ] **Step 4: Implement routes_frames.py**

```python
# src/python/gla/api/routes_frames.py
from fastapi import APIRouter, Request, HTTPException

router = APIRouter()

@router.get("/frames/current")
async def get_current_frame(request: Request):
    qe = request.app.state.query_engine
    overview = qe.frame_overview(0)  # 0 = latest
    if not overview:
        raise HTTPException(404, "No frames captured")
    return _format_overview(overview)

@router.get("/frames/{frame_id}/overview")
async def get_frame_overview(frame_id: int, request: Request):
    qe = request.app.state.query_engine
    overview = qe.frame_overview(frame_id)
    if not overview:
        raise HTTPException(404, f"Frame {frame_id} not found")
    return _format_overview(overview)

def _format_overview(o):
    return {
        "frame_id": o.frame_id,
        "draw_call_count": o.draw_call_count,
        "framebuffer_width": o.fb_width,
        "framebuffer_height": o.fb_height,
    }
```

- [ ] **Step 5: Implement remaining route files**

`routes_frames.py` (additional):
- `GET /frames/{frame_id}/framebuffer` — read color buffer, encode as base64 PNG, return in JSON
- `GET /frames/{frame_id}/framebuffer/depth` — read depth buffer, normalize to 0-255, encode as base64 PNG

`routes_drawcalls.py`:
- `GET /frames/{frame_id}/drawcalls` — paginated list with `?limit=50&offset=0`
- `GET /frames/{frame_id}/drawcalls/{dc_id}` — full draw call details
- `GET /frames/{frame_id}/drawcalls/{dc_id}/vertices` — vertex attribute data
- `GET /frames/{frame_id}/drawcalls/{dc_id}/textures` — bound texture metadata
- `GET /frames/{frame_id}/drawcalls/{dc_id}/shader` — shader program info + parameter values

`routes_pixel.py`: `/frames/{frame_id}/pixel/{x}/{y}` — returns `{r, g, b, a, depth, stencil}`
`routes_control.py`: `/control/pause`, `/control/resume`, `/control/step`, `/control/status`

- [ ] **Step 6: Run tests to verify they pass**

Run: `pytest tests/python/ -v`
Expected: All PASS

- [ ] **Step 7: Commit**

```bash
git add src/python/ tests/python/
git commit -m "feat: FastAPI REST API with auth, frame/drawcall/pixel/control endpoints"
```

---

## Task 14: Python Launcher (Engine + API in One Process)

**Files:**
- Create: `src/python/gla/launcher.py`

The C++ engine runs as a library (via pybind11), not a separate binary. The Python process is the main process: it creates the C++ `Engine` (which starts the IPC server), creates the `QueryEngine`, and runs FastAPI — all in-process. This eliminates the need for a separate C++ binary for normal use.

- [ ] **Step 1: Implement launcher.py**

```python
# src/python/gla/launcher.py
import argparse, threading, secrets, uvicorn
from _gla_core import Engine, QueryEngine
from gla.api.app import create_app

def main():
    parser = argparse.ArgumentParser(description="OpenGPA Engine + REST API")
    parser.add_argument("--socket", default="/tmp/gla.sock")
    parser.add_argument("--shm", default="/gla_capture")
    parser.add_argument("--shm-slots", type=int, default=4)
    parser.add_argument("--slot-size", type=int, default=64 * 1024 * 1024)
    parser.add_argument("--port", type=int, default=18080)
    parser.add_argument("--token", default=None)
    args = parser.parse_args()

    token = args.token or secrets.token_urlsafe(32)
    print(f"GLA_SOCKET_PATH={args.socket}")
    print(f"GLA_SHM_NAME={args.shm}")
    print(f"GLA_AUTH_TOKEN={token}")

    engine = Engine(args.socket, args.shm, args.shm_slots, args.slot_size)
    engine_thread = threading.Thread(target=engine.run, daemon=True)
    engine_thread.start()

    qe = QueryEngine(engine)
    app = create_app(qe, auth_token=token)
    uvicorn.run(app, host="127.0.0.1", port=args.port)

if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Verify launcher starts**

Run: `python -m gla.launcher --port 18080`
Expected: Prints socket/shm/token info, starts listening on 127.0.0.1:18080

- [ ] **Step 3: Commit**

```bash
git add src/python/gla/launcher.py
git commit -m "feat: Python launcher runs engine + REST API in one process"
```

---

## Task 15: Mini GL Test App

**Files:**
- Create: `tests/integration/mini_gl_app.c`

- [ ] **Step 1: Write minimal GL application**

A standalone GL app that:
- Opens a 400x300 window via GLX
- Clears to blue
- Draws a red triangle with a simple shader (hardcoded vertex/fragment)
- Calls `glXSwapBuffers`
- Runs for 5 frames then exits

This is the test fixture for integration testing. It must be simple enough that we know exactly what the captured state should contain: 1 draw call (3 vertices, triangles, red color uniform), blue clear color, specific viewport.

- [ ] **Step 2: Verify it compiles and runs**

Run: `bazel build //tests/integration:mini_gl_app && bazel-bin/tests/integration/mini_gl_app`

Note: `tests/integration/BUILD.bazel` needs:
```starlark
cc_binary(
    name = "mini_gl_app",
    srcs = ["mini_gl_app.c"],
    linkopts = ["-lGL", "-lX11"],
)
```
Expected: Window flashes briefly, exits cleanly

- [ ] **Step 3: Commit**

```bash
git add tests/integration/mini_gl_app.c
git commit -m "test: minimal GL app for integration testing"
```

---

## Task 16: End-to-End Integration Test

**Files:**
- Create: `tests/integration/test_end_to_end.py`

- [ ] **Step 1: Write end-to-end test**

```python
# tests/integration/test_end_to_end.py
"""
End-to-end: mini_gl_app -> LD_PRELOAD shim -> engine -> REST API -> query

Requires: built libgla_gl.so, mini_gl_app binary, gla Python package.
Run with: pytest tests/integration/ -v --timeout=30
"""
import subprocess, time, os, signal, requests, sys

SHIM_LIB = "bazel-bin/src/shims/gl/libgla_gl.so"
GL_APP = "bazel-bin/tests/integration/mini_gl_app"
SOCKET_PATH = "/tmp/gla_test.sock"
SHM_NAME = "/gla_test_e2e"
API_PORT = 18090
TOKEN = "test-e2e-token"

def test_full_pipeline():
    # 1. Start engine + API via Python launcher
    launcher = subprocess.Popen([
        sys.executable, "-m", "gla.launcher",
        "--socket", SOCKET_PATH,
        "--shm", SHM_NAME,
        "--port", str(API_PORT),
        "--token", TOKEN,
    ])
    time.sleep(2)  # let engine + API start

    try:
        # 2. Run GL app with shim
        env = os.environ.copy()
        env["LD_PRELOAD"] = os.path.abspath(SHIM_LIB)
        env["GLA_SOCKET_PATH"] = SOCKET_PATH
        env["GLA_SHM_NAME"] = SHM_NAME
        app = subprocess.run([GL_APP], env=env, timeout=10)
        assert app.returncode == 0
        time.sleep(0.5)  # let engine process frames

        # 3. Query via REST API
        headers = {"Authorization": f"Bearer {TOKEN}"}
        base = f"http://127.0.0.1:{API_PORT}/api/v1"

        # Frame overview
        r = requests.get(f"{base}/frames/current/overview", headers=headers)
        assert r.status_code == 200
        overview = r.json()
        assert overview["draw_call_count"] >= 1
        assert overview["framebuffer_width"] == 400
        assert overview["framebuffer_height"] == 300

        frame_id = overview["frame_id"]

        # Draw call details
        r = requests.get(f"{base}/frames/{frame_id}/drawcalls", headers=headers)
        assert r.status_code == 200
        dcs = r.json()
        assert len(dcs["draw_calls"]) >= 1

        # Pixel query (center of screen — should be red triangle or blue bg)
        r = requests.get(f"{base}/frames/{frame_id}/pixel/200/150", headers=headers)
        assert r.status_code == 200
        pixel = r.json()
        assert "r" in pixel and "g" in pixel and "b" in pixel

        # Framebuffer as PNG
        r = requests.get(f"{base}/frames/{frame_id}/framebuffer", headers=headers)
        assert r.status_code == 200
        assert "image" in r.json()  # base64 PNG

    finally:
        # Cleanup
        launcher.send_signal(signal.SIGTERM)
        launcher.wait(timeout=5)
```

- [ ] **Step 2: Run the integration test**

Run: `pytest tests/integration/test_end_to_end.py -v --timeout=30`
Expected: PASS (all assertions hold)

- [ ] **Step 3: Commit**

```bash
git add tests/integration/test_end_to_end.py
git commit -m "test: end-to-end pipeline integration test"
```

---

## Post-M1/M2 Next Steps

After completing this plan, the following milestones should be planned separately:

- **M3: Semantic reconstruction** — matrix classification, camera extraction, object grouping, AABB. Adds `query_scene` endpoints. Plan depends on M2 working.
- **M4: MCP server** — thin Python wrapper over query functions. Small, can be combined with M3 plan.
- **M5: Vulkan layer** — independent shim, same IPC protocol. Separate plan.
- **M6: WebGL shim** — TypeScript browser extension + Node.js bridge. Separate plan.
- **M7: Advanced queries** — frame diff, pixel attribution (draw call ID buffer), spatial queries. Separate plan.
- **Eval suite** — the adversarial test scenarios from the spec (Category A-E). Should be its own plan after M1-M4 are working.
