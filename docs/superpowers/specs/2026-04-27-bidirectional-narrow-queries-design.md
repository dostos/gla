# Bidirectional Narrow Queries — Scene ↔ GL Link Design

**Date:** 2026-04-27
**Status:** design; not yet implemented
**Author motivation:** R9 evaluation evidence — Cat-2 +$0.39/pair carryover regression
**Predecessors (read in order):**
- `docs/superpowers/specs/2026-04-27-scene-graph-cli-design.md` (commit `72a2ddb`) — defines `gpa inspect-scene` and `gpa check-config`. **This spec supplements that one; it does NOT redefine those two.**
- `docs/flywheel-matrix.md` — Cat-2 `framework-app-dev × web-3d` and Cat-3 `framework-maintenance × web-3d` rows
- `docs/superpowers/plans/2026-04-18-framework-integration.md` — Tier-3 plan; debug-marker correlation is Task 3 there

---

## 1. Problem statement

R9's H1+H4 finding: agents called `gpa dump` 6–8× per scenario, parsed verbose
GL JSON, then fell back to `Grep`-ing the app source anyway. The dump pattern
forces the agent to *manually* correlate scene ↔ GL layers — read a uniform
block, grep app for the object, read a texture binding, grep app for the
material — 3+ tool calls per fact, eating cache and context. Net effect on
Sonnet was the +$0.39/pair Cat-2 regression.

**Bidirectional narrow queries replace the dump.** Each new command answers
one scene↔GL question in one tool call by walking a captured `LinkRecord`
join. Spec-`72a2ddb` covers the scene-side (`inspect-scene`) and config-rules
(`check-config`) slices; this spec adds the *traversal* slice — draw → node,
predicate → subtree, pixel → causal chain, draw → draw delta.

Three flywheel-matrix gaps anchor the work:
- "object ↔ drawcall map" (Cat-2/Cat-3 rows): unaddressed.
- "per-draw-within-frame diff" (Cat-1 row): `gpa compare` only does
  frame-to-frame.
- "explain_pixel stub" (Cat-1 row): present as a stub, never productionised.

---

## 2. The link primitive

The data structure that makes bidirectional queries possible:

```
LinkRecord {
  drawcall_id:      int    # GL-side ID, already in NormalizedDrawCall.id
  scene_node_uuid:  str    # framework-side UUID, plugin-emitted
  scene_node_path:  str    # human path: "Scene/Player/Helmet"
  framework:        str    # "three.js" | "babylon" | "mapbox" | ...
}
```

A frame's `LinkTable` is `list[LinkRecord]` and is reconstructed engine-side at
frame end. Each draw has 0 or 1 records (no draw → no link; multiple nodes
sharing a draw is an upstream pathology we do not encode).

### 2.1 Two population mechanisms

**A. Debug-marker (recommended).** The Tier-3 plugin emits
`gl.pushDebugGroup(GL_DEBUG_SOURCE_APPLICATION, 0, -1, node.uuid)` around each
node's draws and `gl.popDebugGroup()` after. The native shim already captures
push/pop into per-drawcall `NormalizedDrawCall.debug_group_path` (e.g.
`"Scene/Player/Helmet"`). The engine reconstructs `LinkRecord` rows at
frame-end by matching path/UUID. **Zero agent-visible cost** — built once at
ingest, queried by ID.

**B. JS proxy fallback.** For runtimes without `KHR_debug`, the plugin wraps
`gl.drawArrays`/`gl.drawElements` and `POST`s
`/api/v1/frames/{id}/links` with `{drawcall_id, scene_node_uuid,
scene_node_path}`. Heavier (one POST per draw), but framework-portable.

### 2.2 Precondition

This spec **assumes** `NormalizedDrawCall.debug_group_path: str` exists
(verified at commit `72a2ddb`: `normalized_types.h:57`, `py_gpa.cpp:82`,
`gl_wrappers.c:340-351`, `frame_capture.c:71/158/299`, `engine.cpp:493`). If
later renamed to `debug_groups: list[str]` per the framework-integration plan
wording, the link engine reads whichever exists. The Tier-3 plugin emitting
markers per node is **not yet shipped** — a Step-3 deliverable in §9.

---

## 3. Four new CLI subcommands

All four obey the CLI-for-agents principles, with **narrowness** as the
overriding rule: each command returns a focused slice (≤50 lines JSON
default), with `--full` available where dump-mode is genuinely useful.

### 3.1 `gpa explain-draw <draw_id>`

**Synopsis**
```
gpa explain-draw DRAW_ID [--frame FRAME] [--field name,uniforms,textures,state]
                         [--json] [--full] [--session DIR]
```

**Purpose.** Single-draw answer: scene-node + material/shader name + uniforms
set + textures sampled + 3 most relevant GL state values. Replaces `gpa dump`
→ grep `'"id": 47'` → grep `uniform_block` → grep `texture_units` (3+ tool
calls) with one ~30-line answer.

**Flags**

| Flag | Meaning |
|---|---|
| `DRAW_ID` | Required positional; the GL draw-call id. |
| `--frame N` | Frame id, default `latest`. Accepts `-` for stdin. |
| `--field LIST` | CSV of `name,uniforms,textures,state`. Default `all`. |
| `--json` | Machine-readable output. |
| `--full` | Include full uniform list and full bound-state dump (opt-in escape hatch). |
| `--session DIR` | Override session discovery. |

**Worked examples**
```bash
gpa explain-draw 47                                    # 1) simplest
gpa explain-draw 47 --field uniforms                   # 2) filtered
gpa explain-draw 47 --json                             # 3) JSON
gpa scene-find material:transparent --json \
  | jq -r '.matches[].draw_call_ids[]' \
  | xargs -I% gpa explain-draw %                       # 4) pipeline
gpa explain-draw 99999
  # [gpa] draw 99999 not found in frame latest. Try `gpa report`. exit 1
```

**Sample output (default, ≤15 lines)**
```
draw 47  frame 7
node      Scene/Player/Helmet  (three.js Mesh, uuid=4f81…)
shader    HelmetMaterial.frag.glsl  (program 12)
material  MeshStandardMaterial("Helmet")  transparent=true opacity=0.4
uniforms  uOpacity=0.4  uMetalness=0.9  uModelMatrix=…
textures  unit0 tex7 Helmet_Albedo RGBA8 1024², unit1 tex8 Helmet_Normal RG8 1024²
state     GL_BLEND=0 ← suspect (material.transparent=true)
          GL_DEPTH_TEST=1  GL_CULL_FACE=1
```

**Exit codes:** 0 ok / 1 draw-or-frame not found / 2 usage error / 3
unresolvable (e.g. pipeline state truncated).

### 3.2 `gpa scene-find <predicate>`

**Synopsis**
```
gpa scene-find PREDICATE [PREDICATE...] [--frame FRAME] [--limit N]
                         [--json] [--session DIR]
```

**Purpose.** Scene-tree subtree(s) matching predicate(s), with each match's
draw-call IDs. Predicates AND together. Replaces `gpa inspect-scene --format
compact | grep | awk` + manual draw-id lookup.

**Predicates (CSV-AND, comma-separated or arg-repeated):**
`material:transparent` / `material:opaque` (negation), `uniform-has-nan`
(any NaN/Inf uniform on the node's draws), `texture:missing` (referenced tex
id didn't bind), `material-name:Glass` (exact), `name-contains:visor`
(substring), `type:Mesh` (exact `obj.type`).

**Flags**

| Flag | Meaning |
|---|---|
| `--frame N` | Default `latest`; `-` for stdin. |
| `--limit N` | Cap matches (default 10). Refuse to run unbounded. |
| `--json` | Machine-readable. |
| `--session DIR` | Override session. |

**Worked examples**
```bash
gpa scene-find material:transparent                    # 1) simplest
gpa scene-find material:transparent,uniform-has-nan    # 2) AND
gpa scene-find type:Mesh,name-contains:visor --json    # 3) JSON
gpa scene-find material-name:Glass --json \
  | jq -r '.matches[].draw_call_ids[]' \
  | xargs -I% gpa explain-draw %                       # 4) pipeline
gpa scene-find badpred:foo
  # [gpa] unknown predicate 'badpred'. Known: material:{transparent|opaque},
  # uniform-has-nan, texture:missing, material-name:NAME, name-contains:S, type:T.
  # Example: gpa scene-find material:transparent,name-contains:visor. exit 2
```

**Sample output (default, ≤12 lines)**
```
scene-find frame 7  predicate=material:transparent  matches=2 (limit 10)

Scene/Player/Helmet   Mesh   MeshStandardMaterial("Helmet") opacity=0.4   draws=[4]
Scene/Effects/Flare   Mesh   RawShaderMaterial("Flare") opacity=1.0       draws=[12,13]

Tip: gpa explain-draw 4 --frame 7
```

**Exit codes:** 0 ok / 1 no matches / 2 usage error.

### 3.3 `gpa scene-explain --pixel X,Y`

**Synopsis**
```
gpa scene-explain --pixel X,Y [--frame FRAME] [--json] [--session DIR]
```

**Purpose.** Productionises the `explain_pixel` stub. Pixel (x,y) → draw →
scene_node → material → uniforms/textures. Full bidirectional traversal in
one call.

**Flags**

| Flag | Meaning |
|---|---|
| `--pixel X,Y` | Required. Comma-separated viewport coordinates. |
| `--frame N` | Default `latest`. |
| `--json` | Machine-readable. |
| `--session DIR` | Override session. |

**Worked examples**
```bash
gpa scene-explain --pixel 200,150                      # 1) simplest
gpa scene-explain --pixel 200,150 --json               # 2) JSON
gpa scene-explain --pixel 200,150 --frame 7            # 3) specific frame
printf '200,150\n401,98\n' \
  | xargs -I% gpa scene-explain --pixel %              # 4) pipeline
gpa scene-explain --pixel 99999,150
  # [gpa] pixel (99999,150) outside viewport (800x600).
  # Example: gpa scene-explain --pixel 200,150. exit 3
```

**Sample output (≤12 lines)**
```
scene-explain frame 7  pixel (200,150)
draw      4   (last write)
node      Scene/Player/Helmet  (Mesh)
material  MeshStandardMaterial("Helmet")  transparent=true opacity=0.4
shader    HelmetMaterial.frag.glsl  (program 12)
inputs    uOpacity=0.4
          Helmet_Albedo tex7 uv≈(0.51,0.62)  Helmet_Normal tex8 uv≈(0.51,0.62)
state     GL_BLEND=0  GL_DEPTH_TEST=1  GL_CULL_FACE=1
```

**Exit codes:** 0 ok / 1 unresolvable (depth-buffer miss, no link record for
the writing draw) / 2 usage error / 3 pixel out of viewport.

### 3.4 `gpa diff-draws <a> <b>`

**Synopsis**
```
gpa diff-draws A B [--frame FRAME] [--scope state|uniforms|textures|all]
                   [--json] [--session DIR]
```

**Purpose.** Closes the per-draw-within-frame diff gap. Returns the *delta*
between draws A and B — uniforms changed, textures rebound, blend-mode
flipped, etc. Replaces "dump A, dump B, eyeball-diff" with one call.

**Flags**

| Flag | Meaning |
|---|---|
| `A`, `B` | Required positionals; the two draw-call ids. |
| `--frame N` | Default `latest`. |
| `--scope` | `state` (default), `uniforms`, `textures`, `all`. |
| `--json` | Machine-readable. |
| `--session DIR` | Override session. |

**Worked examples**
```bash
gpa diff-draws 4 5                                     # 1) state delta
gpa diff-draws 4 5 --scope uniforms                    # 2) filtered
gpa diff-draws 4 5 --scope all --json                  # 3) JSON
gpa scene-find uniform-has-nan --json \
  | jq -r '.matches[].draw_call_ids[]' \
  | xargs -I% gpa diff-draws 0 %                       # 4) pipeline
gpa diff-draws 4 999
  # [gpa] draw 999 not found in frame latest.
  # Example: gpa diff-draws 4 5. exit 1
```

**Sample output (default scope=state, ≤10 lines)**
```
diff-draws frame 7  A=4 (Scene/Player/Helmet)  B=5 (Scene/Player/Body)
state changes A → B
  GL_BLEND        1 → 0
  GL_DEPTH_MASK   0 → 1
  shader_program  12 → 14
  bound_vao       3 → 4
(uniforms/textures unchanged at this scope; pass --scope all)
```

**Exit codes:** 0 ok with diffs / 1 either draw missing OR diffs empty (rare
but distinct from error) / 2 usage error.

### 3.5 What the four narrow queries replace from R9

| Old dump-pattern flow | New narrow command |
|---|---|
| `gpa dump` → grep `id:47` → grep `uniform_block` → grep `texture_units` | `gpa explain-draw 47` |
| `gpa inspect-scene --format compact \| grep \| awk` → manual draw-id lookup | `gpa scene-find material:transparent` |
| `gpa report` → `gpa dump` → grep pixel coords (no good answer) | `gpa scene-explain --pixel x,y` |
| `gpa dump \| jq draw 4` + `gpa dump \| jq draw 5` + eyeball-diff | `gpa diff-draws 4 5` |

---

## 4. REST counterparts

Each CLI command maps to one narrow REST endpoint. All return via
`safe_json_response()` (CLAUDE.md). All GETs, idempotent. ≤10 fields each.

### 4.1 `GET /api/v1/frames/{frame_id}/draws/{draw_id}/explain`

```json
{
  "frame_id": 7,
  "draw_call_id": 47,
  "scene_node_path": "Scene/Player/Helmet",
  "scene_node_uuid": "4f81…",
  "shader_program_id": 12,
  "material_name": "Helmet",
  "uniforms_set": [{"name":"uOpacity","value":0.4}, …],
  "textures_sampled": [{"unit":0,"tex_id":7,"name":"Helmet_Albedo"}, …],
  "relevant_state": {"GL_BLEND":0, "GL_DEPTH_TEST":1, "GL_CULL_FACE":1}
}
```

### 4.2 `GET /api/v1/frames/{frame_id}/scene/find?predicate=…&limit=N`

Multiple `predicate=` query params AND together.

```json
{
  "frame_id": 7,
  "predicate": "material:transparent",
  "limit": 10,
  "match_count": 2,
  "matches": [
    {"path":"Scene/Player/Helmet", "type":"Mesh",
     "material_name":"Helmet", "draw_call_ids":[4]},
    {"path":"Scene/Effects/Flare", "type":"Mesh",
     "material_name":"Flare", "draw_call_ids":[12,13]}
  ]
}
```

### 4.3 `GET /api/v1/frames/{frame_id}/explain-pixel?x=…&y=…`

```json
{
  "frame_id": 7, "pixel": [200,150],
  "draw_call_id": 4,
  "scene_node_path": "Scene/Player/Helmet",
  "material_name": "Helmet",
  "shader_program_id": 12,
  "inputs": {
    "uniforms": [{"name":"uOpacity","value":0.4}],
    "textures": [{"unit":0,"tex_id":7,"name":"Helmet_Albedo","uv":[0.51,0.62]}]
  },
  "relevant_state": {"GL_BLEND":0, "GL_DEPTH_TEST":1, "GL_CULL_FACE":1},
  "resolved": true
}
```
`resolved: false` when depth-buffer miss / no link record (CLI exit 1).

### 4.4 `GET /api/v1/frames/{frame_id}/draws/diff?a=…&b=…&scope=…`

```json
{
  "frame_id": 7, "a": 4, "b": 5, "scope": "state",
  "a_node": "Scene/Player/Helmet",
  "b_node": "Scene/Player/Body",
  "changes": [
    {"key":"GL_BLEND","a":1,"b":0},
    {"key":"GL_DEPTH_MASK","a":0,"b":1},
    {"key":"shader_program","a":12,"b":14},
    {"key":"bound_vao","a":3,"b":4}
  ]
}
```

### 4.5 `POST /api/v1/frames/{frame_id}/links` (fallback only)

Body: `{drawcall_id, scene_node_uuid, scene_node_path, framework}`. Idempotent
on `(frame_id, drawcall_id)` — re-POST overwrites. Used only by §2.1.B.

---

## 5. Validation strategy

Re-run the four R9 carryover scenarios with the four new commands available.

| ID | Description |
|---|---|
| `r10` | three.js feedback-loop visual artefact |
| `r22` | three.js point-sprites attenuation wrong |
| `r25` | PIXI filter chain stale (deferred — different framework) |
| `r27` | three.js black-square shadow artefact |

**Hypothesis.** Sonnet's tool-call count drops from ~8 (dump-pattern) to ~2-3
(narrow-pattern); cost delta flips from +$0.39/pair to ≤$0.

**Definition of "shipped":**

| Deliverable | Acceptance |
|---|---|
| 4 new CLI commands | All flag lists from §3 implemented; `--help` carries ≥3 examples; integration test against fixture frame. |
| 4 new REST endpoints | Each routes via `safe_json_response()`; each has unit tests in `tests/unit/python/test_api_NAME.py`. |
| Reference three.js plugin emits debug markers | Updated `gpa-threejs-plugin.js` adds `gl.pushDebugGroup(node.uuid)` around each node's draws; one eval scenario shows non-empty `debug_group_path` on captured draws. |
| Eval re-run | Cost delta on 3 three.js carryovers (r10, r22, r27) ≤ +$0.10/pair on Sonnet (target ≤$0; ceiling +$0.10 because point-sprite class may not benefit). |

If cost delta does not move ≤$0.10, decompose by command: which command did the
agent pick? Was the link table populated? Was the relevant predicate present?

---

## 6. Layered cost model

**Cheap (no model calls; computed at frame ingest or joined-on-read):**
- `LinkTable` built from `debug_group_path` — O(draws) string match.
- Predicate evaluation for `scene-find` — O(scene_nodes × predicates).
- State diff in `diff-draws` — O(state_keys), trivial.
- All endpoint joins — server-side only.

**Costs the agent (one tool call per hypothesis — the whole point):**
Each command targets ≤50 lines JSON. Cache stays warm because successive
narrow queries on the same frame share the captured prefix.

**Anti-pattern guard.** No command dumps every draw. `--full` flags exist for
the rare escape hatch; their `--help` warns "defeats narrow-query design".

---

## 7. Out of scope

- **Multi-frame queries.** All four commands are single-`--frame`; cross-frame
  is `gpa compare`'s job.
- **WebGPU.** Different draw model (encoders, command-buffers); separate spec.
- **Deep diff of vertex buffers.** `diff-draws --scope all` does NOT include
  per-vertex data. Huge payload, low signal; revisit only if eval demands.
- **Time-series replays.** Step-and-rerun is a separate concept.
- **Bidirectional writes.** All four commands read-only. Fallback `POST
  /links` is plugin-side, not agent-side.

---

## 8. Open questions

1. **`debug_group_path` semantics.** Current shim emits one path string with
   `/` separators; literal `/` in node names is ambiguous. Migrate to
   `debug_groups: list[str]`, or escape? Recommend list form; one-binding
   tweak.

2. **Join key: UUID vs path.** UUIDs are stable, paths drift when nodes are
   renamed/reparented. For single-frame queries either works. Recommend UUID
   canonical, path display-only.

3. **Predicate ordering.** CSV-AND can't express "transparent drawn before any
   depth write". Defer ordering predicates; document in `--help`.

4. **`scene-explain --pixel` resolution.** (a) draw-call-ID framebuffer
   (precise, needs new instrumentation) vs (b) bounding-box hit-test (cheap,
   approximate). Recommend (a) once ID-buffer wiring lands; ship (b) first
   with `"resolved":"approximate"` in the JSON.

5. **Plugin dependency.** `scene-find`, `scene-explain`, and the scene-node
   columns of `explain-draw`/`diff-draws` require the three.js plugin.
   `explain-draw` and `diff-draws` work without the plugin (raw
   `debug_group_path` only). Document degradation in each `--help`.

---

## 9. Implementation order

**Step 1 — Verify debug-marker capture.** Already wired at commit `72a2ddb`
(see §2.2 file list). Add one integration test: `glPushDebugGroup("foo")` +
draw + pop ⇒ captured `debug_group_path == "foo"`.

**Step 2 — Ship `gpa explain-draw` and `gpa diff-draws`.** Work on bare GL
data + debug markers; degrade gracefully (scene-node column blank when
plugin absent). Land:
- `src/python/gpa/cli/commands/{explain_draw,diff_draws}.py`
- `src/python/gpa/api/routes_{explain_draw,diff_draws}.py`
- `tests/unit/python/test_api_{explain_draw,diff_draws}.py`

**Step 3 — Reference three.js plugin emits debug markers per node; then
`scene-find` and `scene-explain --pixel` light up.** Modify
`src/shims/webgl/extension/gpa-threejs-plugin.js` to wrap `renderer.render()`
with `gl.pushDebugGroup(uuid + ":" + path)` / `gl.popDebugGroup()` per mesh.
Land:
- Plugin update (≤30 LoC).
- `src/python/gpa/cli/commands/{scene_find,scene_explain}.py`
- `src/python/gpa/api/routes_{scene_find,explain_pixel}.py`
- Eval re-run on r10, r22, r27 per §5.

Tests: `bazel test //tests/unit/python/...` after each step. Spec-only
commit; tests not affected.
