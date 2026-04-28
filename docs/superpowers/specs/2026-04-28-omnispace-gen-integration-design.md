# OpenGPA ↔ omnispace-gen Integration — Design

**Date**: 2026-04-28
**Status**: Approved (brainstorming complete, plan to follow)
**Affects**: `gla/` (OpenGPA), `omnispace-gen/`

## Problem

omnispace-gen renders human motion in two places: a live React/three-fiber workbench, and an offline Python pipeline (Open3D default, pyrender/OSMesa fallback). The project's feedback pipeline already classifies "visual/3D" bugs into a bucket that requires human verification — there is no automated way for an agent to inspect the rendered output and reason about it.

OpenGPA exists to give agents structured access to graphics state, but its WebGL Tier-3 plugin is currently a single file inside a Chrome extension subtree, and there is no Python client at all. omnispace-gen is the first non-self consumer; its needs will shape the public API surface.

## Goal

Enable an agent to answer: **"which joint of the SMPLX render is at the wrong world position?"** — both for the live workbench and for the offline Open3D pipeline, with a single shared joint-naming convention so MCP queries return the same strings against either renderer.

Non-goals (Phase 3, deferred):
- pyrender/OSMesa interception (separate library, separate shim work)
- WebGL Tier-1 (`readPixels` via the Node bridge, Chrome extension install)
- Occlusion-aware diagnosis ("is the marker actually visible?")

## Architecture

Three phases, gated:

```
Phase 1 (workbench)        Phase 2 (Open3D offline)        Phase 3 (deferred)
   Tier-3 only        ──►     Tier-3 + LD_PRELOAD     ──►    OSMesa shim
   joint markers              same naming convention          readPixels bridge
                                                              gated on Phase 1/2 eval
```

Phase 3 is built **only if** Phase 1/2 evals demonstrate that the missing pixel/occlusion data actually breaks per-joint diagnosis. The likely outcome is that named joint markers + Tier-3 transforms answer the question without it.

The shared artifact across phases is a single joint-naming module — without it, the workbench scene says `right_elbow_marker` and Open3D says `joint_18`, and MCP queries can't be written against both.

## Components

### OpenGPA (`gla/`) — extract reusable clients

| New location | What | Notes |
|---|---|---|
| `clients/threejs/index.js` + `package.json` | Tier-3 client for Three.js. Adapted from `src/shims/webgl/extension/gpa-threejs-plugin.js`. Publishable as `@opengpa/threejs-sidecar`. | Existing extension keeps depending on it via relative import — no behavior change. |
| `clients/python/opengpa_client/` | Python Tier-3 client. Pip-installable. Exposes `Tier3Sidecar` ABC + HTTP POST helper. | Renderer-agnostic; backends subclass and implement `walk_scene()`. |

### omnispace-gen — consume + add joint convention

| File | What | LOC |
|---|---|---|
| `src/common/skeletal/opengpa_joint_names.py` | Canonical SMPLX joint name list. Single source of truth, exported to JS at build time. | ~30 |
| `src/motiongen/visualization/joint_markers.py` | Per-joint marker geometry (small spheres) for Open3D, named per convention. Toggled by `enable_opengpa_markers` config flag. | ~80 |
| `src/motiongen/visualization/opengpa_sidecar.py` | Open3D subclass of `Tier3Sidecar`. Walks Open3D scene, builds metadata payload, POSTs. | ~80 (smaller because client lib does the HTTP work) |
| `workbench-ui/src/lib/jointMarkers.tsx` | R3F component rendering named `<mesh>` per SMPLX joint above the body mesh. Toggle in workbench UI. | ~60 |
| `workbench-ui/src/lib/opengpaSidecar.ts` | Thin glue: instantiates `@opengpa/threejs-sidecar` in `<Canvas onCreated>` and calls `capture(scene, camera)` after each render. | ~30 |
| `configs/paths.yaml` | Add `modules.opengpa: { engine_url, token }` per the project's path-resolution convention. | +5 |

### OpenGPA — no new code in MVP

`/api/v1/frames/{id}/metadata`, `query_object`, `list_objects`, `explain_pixel` already exist and accept this payload. We consume only.

## Data flow

### Phase 1 — workbench (live debug)

```
User opens workbench → R3F renders frame
   │
   ├─► JointMarkers component renders <mesh name="joint_<smplx_name>" .../> per joint
   │
   └─► onCreated callback wires sidecar:
         opengpaSidecar.capture(scene, camera) after each frame
              │
              └─► HTTP POST :18080/api/v1/frames/{N}/metadata
                       { framework: "threejs", objects: [...joints + body...], materials, camera }
                       (frame_id N = sidecar's local monotonic counter)

Agent (via MCP):
   query_object("joint_right_elbow") → { transform: { position: [0.42, 1.10, -0.05] } }
   ─ compares to source MotionSequence.joints[<idx>]   ← expected position
   ─ flags discrepancy
```

### Phase 2 — Open3D offline (batch debug)

```
User runs: LD_PRELOAD=libgpa_gl.so python scripts/render_scene.py --scene 006 ...
   │
   ├─► Open3D renders frame (joint markers added by joint_markers.py via config flag)
   │     └─► GL calls captured by libgpa_gl.so → engine ingests via Unix socket
   │
   ├─► Sidecar polls GET /api/v1/frames/current/overview → reads engine_frame_id
   │
   └─► Open3D Tier3Sidecar walks the scene:
         └─► HTTP POST :18080/api/v1/frames/{engine_frame_id}/metadata
                       (same payload schema as Phase 1, joined with engine's GL data on the same frame_id)

Agent: same MCP queries; same joint names; same diagnostic logic.
```

### Frame-ID correlation

- **Workbench (Phase 1):** sidecar's local counter is authoritative. Engine has no captured frames in this mode; metadata is stored against the sidecar's IDs. MCP tools that need GL data return 404 — correct.
- **Open3D (Phase 2):** sidecar reads `GET /api/v1/frames/current/overview` to get the engine's `frame_id`, POSTs metadata under that ID. `MetadataStore` accepts arbitrary frame IDs, so the join is implicit.

## Error handling

| Failure | Behavior | Why |
|---|---|---|
| Engine not running | Sidecar's HTTP POST fails → swallow silently. Render proceeds normally. | Matches existing `gpa-threejs-plugin.js` (`.catch(() => {})`). Debugger never breaks the app. |
| LD_PRELOAD captures, sidecar POST is delayed/lost | Engine has GL data without metadata. `query_object` returns 404 for that frame. | Acceptable — agent retries on next frame. Frames are commodity. |
| Sidecar POST succeeds, GL capture missed (Phase 2) | Engine has metadata for a frame_id with no overview. `query_pixel` returns 404; `query_object` works. | Same shape as Phase 1 — degrades to metadata-only. |
| Joint name mismatch between renderers | Caught by cross-language schema test (see Testing). | Single source of truth (`opengpa_joint_names.py`) prevents this by construction. |
| OpenGPA `clients/threejs/` or `clients/python/` not installed | Hard fail at workbench/render startup with a clear error pointing at install instructions. | Matches the project's Rust-extension precedent (`omnispace-gen/CLAUDE.md`: "All imports are unconditional"). Silent broken integrations are worse than loud failures. |
| User toggles "OpenGPA capture" off in workbench | Sidecar instantiates as no-op; joint markers still rendered (separate flag). | Capture and visualization are independently toggleable. |

## Testing

### OpenGPA-side (`gla/`)

| Test | Where | Asserts |
|---|---|---|
| `clients/threejs/` smoke | jest in `clients/threejs/` | Module imports; `capture()` POSTs to a stub server with documented payload shape. |
| `clients/python/` smoke | `tests/unit/python/test_opengpa_client.py` | `Tier3Sidecar` ABC contract; subclasses must implement `walk_scene()`; POST helper handles connection refusal silently. |
| **Eval scenario: per-joint diagnosis** | `tests/eval/r37_joint_offset_smplx/` (new) | Known-broken render where one joint is offset by 5cm. Agent runs MCP `query_object` against each joint, compares to ground truth, identifies the wrong joint within N tool calls. **This is the load-bearing eval — proves the whole story works end-to-end.** |

### omnispace-gen-side

| Test | Where | Asserts |
|---|---|---|
| Joint name registry | `tests/unit/skeletal/test_opengpa_joint_names.py` | Python list and JS-exported list match (cross-language schema test; fails on drift). |
| Open3D Tier3Sidecar | `tests/integration/test_opengpa_sidecar_open3d.py` | Spin up engine, render a known scene with markers, POST goes through, `GET /frames/{N}/metadata` returns expected joint count. |
| Workbench plugin (E2E) | extend `tests/e2e/test_workbench_browser.py` | With OpenGPA capture toggle on, generate a motion, then `curl :18080/api/v1/frames/{N}/objects` returns joint markers with expected names. |
| Quality scenario | `configs/quality_scenarios.yaml` | At least one scenario gates on "joint markers POSTed correctly" — keeps integration alive in CI. |

## Out of scope (Phase 3, deferred)

- OSMesa interception in the GL shim (covers pyrender fallback).
- Chrome extension Tier-1 capture in the workbench (raw draw calls, framebuffer pixels).
- `readPixels` round-trip via the Node bridge for visibility/occlusion checks.
- Custom MCP tool "joint nearest pixel (x,y)" — current `query_object` is sufficient when names are known.

## Migration notes

- Existing `src/shims/webgl/extension/gpa-threejs-plugin.js` becomes a re-export from `clients/threejs/index.js`. Behavior preserved; the extension's manifest still picks it up.
- `bridge.js`, `interceptor.js`, `gpa-trace.js` unchanged in this spec — they're Phase 3 territory.
- omnispace-gen `configs/paths.yaml` gains an `opengpa` section under `modules`. Other modules unaffected.

## Open questions

None at design time. Open questions surfaced during implementation should be raised back to spec rather than resolved silently.
