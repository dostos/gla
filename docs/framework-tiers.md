# GLA Framework Debugging — Tier Model

## Overview

GLA supports three tiers of framework integration, each adding richer data with increasing setup cost. Every tier is additive — higher tiers enrich, never replace, lower-tier data.

```
Tier 3: Metadata Sidecar (per-framework plugin, ~100 LOC)
  ↑ enriches
Tier 2: Debug Markers (free if framework emits GL_KHR_debug)
  ↑ enriches
Tier 1: Raw Capture (zero injection, works on any GL/VK app)
```

---

## Tier 1: Raw Capture (Zero Injection)

**Setup**: None. LD_PRELOAD the shim and go.

**Data captured**:
- Draw call list (primitive type, vertex count, shader ID)
- Shader parameters (uniform names, types, raw values)
- Texture bindings (ID, dimensions, format)
- Pipeline state (depth, blend, cull, scissor, viewport)
- Framebuffer pixels (color, depth, stencil)

**No scene reconstruction**: Scene queries require Tier 3 framework metadata. Use `query_scene` only after a framework plugin has POSTed metadata.

**Queries available**:

| Query | Capability | Limitation |
|-------|-----------|------------|
| `query_frame(overview)` | Draw call count, framebuffer size | No named passes |
| `inspect_drawcall(id)` | Full shader params, pipeline state | No object name |
| `query_pixel(x, y)` | RGBA, depth, stencil | No "which object" |
| `compare_frames(a, b)` | Draw call + pixel diff | Full capability |

**MCP tools**: 5 (query_frame, inspect_drawcall, query_pixel, compare_frames, control_capture)

**Best for**: Raw GL/Vulkan apps, unknown frameworks, quick first look.

---

## Tier 2: Debug Markers (Free Baseline)

**Setup**: None if the framework already emits `GL_KHR_debug` markers. GLA intercepts them automatically via the shim.

**Frameworks that emit markers by default**:
- Unity (Development builds)
- Unreal Engine (RHI debug groups)
- Godot (in debug mode)
- Most Vulkan engines (VK_EXT_debug_utils)

**Frameworks that do NOT emit markers**:
- Three.js
- Babylon.js
- matplotlib / VTK
- Most WebGL apps

**Data captured** (in addition to Tier 1):
- Debug group hierarchy: `glPushDebugGroup("Shadow Pass")` → `glPopDebugGroup()`
- Per-draw-call debug group path: `"GBuffer/Player Mesh"`
- Hierarchical tree structure over draw calls

**Queries available** (in addition to Tier 1):

| Query | Capability | Limitation |
|-------|-----------|------------|
| `list_render_passes()` | Named passes from debug group tree | Names are engine-specific (may be cryptic) |
| `query_render_pass(name)` | Draw call IDs within a pass | No input/output texture tracking |
| `inspect_drawcall(id).debug_group_path` | E.g., "GBuffer/Player Mesh" | Names may not match scene graph |

**Additional MCP tools**: Same 6, but `inspect_drawcall` now includes `debug_group_path` field.

**Best for**: Unity/Unreal/Godot apps in development mode. Get render pass structure for free.

---

## Tier 3: Metadata Sidecar (Per-Framework Plugin)

**Setup**: Add a small plugin (~50-150 LOC) to the application. The plugin traverses the framework's scene graph and POSTs JSON to GLA's metadata endpoint.

**Protocol**:
```
POST /api/v1/frames/{frame_id}/metadata
Content-Type: application/json

{
  "framework": "threejs",
  "version": "165",
  "objects": [...],
  "materials": [...],
  "render_passes": [...]
}
```

**Data captured** (in addition to Tiers 1+2):
- Named objects with scene graph hierarchy (parent/child)
- Object transforms (position, rotation, scale) in framework coordinates
- Material names, shader types, PBR properties, texture maps
- Render pass structure with explicit input/output declarations
- Light properties (color, intensity, range, type)
- Camera properties (FOV, near, far) from the framework's own data

**Queries available** (in addition to Tiers 1+2):

| Query | Capability | Tier 1/2 equivalent |
|-------|-----------|-------------------|
| `list_objects()` | Named objects with hierarchy | `query_scene(objects)` gives unnamed groups |
| `query_object(name)` | Full object info: material, transform, draw calls | Must inspect draw calls manually |
| `query_object_at_pixel(x, y)` | "Player" | "draw call 7" |
| `query_material(object)` | PBR_Metal: albedo=[0.8,0.2,0.1], metallic=0.9 | Raw uniform bytes |
| `list_render_passes()` | Named with input/output textures | From debug markers only |
| `explain_pixel(x, y)` | Full chain: pixel → object → material → pass | Pixel → draw call only |

**Additional MCP tools**: 4 new (query_object, explain_pixel, list_render_passes, query_material). Total: 10.

**Available plugins**:
- Three.js: `gla-threejs-plugin.js` (120 LOC)
- Unity: planned (~50 LOC C#)
- Python frameworks: planned (~20 LOC)
- Generic: POST the JSON manually from any language

**Best for**: Active debugging sessions where you need full scene understanding.

---

## Tier Comparison

| Capability | Tier 1 | Tier 2 | Tier 3 |
|-----------|--------|--------|--------|
| Setup cost | Zero | Zero (if markers exist) | ~100 LOC plugin |
| Draw call inspection | Full | Full | Full |
| Pixel queries | RGBA + depth | RGBA + depth | RGBA + depth + "which object" |
| Render pass structure | Heuristic (FBO changes) | Named (debug groups) | Named + input/output tracking |
| Object identification | Not available (needs Tier 3) | By debug label | By name, with hierarchy |
| Material properties | Raw uniform bytes | Raw uniform bytes | Named: albedo, metallic, ... |
| Camera info | Not available (needs Tier 3) | Not available (needs Tier 3) | Framework's own camera data |
| Scene hierarchy | Flat list | Debug group tree | Full parent/child tree |
| "Why is this pixel this color?" | Draw call + pipeline state | + render pass name | + object + material + full chain |
| Works on unknown apps | Yes | If markers emitted | No (needs plugin) |

---

## Interface Summary

### REST API by Tier

**Tier 1** (existing):
```
GET /frames/{id}/overview
GET /frames/{id}/drawcalls
GET /frames/{id}/drawcalls/{dc}
GET /frames/{id}/drawcalls/{dc}/shader
GET /frames/{id}/drawcalls/{dc}/textures
GET /frames/{id}/pixel/{x}/{y}
GET /frames/{id}/framebuffer
GET /diff/{a}/{b}
POST /control/pause|resume|step
GET /control/status
```

**Tier 2** (adds debug_group_path to draw call responses — no new endpoints)

**Tier 3** (new endpoints):
```
POST /frames/{id}/metadata          # framework plugin sends scene graph
GET  /frames/{id}/metadata          # metadata summary
GET  /frames/{id}/objects           # named object list
GET  /frames/{id}/objects/{name}    # specific object
GET  /frames/{id}/objects/at/{x}/{y} # object at pixel
GET  /frames/{id}/passes            # render pass list
GET  /frames/{id}/passes/{name}     # specific pass
GET  /frames/{id}/explain/{x}/{y}   # full pixel explanation
```

### MCP Tools by Tier

**Tier 1** (5 tools):
1. `query_frame` — overview, draw call list, framebuffer
2. `inspect_drawcall` — shader params, textures, pipeline state
3. `query_pixel` — color/depth at coordinates
4. `compare_frames` — frame diff
5. `control_capture` — pause/resume/step

**Tier 3** adds (5 tools, total 10):
6. `query_scene` — camera, objects (requires framework metadata)
7. `query_object` — named object with material and transform
8. `explain_pixel` — full pixel → object → material → pass chain
9. `list_render_passes` — named pass structure
10. `query_material` — material properties and textures


### Capture Backends

| Backend | Tier 1 | Tier 2 | Tier 3 |
|---------|--------|--------|--------|
| Native (LD_PRELOAD) | Yes | Yes (intercepts markers) | Yes (metadata via HTTP) |
| RenderDoc (.rdc) | Yes | Yes (markers in capture) | Manual (POST metadata separately) |

---

## Future: Reducing the Need for Tier 3

Two approaches to get Tier 3-quality data without per-framework plugins:

### LLM-as-Adapter
Give the agent the framework source code + Tier 1 capture data. The agent correlates:
- Reads Three.js source, sees `scene.add(playerMesh)`
- Queries GLA: "draw call 7 has shader_id=3, uniforms include uModelMatrix"
- Infers: draw call 7 = playerMesh

**Pro**: No plugin code. **Con**: Token-expensive, unreliable for complex scenes.

### Smarter Heuristic Reconstruction
Enhance M3 to recognize common framework patterns:
- Object-per-draw-call (most engines)
- Shared materials = shared shader + same uniform signature
- Render passes = FBO target changes + clear operations
- Shadow maps = depth-only FBO + specific viewport size

**Pro**: Zero setup, works on any app. **Con**: No names, pattern-dependent.
