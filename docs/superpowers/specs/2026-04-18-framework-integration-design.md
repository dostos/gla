# GLA Framework Integration — Design Specification

## 1. Overview

Extends GLA from raw GL/Vulkan debugging to high-level framework debugging (Unity, Unreal, Three.js, scientific visualization, etc.). Bridges the semantic gap between "glDrawArrays(36 verts)" and "PlayerCharacter mesh with PBR material" through a three-layer data model: GL capture (existing), debug markers (free baseline), and framework metadata (opt-in enrichment).

## 2. Problem Statement

GLA currently operates at the graphics API level:
- Draw calls, shader uniforms, pipeline state, pixel data
- No concept of "objects", "materials", "render passes" as named entities

Developers and LLM agents think in framework-level concepts:
- "Why is the Player invisible?"
- "Which material is on this mesh?"
- "What render pass produces the bloom?"
- "Why does this UI overlap the 3D scene?"

The gap makes GLA useful for raw GL apps but insufficient for real-world framework-based applications.

## 3. Design Principles

- **Query-first**: Define what questions the system answers, then fill in data sources
- **Graceful degradation**: Every query works at some fidelity with just GL capture. Debug markers add structure. Metadata adds names. Each layer enriches, none is required.
- **Framework-agnostic core**: GLA's query engine is not framework-specific. Framework knowledge lives only in plugins.
- **Simple plugins**: The complexity is in GLA's correlation engine, not in per-framework adapters. Plugins just traverse a scene graph and POST JSON.

## 4. High-Level Query Model

### 4.1 New Query Categories

Three new query types on top of existing GLA queries:

**Object Queries** — "What is this thing?"
```
query_object(name)              → draw_call_ids, material, transform, bbox, parent
query_object_at_pixel(x, y)     → which object produced this pixel
list_objects()                  → all named objects in the scene with hierarchy
```

**Render Pass Queries** — "How was this frame built?"
```
list_render_passes()            → ordered: ShadowMap → GBuffer → Lighting → PostFX
query_render_pass(name)         → draw calls, input textures, output targets
query_render_pass_for_drawcall(dc_id) → which pass contains this draw call
```

**Material Queries** — "Why does it look like this?"
```
query_material(object_name)     → shader, textures, properties (albedo, roughness, etc.)
query_material_at_pixel(x, y)   → material of whatever is at this pixel
```

**Pixel Explanation** — "Why is this pixel this color?" (chains all layers)
```
explain_pixel(x, y)             → object, material, render pass, shader params, draw call
```

### 4.2 Degradation by Data Availability

| Data Source | Object Queries | Pass Queries | Material Queries |
|-------------|---------------|--------------|-----------------|
| GL capture only | By draw call ID, no names | By framebuffer target changes | Shader params as raw values |
| + Debug markers | Grouped by marker labels | Named passes from debug groups | Marker-labeled materials |
| + Metadata sidecar | Full scene graph with names, hierarchy | Engine render pass structure with data flow | Named materials with typed properties |

## 5. Data Sources

### 5.1 GL Capture (Existing)

Already implemented. Provides:
- Draw call list with vertex count, primitive type, shader ID
- Shader parameters (uniforms) with values
- Texture bindings with dimensions
- Pipeline state (depth, blend, cull, scissor, viewport)
- Framebuffer pixels (color, depth, stencil)

### 5.2 Debug Marker Interception (New — Free Baseline)

Intercept `GL_KHR_debug` markers that many frameworks already emit.

**Functions to intercept:**
- `glPushDebugGroup(source, id, length, message)`
- `glPopDebugGroup()`

**Shadow state addition:**
```c
#define GLA_MAX_DEBUG_GROUP_DEPTH 32
#define GLA_MAX_DEBUG_GROUP_NAME 128

typedef struct {
    char name[GLA_MAX_DEBUG_GROUP_NAME];
    uint32_t id;
} GlaDebugGroupEntry;

// Added to GlaShadowState:
GlaDebugGroupEntry debug_group_stack[GLA_MAX_DEBUG_GROUP_DEPTH];
uint32_t debug_group_depth;
```

**Per draw call:** Each `DrawCallSnapshot` records the current debug group path as a string, e.g., `"GBuffer/Player Mesh"`.

**Frame-level structure:**
```
DebugGroupNode {
    name: string
    id: uint32
    children: [DebugGroupNode]
    draw_call_ids: [uint32]
}
```

This builds a tree over draw calls:
```
Frame
├── "Shadow Pass" [dc 0-4]
├── "GBuffer Pass"
│   ├── "Player Mesh" [dc 5]
│   └── "Environment" [dc 6-9]
├── "Lighting Pass" [dc 10]
└── "PostFX" [dc 11-12]
```

**Vulkan equivalent:** `vkCmdBeginDebugUtilsLabelEXT` / `vkCmdEndDebugUtilsLabelEXT` — same concept, different API.

### 5.3 Metadata Sidecar Protocol (New — Opt-In)

Framework plugins send scene graph data via HTTP POST.

**Endpoint:**
```
POST /api/v1/frames/{frame_id}/metadata
Content-Type: application/json
Authorization: Bearer <token>
```

**Payload schema:**
```json
{
  "framework": "string",
  "version": "string",

  "objects": [
    {
      "name": "string",
      "type": "string",
      "parent": "string (path)",
      "draw_call_ids": [int],
      "transform": {
        "position": [float, float, float],
        "rotation": [float, float, float],
        "scale": [float, float, float]
      },
      "visible": bool,
      "properties": {}
    }
  ],

  "materials": [
    {
      "name": "string",
      "shader": "string",
      "used_by": ["object_name"],
      "properties": {
        "albedo": [float, float, float],
        "metallic": float,
        "roughness": float
      },
      "textures": {
        "albedoMap": "filename",
        "normalMap": "filename"
      }
    }
  ],

  "render_passes": [
    {
      "name": "string",
      "draw_call_range": [int, int],
      "output": "string or [string]",
      "input": ["string"]
    }
  ]
}
```

**Design decisions:**
- `draw_call_ids` / `draw_call_range` is the join key between metadata and GL capture
- Objects reference materials by name
- Render passes declare inputs/outputs for data flow tracing
- Framework name + version enables framework-specific heuristics
- Metadata is per-frame; framework sends after each frame or only on scene change
- If metadata arrives after frame capture (async), engine attaches to matching frame_id

**Storage:** Metadata stored alongside the frame in a new field on `RawFrame` / `NormalizedFrame`. Accessible via the `FrameProvider` interface.

## 6. Correlation Engine

Joins the three data sources into unified query responses.

### 6.1 Architecture

```
                 ┌─────────────────────────────────┐
                 │     FrameworkQueryEngine          │
                 │                                   │
                 │  query_object()                   │
                 │  explain_pixel()                  │
                 │  list_render_passes()             │
                 │  query_material()                 │
                 └─────┬──────────┬──────────┬──────┘
                       │          │          │
              ┌────────▼───┐ ┌───▼───┐ ┌────▼──────┐
              │FrameProvider│ │Debug  │ │ Metadata  │
              │(GL capture) │ │Markers│ │ Store     │
              └────────────┘ └───────┘ └───────────┘
```

`FrameworkQueryEngine` wraps the existing `FrameProvider` and adds:
- `MetadataStore`: stores per-frame metadata from sidecar POSTs
- Debug group tree: built from intercepted markers (part of GL capture)

### 6.2 Core Method: explain_pixel(x, y)

The chain that ties everything together:

1. `provider.get_pixel(frame_id, x, y)` → RGBA, depth
2. Draw call attribution → which draw call produced this pixel
3. Look up draw call's `debug_group_path` → render pass name
4. Look up draw call in metadata objects → object name, parent path
5. Look up object's material in metadata → material name, properties
6. Get shader params from draw call → actual uniform values
7. Return unified explanation:

```json
{
  "pixel": {"x": 200, "y": 150, "rgba": [204, 51, 25, 255], "depth": 0.45},
  "draw_call_id": 7,
  "debug_group": "GBuffer/Player Mesh",
  "render_pass": "GBuffer",
  "object": {
    "name": "Player",
    "type": "Mesh",
    "parent": "World/Characters",
    "transform": {"position": [5, 0, 3]}
  },
  "material": {
    "name": "PBR_Metal",
    "shader": "Standard",
    "properties": {"albedo": [0.8, 0.2, 0.1], "metallic": 0.9}
  },
  "shader_params": [
    {"name": "uModelMatrix", "type": "mat4", "semantic": "model_matrix"},
    {"name": "uAlbedo", "type": "vec3", "value": [0.8, 0.2, 0.1]}
  ]
}
```

When data is missing, fields are null with a `data_source` indicator:
```json
{
  "object": null,
  "object_source": "no_metadata",
  "render_pass": "Shadow Pass",
  "render_pass_source": "debug_markers"
}
```

### 6.3 Implementation

Python module: `src/python/gla/framework/`
```
framework/
  __init__.py
  query_engine.py      # FrameworkQueryEngine
  metadata_store.py    # Per-frame metadata storage
  debug_groups.py      # Debug group tree builder
  correlation.py       # Join logic (draw call ID → object → material)
```

Extends the `FrameProvider` interface:
```python
class FrameworkQueryEngine:
    def __init__(self, provider: FrameProvider, metadata_store: MetadataStore):
        self.provider = provider
        self.metadata = metadata_store

    def query_object(self, frame_id: int, name: str) -> Optional[ObjectInfo]: ...
    def query_object_at_pixel(self, frame_id: int, x: int, y: int) -> Optional[ObjectInfo]: ...
    def list_objects(self, frame_id: int) -> List[ObjectInfo]: ...
    def list_render_passes(self, frame_id: int) -> List[RenderPassInfo]: ...
    def query_render_pass(self, frame_id: int, name: str) -> Optional[RenderPassInfo]: ...
    def query_material(self, frame_id: int, object_name: str) -> Optional[MaterialInfo]: ...
    def explain_pixel(self, frame_id: int, x: int, y: int) -> PixelExplanation: ...
```

## 7. New REST Endpoints

```
# Metadata ingestion
POST /api/v1/frames/{frame_id}/metadata          # framework plugin POSTs scene graph

# Object queries
GET  /api/v1/frames/{frame_id}/objects            # list all objects
GET  /api/v1/frames/{frame_id}/objects/{name}     # specific object
GET  /api/v1/frames/{frame_id}/objects/at/{x}/{y} # object at pixel

# Render pass queries
GET  /api/v1/frames/{frame_id}/passes             # list render passes
GET  /api/v1/frames/{frame_id}/passes/{name}      # specific pass

# Material queries
GET  /api/v1/frames/{frame_id}/materials/{name}   # specific material

# Pixel explanation (the chain query)
GET  /api/v1/frames/{frame_id}/explain/{x}/{y}    # full pixel explanation
```

## 8. New MCP Tools

Four new tools extending the existing six:

```
query_object(frame_id, name)
  Returns: draw calls, material, transform, bbox, parent, visibility

explain_pixel(frame_id, x, y)
  Returns: full chain — pixel color, object, material, render pass, shader params

list_render_passes(frame_id)
  Returns: ordered pass list with draw call ranges, inputs, outputs

query_material(frame_id, object_name)
  Returns: shader name, properties (albedo, roughness, ...), texture maps
```

Total MCP tools: 10 (6 existing + 4 new).

## 9. Framework Plugin SDK

Minimal adapters that traverse a scene graph and POST the metadata JSON.

### 9.1 Three.js (~30 lines)
```javascript
class GLAPlugin {
  constructor(renderer, url = 'http://127.0.0.1:18080', token = '') {
    this.url = url;
    this.token = token;
    this.frameCount = 0;
  }

  capture(scene, camera) {
    const objects = [];
    const materials = new Map();

    scene.traverse(obj => {
      if (obj.isMesh) {
        objects.push({
          name: obj.name || `mesh_${obj.id}`,
          type: obj.type,
          parent: this._path(obj),
          draw_call_ids: [],  // estimated from render order
          transform: {
            position: obj.position.toArray(),
            rotation: obj.rotation.toArray().slice(0, 3),
            scale: obj.scale.toArray()
          },
          visible: obj.visible
        });
        if (obj.material) {
          materials.set(obj.material.name || obj.material.uuid, obj.material);
        }
      }
    });

    fetch(`${this.url}/api/v1/frames/${this.frameCount}/metadata`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'Authorization': `Bearer ${this.token}`
      },
      body: JSON.stringify({
        framework: 'threejs',
        version: THREE.REVISION,
        objects,
        materials: [...materials.entries()].map(([name, m]) => ({
          name, shader: m.type,
          properties: { color: m.color?.toArray() },
          textures: { map: m.map?.source?.data?.src }
        })),
        render_passes: []
      })
    });
    this.frameCount++;
  }
}
```

### 9.2 Unity (~50 lines C#)
```csharp
using UnityEngine;
using UnityEngine.Networking;

[ExecuteAlways]
public class GLACapture : MonoBehaviour {
    public string glaUrl = "http://127.0.0.1:18080";
    public string token = "";
    int frameCount = 0;

    void OnRenderObject() {
        var renderers = FindObjectsOfType<Renderer>();
        // Serialize scene graph to JSON
        // POST to glaUrl/api/v1/frames/{frameCount}/metadata
        frameCount++;
    }
}
```

### 9.3 Python frameworks (~20 lines)
```python
import requests

def gla_capture(scene, frame_id, url="http://127.0.0.1:18080", token=""):
    objects = []
    for actor in scene.get_actors():
        objects.append({
            "name": actor.name,
            "type": type(actor).__name__,
            "transform": {"position": list(actor.position)},
            "visible": actor.visible,
        })
    requests.post(
        f"{url}/api/v1/frames/{frame_id}/metadata",
        json={"framework": "custom", "objects": objects, "materials": [], "render_passes": []},
        headers={"Authorization": f"Bearer {token}"},
    )
```

### 9.4 Generic (no plugin)

No plugin needed. GLA works with:
- Debug markers (if framework emits them) → pass structure, object grouping
- Heuristic reconstruction from M3 → camera, transforms, object grouping by shared matrix
- Raw GL capture → draw calls, uniforms, pixels

## 10. Implementation Plan

Build order, simplest first:

| Step | What | Effort | Depends On |
|------|------|--------|-----------|
| 1 | Intercept glPushDebugGroup/glPopDebugGroup in GL shim | Small | Nothing |
| 2 | Add debug_group_path to DrawCallSnapshot + serialization | Small | Step 1 |
| 3 | Build DebugGroupTree in normalizer | Small | Step 2 |
| 4 | Metadata REST endpoint (POST + storage) | Small | Nothing |
| 5 | MetadataStore (per-frame storage, attached to frames) | Small | Step 4 |
| 6 | FrameworkQueryEngine (correlation logic) | Medium | Steps 3, 5 |
| 7 | New REST endpoints (objects, passes, materials, explain) | Medium | Step 6 |
| 8 | New MCP tools (4 tools) | Small | Step 7 |
| 9 | Three.js plugin | Small | Step 4 |
| 10 | Eval: test with a real Three.js app | Medium | Steps 8, 9 |

Steps 1-3 (debug markers) and 4-5 (metadata endpoint) are independent and can be done in parallel.

## 11. Success Criteria

1. `explain_pixel(x, y)` returns object name + material + render pass for a Three.js app with the plugin installed
2. `list_render_passes()` shows named passes from debug markers for an engine that emits them
3. All existing queries continue to work unchanged (backward compatible)
4. An LLM agent can answer "why is the Player character invisible?" by calling `query_object("Player")` and seeing `visible: false` or missing draw calls
5. Degraded mode (no markers, no metadata) still returns useful data from heuristic reconstruction
