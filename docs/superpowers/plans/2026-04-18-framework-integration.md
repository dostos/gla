# Framework Integration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Extend OpenGPA to debug high-level frameworks by intercepting GL debug markers, accepting framework metadata via HTTP POST, and providing object/pass/material/pixel-explanation queries.

**Architecture:** Three data layers — GL capture (existing), debug markers (free baseline from glPushDebugGroup), and metadata sidecar (framework plugins POST scene graph via HTTP). A correlation engine joins all three via draw call IDs. New REST endpoints and MCP tools expose the joined data.

**Tech Stack:** C (shim debug marker interception), C++ (normalizer debug group tree), Python (metadata store, correlation engine, REST endpoints, MCP tools), JavaScript (Three.js plugin)

**Spec:** `docs/superpowers/specs/2026-04-18-framework-integration-design.md`

---

## File Structure

```
src/
  shims/gl/
    shadow_state.h          # MODIFY: add debug group stack
    shadow_state.c          # MODIFY: add push/pop debug group functions
    gl_wrappers.h           # MODIFY: add glPushDebugGroup/glPopDebugGroup to dispatch table
    gl_wrappers.c           # MODIFY: add wrapper functions + resolve_wrapper entries
    frame_capture.c         # MODIFY: add debug_group_path to DrawCallSnapshot + serialization
  core/
    store/raw_frame.h       # MODIFY: add debug_group_path to RawDrawCall
    normalize/
      normalized_types.h    # MODIFY: add debug_group_path to NormalizedDrawCall, add DebugGroupNode
    engine.cpp              # MODIFY: parse debug_group_path from shm binary
  bindings/py_gla.cpp       # MODIFY: expose debug_group_path
  python/gla/
    framework/
      __init__.py           # CREATE: exports
      metadata_store.py     # CREATE: per-frame metadata storage
      debug_groups.py       # CREATE: DebugGroupNode tree builder
      correlation.py        # CREATE: join GL capture + markers + metadata
      query_engine.py       # CREATE: FrameworkQueryEngine
      types.py              # CREATE: ObjectInfo, RenderPassInfo, MaterialInfo, PixelExplanation
    api/
      routes_metadata.py    # CREATE: POST /frames/{id}/metadata
      routes_objects.py     # CREATE: GET /frames/{id}/objects, /objects/{name}, /objects/at/{x}/{y}
      routes_passes.py      # CREATE: GET /frames/{id}/passes, /passes/{name}
      routes_explain.py     # CREATE: GET /frames/{id}/explain/{x}/{y}
      app.py                # MODIFY: register new routers
    mcp/server.py           # MODIFY: add 4 new tools
    backends/base.py        # MODIFY: add metadata + framework query methods to FrameProvider
    backends/native.py      # MODIFY: implement new methods
  shims/webgl/
    extension/
      gla-threejs-plugin.js # CREATE: Three.js scene graph capture plugin
tests/
  shims/
    test_shadow_state.c     # MODIFY: add debug group tests
  core/
    test_debug_groups.cpp   # CREATE: DebugGroupNode tree building
  python/
    test_metadata_store.py  # CREATE: metadata storage tests
    test_correlation.py     # CREATE: correlation engine tests
    test_framework_query.py # CREATE: FrameworkQueryEngine tests
    test_api_metadata.py    # CREATE: metadata POST endpoint tests
    test_api_objects.py     # CREATE: object query endpoint tests
    test_api_explain.py     # CREATE: explain_pixel endpoint tests
```

---

## Task 1: Debug Group Stack in Shadow State

**Files:**
- Modify: `src/shims/gl/shadow_state.h`
- Modify: `src/shims/gl/shadow_state.c`
- Modify: `tests/shims/test_shadow_state.c`

- [ ] **Step 1: Add debug group data to shadow state header**

Add to `GlaShadowState` in `shadow_state.h`:
```c
#define GLA_MAX_DEBUG_GROUP_DEPTH 32
#define GLA_MAX_DEBUG_GROUP_NAME 128

typedef struct {
    char name[GLA_MAX_DEBUG_GROUP_NAME];
    uint32_t id;
} GlaDebugGroupEntry;

// Add to GlaShadowState struct:
GlaDebugGroupEntry debug_group_stack[GLA_MAX_DEBUG_GROUP_DEPTH];
uint32_t debug_group_depth;
```

Add function declarations:
```c
void gla_shadow_push_debug_group(GlaShadowState* state, uint32_t id, const char* name);
void gla_shadow_pop_debug_group(GlaShadowState* state);
// Returns current debug group path as "Parent/Child/Grandchild", writes to buf
int gla_shadow_get_debug_group_path(const GlaShadowState* state, char* buf, size_t buf_size);
```

- [ ] **Step 2: Write failing tests**

Add to `tests/shims/test_shadow_state.c`:
```c
void test_debug_group_push_pop(void) {
    GlaShadowState s;
    gla_shadow_init(&s);
    assert(s.debug_group_depth == 0);
    
    gla_shadow_push_debug_group(&s, 1, "Shadow Pass");
    assert(s.debug_group_depth == 1);
    assert(strcmp(s.debug_group_stack[0].name, "Shadow Pass") == 0);
    
    gla_shadow_push_debug_group(&s, 2, "Player");
    assert(s.debug_group_depth == 2);
    
    gla_shadow_pop_debug_group(&s);
    assert(s.debug_group_depth == 1);
    
    gla_shadow_pop_debug_group(&s);
    assert(s.debug_group_depth == 0);
    printf("PASS test_debug_group_push_pop\n");
}

void test_debug_group_path(void) {
    GlaShadowState s;
    gla_shadow_init(&s);
    char buf[512];
    
    gla_shadow_get_debug_group_path(&s, buf, sizeof(buf));
    assert(strcmp(buf, "") == 0);
    
    gla_shadow_push_debug_group(&s, 1, "GBuffer");
    gla_shadow_push_debug_group(&s, 2, "Player Mesh");
    gla_shadow_get_debug_group_path(&s, buf, sizeof(buf));
    assert(strcmp(buf, "GBuffer/Player Mesh") == 0);
    
    printf("PASS test_debug_group_path\n");
}
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `bazel test //tests/shims:test_shadow_state`

- [ ] **Step 4: Implement shadow state functions**

In `shadow_state.c`:
```c
void gla_shadow_push_debug_group(GlaShadowState* state, uint32_t id, const char* name) {
    if (state->debug_group_depth >= GLA_MAX_DEBUG_GROUP_DEPTH) return;
    GlaDebugGroupEntry* e = &state->debug_group_stack[state->debug_group_depth];
    e->id = id;
    strncpy(e->name, name, GLA_MAX_DEBUG_GROUP_NAME - 1);
    e->name[GLA_MAX_DEBUG_GROUP_NAME - 1] = '\0';
    state->debug_group_depth++;
}

void gla_shadow_pop_debug_group(GlaShadowState* state) {
    if (state->debug_group_depth > 0) state->debug_group_depth--;
}

int gla_shadow_get_debug_group_path(const GlaShadowState* state, char* buf, size_t buf_size) {
    buf[0] = '\0';
    size_t pos = 0;
    for (uint32_t i = 0; i < state->debug_group_depth; i++) {
        if (i > 0 && pos < buf_size - 1) buf[pos++] = '/';
        size_t len = strlen(state->debug_group_stack[i].name);
        if (pos + len >= buf_size) break;
        memcpy(buf + pos, state->debug_group_stack[i].name, len);
        pos += len;
    }
    buf[pos] = '\0';
    return (int)pos;
}
```

- [ ] **Step 5: Run tests to verify they pass**
- [ ] **Step 6: Commit**

```
feat: debug group stack in GL shadow state
```

---

## Task 2: Intercept glPushDebugGroup/glPopDebugGroup

**Files:**
- Modify: `src/shims/gl/gl_wrappers.h`
- Modify: `src/shims/gl/gl_wrappers.c`

- [ ] **Step 1: Add to dispatch table in gl_wrappers.h**

Add to `GlaRealGlFuncs`:
```c
void (*glPushDebugGroup)(GLenum source, GLuint id, GLsizei length, const char* message);
void (*glPopDebugGroup)(void);
```

- [ ] **Step 2: Add wrapper functions in gl_wrappers.c**

```c
void glPushDebugGroup(GLenum source, GLuint id, GLsizei length, const char* message) {
    gla_init();
    if (gla_real_gl.glPushDebugGroup)
        gla_real_gl.glPushDebugGroup(source, id, length, message);
    gla_shadow_push_debug_group(&gla_shadow, id, message);
}

void glPopDebugGroup(void) {
    gla_init();
    if (gla_real_gl.glPopDebugGroup)
        gla_real_gl.glPopDebugGroup();
    gla_shadow_pop_debug_group(&gla_shadow);
}
```

Note: `glPushDebugGroup` may be NULL if the driver doesn't support `GL_KHR_debug`. The wrapper handles this gracefully — still records the marker in shadow state.

- [ ] **Step 3: Add to gla_wrappers_init()**

```c
gla_real_gl.glPushDebugGroup = dlsym(RTLD_NEXT, "glPushDebugGroup");
gla_real_gl.glPopDebugGroup  = dlsym(RTLD_NEXT, "glPopDebugGroup");
```

- [ ] **Step 4: Add to gla_resolve_wrapper()**

```c
if (strcmp(name, "glPushDebugGroup") == 0) return (__GLXextFuncPtr)glPushDebugGroup;
if (strcmp(name, "glPopDebugGroup") == 0)  return (__GLXextFuncPtr)glPopDebugGroup;
```

- [ ] **Step 5: Verify build**

Run: `bazel build //src/shims/gl:gla_gl`

- [ ] **Step 6: Commit**

```
feat: intercept glPushDebugGroup/glPopDebugGroup in GL shim
```

---

## Task 3: Serialize Debug Group Path with Draw Calls

**Files:**
- Modify: `src/shims/gl/frame_capture.c`
- Modify: `src/core/store/raw_frame.h`
- Modify: `src/core/normalize/normalized_types.h`
- Modify: `src/core/engine.cpp`
- Modify: `src/bindings/py_gla.cpp`

- [ ] **Step 1: Add debug_group_path to GlaDrawCallSnapshot**

In `frame_capture.c`, add to the `GlaDrawCallSnapshot` struct:
```c
char debug_group_path[512];
```

In `gla_frame_record_draw_call()`, after existing field copies:
```c
gla_shadow_get_debug_group_path(shadow, s->debug_group_path, sizeof(s->debug_group_path));
```

- [ ] **Step 2: Serialize debug_group_path in wire format**

In `serialise_draw_calls()`, after param data, add:
```c
// debug_group_path: uint16 length + chars (no null terminator)
uint16_t path_len = (uint16_t)strlen(s->debug_group_path);
memcpy(p, &path_len, 2); p += 2;
memcpy(p, s->debug_group_path, path_len); p += path_len;
```

- [ ] **Step 3: Add debug_group_path to RawDrawCall**

In `src/core/store/raw_frame.h`, add to `RawDrawCall`:
```cpp
std::string debug_group_path;
```

- [ ] **Step 4: Deserialize in engine.cpp ingest_frame()**

After existing param deserialization, add:
```cpp
uint16_t path_len = 0;
if (dc_ptr + 2 <= dc_end) {
    std::memcpy(&path_len, dc_ptr, 2); dc_ptr += 2;
    if (path_len > 0 && dc_ptr + path_len <= dc_end) {
        dc.debug_group_path.assign(reinterpret_cast<const char*>(dc_ptr), path_len);
        dc_ptr += path_len;
    }
}
```

- [ ] **Step 5: Add to NormalizedDrawCall**

In `normalized_types.h`, add to `NormalizedDrawCall`:
```cpp
std::string debug_group_path;
```

Copy in normalizer.cpp:
```cpp
dc.debug_group_path = rdc.debug_group_path;
```

- [ ] **Step 6: Expose in pybind11**

In `py_gla.cpp`, add to the NormalizedDrawCall binding:
```cpp
.def_readonly("debug_group_path", &gla::NormalizedDrawCall::debug_group_path)
```

- [ ] **Step 7: Verify full build and tests**

Run: `bazel build //... && bazel test //tests/core/... //tests/shims/...`

- [ ] **Step 8: Commit**

```
feat: serialize debug group path through capture pipeline
```

---

## Task 4: Metadata REST Endpoint + Storage

**Files:**
- Create: `src/python/gla/framework/__init__.py`
- Create: `src/python/gla/framework/types.py`
- Create: `src/python/gla/framework/metadata_store.py`
- Create: `src/python/gla/api/routes_metadata.py`
- Modify: `src/python/gla/api/app.py`
- Create: `tests/python/test_metadata_store.py`
- Create: `tests/python/test_api_metadata.py`

- [ ] **Step 1: Create framework types**

`src/python/gla/framework/types.py`:
```python
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

@dataclass
class FrameworkObject:
    name: str
    type: str = ""
    parent: str = ""
    draw_call_ids: List[int] = field(default_factory=list)
    transform: Dict[str, Any] = field(default_factory=dict)
    visible: bool = True
    properties: Dict[str, Any] = field(default_factory=dict)

@dataclass
class FrameworkMaterial:
    name: str
    shader: str = ""
    used_by: List[str] = field(default_factory=list)
    properties: Dict[str, Any] = field(default_factory=dict)
    textures: Dict[str, str] = field(default_factory=dict)

@dataclass
class FrameworkRenderPass:
    name: str
    draw_call_range: List[int] = field(default_factory=list)
    output: Any = None  # str or list
    input: List[str] = field(default_factory=list)

@dataclass
class FrameMetadata:
    framework: str = ""
    version: str = ""
    objects: List[FrameworkObject] = field(default_factory=list)
    materials: List[FrameworkMaterial] = field(default_factory=list)
    render_passes: List[FrameworkRenderPass] = field(default_factory=list)

@dataclass
class ObjectInfo:
    name: str
    type: str
    parent: str
    draw_call_ids: List[int]
    material: Optional[str]
    transform: Dict[str, Any]
    visible: bool
    properties: Dict[str, Any]

@dataclass
class RenderPassInfo:
    name: str
    draw_call_ids: List[int]
    input: List[str]
    output: Any

@dataclass
class MaterialInfo:
    name: str
    shader: str
    properties: Dict[str, Any]
    textures: Dict[str, str]
    used_by: List[str]

@dataclass
class PixelExplanation:
    pixel: Dict[str, Any]
    draw_call_id: Optional[int]
    debug_group: Optional[str]
    render_pass: Optional[str]
    object: Optional[Dict[str, Any]]
    material: Optional[Dict[str, Any]]
    shader_params: List[Dict[str, Any]]
    data_sources: List[str]  # which layers contributed
```

- [ ] **Step 2: Create MetadataStore**

`src/python/gla/framework/metadata_store.py`:
```python
from typing import Optional
from .types import FrameMetadata, FrameworkObject, FrameworkMaterial, FrameworkRenderPass

class MetadataStore:
    """Per-frame metadata storage. Framework plugins POST here."""
    
    def __init__(self, capacity: int = 120):
        self._store: dict[int, FrameMetadata] = {}
        self._capacity = capacity
    
    def store(self, frame_id: int, data: dict) -> None:
        """Store raw metadata dict, parse into FrameMetadata."""
        if len(self._store) >= self._capacity:
            oldest = min(self._store.keys())
            del self._store[oldest]
        
        md = FrameMetadata(
            framework=data.get("framework", ""),
            version=data.get("version", ""),
        )
        for obj in data.get("objects", []):
            md.objects.append(FrameworkObject(**{
                k: obj[k] for k in FrameworkObject.__dataclass_fields__ if k in obj
            }))
        for mat in data.get("materials", []):
            md.materials.append(FrameworkMaterial(**{
                k: mat[k] for k in FrameworkMaterial.__dataclass_fields__ if k in mat
            }))
        for rp in data.get("render_passes", []):
            md.render_passes.append(FrameworkRenderPass(**{
                k: rp[k] for k in FrameworkRenderPass.__dataclass_fields__ if k in rp
            }))
        self._store[frame_id] = md
    
    def get(self, frame_id: int) -> Optional[FrameMetadata]:
        return self._store.get(frame_id)
    
    def has(self, frame_id: int) -> bool:
        return frame_id in self._store
```

- [ ] **Step 3: Write MetadataStore tests**

`tests/python/test_metadata_store.py`:
- `test_store_and_get` — store metadata, retrieve by frame_id
- `test_not_found` — get non-existent frame_id returns None
- `test_capacity_eviction` — store more than capacity, oldest evicted
- `test_parse_objects` — verify FrameworkObject fields
- `test_parse_materials` — verify FrameworkMaterial fields
- `test_parse_render_passes` — verify FrameworkRenderPass fields
- `test_partial_data` — metadata with only objects, no materials/passes

- [ ] **Step 4: Run MetadataStore tests**

Run: `PYTHONPATH=src/python python -m pytest tests/python/test_metadata_store.py -v`

- [ ] **Step 5: Create metadata POST endpoint**

`src/python/gla/api/routes_metadata.py`:
```python
from fastapi import APIRouter, Request, HTTPException

router = APIRouter()

@router.post("/frames/{frame_id}/metadata")
async def post_metadata(frame_id: int, request: Request):
    body = await request.json()
    metadata_store = request.app.state.metadata_store
    metadata_store.store(frame_id, body)
    return {"status": "ok", "frame_id": frame_id}

@router.get("/frames/{frame_id}/metadata")
async def get_metadata(frame_id: int, request: Request):
    metadata_store = request.app.state.metadata_store
    md = metadata_store.get(frame_id)
    if not md:
        raise HTTPException(404, f"No metadata for frame {frame_id}")
    return {
        "framework": md.framework,
        "version": md.version,
        "object_count": len(md.objects),
        "material_count": len(md.materials),
        "render_pass_count": len(md.render_passes),
    }
```

- [ ] **Step 6: Register in app.py**

Add to `create_app()`:
```python
from gla.framework.metadata_store import MetadataStore
app.state.metadata_store = metadata_store or MetadataStore()

from .routes_metadata import router as metadata_router
app.include_router(metadata_router, prefix="/api/v1")
```

- [ ] **Step 7: Write API tests, verify all pass**

Run: `PYTHONPATH=src/python python -m pytest tests/python/ -v`

- [ ] **Step 8: Commit**

```
feat: metadata sidecar endpoint + storage for framework plugins
```

---

## Task 5: Debug Group Tree Builder

**Files:**
- Create: `src/python/gla/framework/debug_groups.py`
- Create: `tests/python/test_debug_groups.py`

- [ ] **Step 1: Implement DebugGroupNode and tree builder**

`src/python/gla/framework/debug_groups.py`:
```python
from dataclasses import dataclass, field
from typing import List, Optional

@dataclass
class DebugGroupNode:
    name: str
    children: List['DebugGroupNode'] = field(default_factory=list)
    draw_call_ids: List[int] = field(default_factory=list)

def build_debug_group_tree(draw_calls: list) -> DebugGroupNode:
    """Build a tree from draw calls with debug_group_path strings.
    
    Each draw call has a debug_group_path like "GBuffer/Player Mesh".
    Returns a root DebugGroupNode with the hierarchy.
    """
    root = DebugGroupNode(name="Frame")
    
    for dc in draw_calls:
        path = getattr(dc, 'debug_group_path', '') or ''
        if hasattr(dc, 'get'):  # dict-like
            path = dc.get('debug_group_path', '')
        
        if not path:
            root.draw_call_ids.append(dc.id if hasattr(dc, 'id') else dc.get('id', 0))
            continue
        
        parts = path.split('/')
        node = root
        for part in parts:
            child = next((c for c in node.children if c.name == part), None)
            if not child:
                child = DebugGroupNode(name=part)
                node.children.append(child)
            node = child
        
        dc_id = dc.id if hasattr(dc, 'id') else dc.get('id', 0)
        node.draw_call_ids.append(dc_id)
    
    return root
```

- [ ] **Step 2: Write tests**

Tests: empty frame, single draw no group, nested groups, multiple draws in same group, sibling groups.

- [ ] **Step 3: Run tests, verify pass**
- [ ] **Step 4: Commit**

```
feat: debug group tree builder from draw call paths
```

---

## Task 6: Correlation Engine + FrameworkQueryEngine

**Files:**
- Create: `src/python/gla/framework/correlation.py`
- Create: `src/python/gla/framework/query_engine.py`
- Create: `tests/python/test_correlation.py`
- Create: `tests/python/test_framework_query.py`

- [ ] **Step 1: Implement correlation logic**

`src/python/gla/framework/correlation.py`:
```python
def find_object_for_drawcall(dc_id, metadata):
    """Find which framework object owns this draw call."""
    if not metadata: return None
    for obj in metadata.objects:
        if dc_id in obj.draw_call_ids:
            return obj
    return None

def find_material_for_object(obj_name, metadata):
    """Find the material used by a named object."""
    if not metadata: return None
    for mat in metadata.materials:
        if obj_name in mat.used_by:
            return mat
    return None

def find_render_pass_for_drawcall(dc_id, metadata, debug_group_path=None):
    """Find which render pass contains this draw call.
    Checks metadata first, falls back to debug group."""
    if metadata:
        for rp in metadata.render_passes:
            r = rp.draw_call_range
            if len(r) == 2 and r[0] <= dc_id <= r[1]:
                return rp.name
    if debug_group_path:
        return debug_group_path.split('/')[0] if '/' in debug_group_path else debug_group_path
    return None
```

- [ ] **Step 2: Implement FrameworkQueryEngine**

`src/python/gla/framework/query_engine.py`:
```python
class FrameworkQueryEngine:
    def __init__(self, provider, metadata_store):
        self.provider = provider
        self.metadata = metadata_store
    
    def list_objects(self, frame_id): ...
    def query_object(self, frame_id, name): ...
    def query_object_at_pixel(self, frame_id, x, y): ...
    def list_render_passes(self, frame_id): ...
    def query_render_pass(self, frame_id, name): ...
    def query_material(self, frame_id, object_name): ...
    def explain_pixel(self, frame_id, x, y): ...
```

Each method: get data from `provider` (low-level), join with `metadata_store` (high-level), return unified result. Use `correlation.py` helpers for the joins.

- [ ] **Step 3: Write tests for correlation helpers**
- [ ] **Step 4: Write tests for FrameworkQueryEngine**

Test with mock provider + mock metadata. Verify:
- `list_objects` returns metadata objects enriched with draw call info
- `explain_pixel` chains pixel → draw call → debug group → object → material
- Degraded mode: no metadata → returns what GL capture provides

- [ ] **Step 5: Run all tests, verify pass**
- [ ] **Step 6: Commit**

```
feat: correlation engine + FrameworkQueryEngine
```

---

## Task 7: New REST Endpoints

**Files:**
- Create: `src/python/gla/api/routes_objects.py`
- Create: `src/python/gla/api/routes_passes.py`
- Create: `src/python/gla/api/routes_explain.py`
- Modify: `src/python/gla/api/app.py`
- Create: `tests/python/test_api_objects.py`
- Create: `tests/python/test_api_explain.py`

- [ ] **Step 1: Create object query routes**

```python
# routes_objects.py
GET /frames/{frame_id}/objects           → list_objects
GET /frames/{frame_id}/objects/{name}    → query_object
GET /frames/{frame_id}/objects/at/{x}/{y} → query_object_at_pixel
```

- [ ] **Step 2: Create render pass routes**

```python
# routes_passes.py
GET /frames/{frame_id}/passes            → list_render_passes
GET /frames/{frame_id}/passes/{name}     → query_render_pass
```

- [ ] **Step 3: Create explain_pixel route**

```python
# routes_explain.py
GET /frames/{frame_id}/explain/{x}/{y}   → explain_pixel
```

- [ ] **Step 4: Register all routers in app.py**
- [ ] **Step 5: Write tests, verify all pass**
- [ ] **Step 6: Commit**

```
feat: REST endpoints for objects, render passes, and pixel explanation
```

---

## Task 8: New MCP Tools

**Files:**
- Modify: `src/python/gla/mcp/server.py`

- [ ] **Step 1: Add 4 new tools to the MCP server**

```python
# Tool 7: query_object
{"name": "query_object", "description": "Get info about a named scene object",
 "params": {"frame_id": int, "name": str}}

# Tool 8: explain_pixel
{"name": "explain_pixel", "description": "Full explanation of why a pixel is this color",
 "params": {"frame_id": int, "x": int, "y": int}}

# Tool 9: list_render_passes
{"name": "list_render_passes", "description": "Show render pass structure",
 "params": {"frame_id": int}}

# Tool 10: query_material
{"name": "query_material", "description": "Get material properties for an object",
 "params": {"frame_id": int, "object_name": str}}
```

Each tool calls the corresponding REST endpoint.

- [ ] **Step 2: Verify all existing + new tools work**
- [ ] **Step 3: Commit**

```
feat: 4 new MCP tools for framework-level debugging
```

---

## Task 9: Three.js Plugin

**Files:**
- Create: `src/shims/webgl/extension/gla-threejs-plugin.js`

- [ ] **Step 1: Implement the plugin**

Self-contained JS file (~40 lines) that:
- Takes a Three.js scene + renderer URL + token
- Traverses `scene.traverse()` to collect meshes, lights, cameras
- Collects materials from meshes
- POSTs to `/api/v1/frames/{frameCount}/metadata`
- Increments frame counter

- [ ] **Step 2: Commit**

```
feat: Three.js scene graph capture plugin
```

---

## Task 10: Integration Test with Three.js

**Files:**
- Create: `tests/integration/test_threejs_integration.py`

- [ ] **Step 1: Write integration test**

Test that:
1. Start OpenGPA engine
2. POST mock Three.js metadata to `/frames/0/metadata`
3. Query `/frames/0/objects` → returns objects from metadata
4. Query `/frames/0/explain/200/150` → returns explanation with object + material
5. Query `/frames/0/passes` → returns render passes from metadata

This is a Python test that doesn't need an actual Three.js app — it tests the metadata → correlation → query chain.

- [ ] **Step 2: Run test, verify pass**
- [ ] **Step 3: Commit**

```
test: integration test for framework metadata → query pipeline
```

---

## Post-Plan: Next Steps

After completing this plan:
- Test with a real Three.js app in a browser
- Add Unity and Python framework plugins
- Improve `explain_pixel` to include draw call attribution (pixel → draw call mapping)
- Add framework-specific heuristics (e.g., Three.js material type → PBR parameter extraction)
