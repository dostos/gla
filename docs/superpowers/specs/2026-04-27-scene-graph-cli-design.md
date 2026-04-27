# `gpa inspect-scene` + `gpa check-config` — Design Spec

**Date:** 2026-04-27
**Status:** design; not yet implemented
**Author motivation:** R9 evaluation evidence
**Predecessors:**
- `docs/flywheel-matrix.md` — Category 2 (`framework-app-dev`) row, gap markers
- `docs/superpowers/plans/2026-04-18-framework-integration.md` — Tier-3 plan
- `docs/superpowers/specs/2026-04-19-gpa-cli-design.md` — existing CLI shape
- `src/python/gpa/api/routes_annotations.py` (commit `b720e9c`) — annotations sidecar endpoint already shipped

---

## 1. Problem statement

R9 reported a clean **+$0.39/pair carryover regression** on the `framework-app-dev` slice when GPA was attached. The flywheel matrix row for Category 2 (`framework-app-dev × web-3d`) shows the cause: every `gpa report` / `gpa dump` answer is a *GL-level* answer (uniform values, attachments, draw-call lists), but the bug lives at the *framework level* — wrong `scene.add()` parent, wrong `renderer.toneMapping`, mis-configured `material.transparent`. The agent runs `gpa dump`, gets back a wall of GL state that does not reproduce the framework abstractions it actually reasons in, then falls back to reading source — at higher cost than the no-GPA control.

Mining more Cat-2 scenarios will not close this gap; we are missing two **capabilities**:

1. A *scene-graph reader* that walks the framework's object tree and shows the agent its own abstraction.
2. A *config validator* that flags well-known framework misconfigurations against the captured GL state.

The annotations sidecar (`POST /frames/<id>/annotations`, commit `b720e9c`) already accepts framework JSON. What's missing is (a) a Tier-3 plugin that actually populates it, (b) ergonomic CLI surfaces over it, and (c) a small library of framework-vs-GL consistency rules. This spec defines (b) and (c) and sketches the minimal three.js plugin needed for (a).

---

## 2. Two new CLI subcommands

Both subcommands obey the CLI-for-agents principles from the project rubric:

- **Non-interactive first** — every input is a flag.
- **Discoverability** — each subcommand owns its own `--help` page; `gpa --help` continues to be the index.
- **`--help` with copy-pasteable Examples** — every subcommand prints 3-5 worked invocations.
- **stdin/pipelines** — `--frame -` reads frame ids from stdin so they compose with `gpa frames`.
- **Fail fast** — missing or empty annotation → return exit 1 with a one-line message naming the next command to try (`--setup-help`).
- **Idempotent** — pure REST GETs; no writes; no caching.
- **Predictable structure** — `gpa <verb>` shape, matching `gpa report` / `gpa dump` / `gpa trace`.
- **Structured success output** — object IDs, paths, attribute values; pretty tree by default, `--format json` when machine-parseable is wanted.

### 2.1 `gpa inspect-scene`

**Synopsis**

```
gpa inspect-scene [--frame FRAME|-] [--filter EXPR] [--format tree|json|compact]
                  [--depth N] [--field FIELD,...] [--setup-help] [--session DIR]
```

**Purpose.** GET `/api/v1/frames/<frame_id>/annotations` and render the scene-graph payload that a Tier-3 plugin posted at frame end.

**Flags**

| Flag | Meaning |
|---|---|
| `--frame N` | Frame id to inspect. Default: `latest`. Accepts `-` to read newline-separated ids from stdin. |
| `--filter EXPR` | Filter to a sub-tree. Forms: `type:Mesh`, `name:Spotlight`, `path:Scene/Player/*`. Multiple `--filter` flags AND together. |
| `--format` | `tree` (default, indented), `json` (raw payload), `compact` (one-line `path=… type=… key=val …` per node — grep-friendly). |
| `--depth N` | Max tree depth to render (default: unlimited). Cuts noise for huge scenes. |
| `--field FIELD,…` | Comma-separated list of fields to show on each node (default: `type,name,position,visible,material`). |
| `--setup-help` | Print a 30-line three.js plugin snippet (see §4) and exit 0. |
| `--session DIR` | Override session discovery. |

**Worked examples**

```bash
# 1) Simplest: pretty tree of the latest frame
gpa inspect-scene

# 2) Just the lights
gpa inspect-scene --filter type:Light

# 3) Drill into a named subtree, machine-readable
gpa inspect-scene --filter path:Scene/Player/* --format json

# 4) Grep-friendly: find any node whose material has transparent=true
gpa inspect-scene --format compact | grep 'material.transparent=true'

# 5) Pipeline: inspect every captured frame
gpa frames | gpa inspect-scene --frame - --format compact

# 6) Plugin not deployed yet — get setup help
gpa inspect-scene --setup-help
```

**Sample output (tree, default)**

```
gpa inspect-scene — frame 7 (session /tmp/gpa-session-1000-…/)
plugin: gpa-threejs-plugin@0.1   framework: three.js@r161   nodes: 12

Scene  [Group, name="root"]
├── Camera  [PerspectiveCamera, name="MainCam", fov=50, position=(0,1.6,5)]
├── Light  [DirectionalLight, name="Sun", intensity=1.0, position=(5,10,5)]
├── Player  [Group, position=(0,0,0)]
│   ├── Body  [Mesh, geometry=BoxGeometry, material=MeshStandard("PlayerMat")]
│   └── Helmet [Mesh, geometry=SphereGeometry, material=MeshStandard("Helmet"),
│               material.transparent=true, material.opacity=0.4]
└── Floor [Mesh, geometry=PlaneGeometry, material=MeshBasic("Tile")]

12 nodes. Use `--filter` or `--field` to scope.
```

**Sample output (compact)**

```
path=Scene type=Group name=root visible=true
path=Scene/MainCam type=PerspectiveCamera fov=50 position=(0,1.6,5)
path=Scene/Sun type=DirectionalLight intensity=1.0 position=(5,10,5)
path=Scene/Player type=Group position=(0,0,0) visible=true
path=Scene/Player/Body type=Mesh material=PlayerMat material.transparent=false
path=Scene/Player/Helmet type=Mesh material=Helmet material.transparent=true material.opacity=0.4
path=Scene/Floor type=Mesh material=Tile material.transparent=false
```

**Empty-annotation behaviour (fail fast)**

```
$ gpa inspect-scene --frame 7
[gpa] no scene-graph annotation found for frame 7.
[gpa] Plugin not deployed? Run `gpa inspect-scene --setup-help` for a three.js
[gpa] sketch you can drop into your app.
```
Exit code: `1` (no-data).

**Exit codes**

| Code | Meaning |
|---|---|
| 0 | Output rendered. |
| 1 | No annotation data for the requested frame, or transport error. |
| 2 | No active session. |
| 3 | Usage error (bad `--filter` syntax, unknown `--format`). |

---

### 2.2 `gpa check-config`

**Synopsis**

```
gpa check-config [--frame FRAME|-] [--severity error|warn|info]
                 [--rules] [--rule NAME,...] [--json] [--session DIR]
```

**Purpose.** Cross-validate the scene-graph annotation against captured GL state and emit a list of warnings keyed to known three.js / babylon-class consumer-config bugs. Read-only. No side effects.

**Built-in rule set (initial — extensible)**

| Rule name | Triggers when |
|---|---|
| `auto-clear-disabled` | annotation says `renderer.autoClear === false` AND no `glClear` was issued before the first draw of the frame |
| `linear-textures-srgb-output` | `renderer.outputColorSpace === 'srgb'` AND any sampled texture has `internalFormat=GL_RGBA8` (not `GL_SRGB8_ALPHA8`) AND is bound by a material whose `map` slot consumes it |
| `tonemap-fp-target-mismatch` | `renderer.toneMapping !== 'NoToneMapping'` AND every render-target attachment is `RGBA8` (no FP target → tonemap input clamps and bands) |
| `physically-correct-but-no-light-units` | `physicallyCorrectLights === true` AND any light has `intensity < 0.1` (legacy unit-scale leftover) |
| `transparent-without-blend` | annotation node has `material.transparent === true` AND its draw call has `glIsEnabled(GL_BLEND)` false |
| `mismatched-pixel-ratio` | `renderer.pixelRatio` × CSS canvas size ≠ GL viewport dimensions |
| `shadow-map-disabled-but-castShadow` | annotation has any `mesh.castShadow === true` AND `renderer.shadowMap.enabled === false` |
| `frustum-cull-but-bounding-empty` | mesh has `frustumCulled === true` AND its geometry's bounding sphere radius is 0 |

Severities: `error` = certainly broken render, `warn` = likely-wrong-but-may-be-intended, `info` = stylistic.

**Flags**

| Flag | Meaning |
|---|---|
| `--frame N` | Frame to validate. Default `latest`. Accepts `-` for stdin pipeline. |
| `--severity LEVEL` | Threshold; show only at this level or higher. Default `warn`. |
| `--rules` | List the built-in rules with severity + 1-line description. Exit 0. |
| `--rule NAME,…` | Run only these rules (comma-separated). |
| `--json` | Emit `{frame, findings:[{rule,severity,path,gl_evidence,fix}…]}`. |
| `--session DIR` | Override session discovery. |

**Worked examples**

```bash
# 1) Simplest: full report on latest frame
gpa check-config

# 2) JSON for programmatic consumption
gpa check-config --json

# 3) Just the rule catalogue, no session needed
gpa check-config --rules

# 4) Single rule, every captured frame
gpa frames | gpa check-config --frame - --rule auto-clear-disabled

# 5) Ratchet to errors only (ignore warnings/info)
gpa check-config --severity error
```

**Sample output (default plain text)**

```
gpa check-config — frame 7 (session /tmp/gpa-session-1000-…/)
3 findings (1 error, 2 warn)

✗ tonemap-fp-target-mismatch  [error]  Scene
  renderer.toneMapping=ACESFilmicToneMapping but only RGBA8 render target bound.
  Output will band; banding worsens with --strength.
  fix: set renderer.toneMapping after creating an RGBA16F target, or disable tonemap.

⚠ transparent-without-blend  [warn]   Scene/Player/Helmet
  material.transparent=true but draw call 4 has GL_BLEND disabled.
  Three.js usually toggles blend automatically — likely a custom RawShaderMaterial.
  fix: pass `transparent: true` to RawShaderMaterial *and* `blending: NormalBlending`.

⚠ linear-textures-srgb-output [warn]  Scene/Floor (material=Tile)
  renderer.outputColorSpace=srgb but texture id 7 (Tile.map) has internalFormat=RGBA8.
  fix: set tile_texture.colorSpace = THREE.SRGBColorSpace before .needsUpdate=true.

Exit 2 — invalid configuration found by checks.
```

**Exit codes**

| Code | Meaning |
|---|---|
| 0 | No findings at or above `--severity`. |
| 1 | No data (no annotation, or no GL frame). |
| 2 | Findings present at or above `--severity` (CI gateable). |
| 3 | Usage error (unknown rule name, bad severity). |

---

## 3. REST counterparts

Both CLI commands are thin clients over REST. One existing endpoint, one new endpoint:

### 3.1 `GET /api/v1/frames/{frame_id}/annotations` (existing)

Already shipped at commit `b720e9c`. Returns the dict that a Tier-3 plugin POSTed. `gpa inspect-scene` calls this directly. No changes required.

Response (excerpt):
```json
{
  "plugin": "gpa-threejs-plugin",
  "plugin_version": "0.1",
  "framework": "three.js",
  "framework_version": "r161",
  "renderer": {
    "outputColorSpace": "srgb",
    "toneMapping": "ACESFilmicToneMapping",
    "autoClear": true,
    "shadowMap": {"enabled": true, "type": "PCFSoftShadowMap"},
    "pixelRatio": 2.0
  },
  "scene": [
    {"path": "Scene", "type": "Group", "name": "root", "visible": true,
     "draw_call_ids": []},
    {"path": "Scene/Player/Helmet", "type": "Mesh",
     "position": [0, 1.7, 0], "rotation": [0,0,0,1], "scale": [1,1,1],
     "material": {"name": "Helmet", "type": "MeshStandardMaterial",
                  "transparent": true, "opacity": 0.4,
                  "map_texture_id": null, "uniforms": {}},
     "geometry": {"type": "SphereGeometry", "vertex_count": 482,
                  "bounding_sphere_radius": 0.4},
     "draw_call_ids": [4]}
  ]
}
```

### 3.2 `GET /api/v1/frames/{frame_id}/check-config` (new)

```python
# src/python/gpa/api/routes_check_config.py
@router.get("/frames/{frame_id}/check-config")
def get_check_config(frame_id, request: Request,
                     rule: list[str] | None = Query(None),
                     severity: str = "warn"):
    annotation = request.app.state.annotations.get(frame_id)
    provider   = request.app.state.provider
    gl_frame   = provider.get_frame_overview(frame_id)
    findings   = run_rules(annotation, gl_frame,
                           rules=rule, min_severity=severity)
    return safe_json_response({"frame_id": frame_id,
                               "findings": findings})
```

Per CLAUDE.md: returns via `safe_json_response()` (handles bytes from pybind11). No write paths. Idempotent. Token cost: O(rules × scene-nodes), no large data ever returned (each finding is a small dict).

The `run_rules()` function lives in `src/python/gpa/checks/config_rules.py` (new module, parallels `src/python/gpa/cli/checks/`). Each rule is a `(name, severity, predicate, fix_text)` tuple — adding a rule is a 5-line patch.

---

## 4. Tier-3 three.js plugin sketch (≤80 lines)

Recommended starter plugin. Ships under `src/shims/webgl/extension/gpa-threejs-plugin.js` (path consistent with the framework-integration plan).

```javascript
// gpa-threejs-plugin.js — Tier-3 scene-graph reporter for OpenGPA.
// Drop into a three.js page after creating `scene` and `renderer`.
//
// Usage:
//   import { installGpaPlugin } from './gpa-threejs-plugin.js';
//   installGpaPlugin({ scene, renderer,
//                      endpoint: 'http://localhost:18080',
//                      token: 'YOUR_TOKEN' });
// Then call renderer.render() as usual; the plugin POSTs at frame end.

export function installGpaPlugin({scene, renderer, endpoint, token}) {
  let frameId = 0;
  const headers = {
    'Content-Type': 'application/json',
    'Authorization': `Bearer ${token}`,
  };

  const serializeNode = (obj, parentPath) => {
    const path = parentPath ? `${parentPath}/${obj.name || obj.uuid}` : 'Scene';
    const node = {
      path,
      type: obj.type,
      name: obj.name || null,
      visible: obj.visible,
      castShadow: obj.castShadow,
      frustumCulled: obj.frustumCulled,
      position: obj.position?.toArray?.() ?? null,
      rotation: obj.quaternion?.toArray?.() ?? null,
      scale:    obj.scale?.toArray?.()    ?? null,
      draw_call_ids: [],   // populated by the GL shim if available
    };
    if (obj.material) {
      const m = Array.isArray(obj.material) ? obj.material[0] : obj.material;
      node.material = {
        name: m.name || null,
        type: m.type,
        transparent: !!m.transparent,
        opacity: m.opacity,
        map_texture_id: m.map?.image ? m.map.id : null,
        uniforms: m.uniforms ? Object.fromEntries(
          Object.entries(m.uniforms).map(([k, v]) => [k, v.value])
        ) : {},
      };
    }
    if (obj.geometry) {
      const g = obj.geometry;
      g.computeBoundingSphere?.();
      node.geometry = {
        type: g.type,
        vertex_count: g.attributes?.position?.count ?? 0,
        bounding_sphere_radius: g.boundingSphere?.radius ?? 0,
      };
    }
    return [node, path];
  };

  const collectScene = () => {
    const out = [];
    scene.traverse((obj) => {
      const [node, path] = serializeNode(obj, obj.parent ? out[out.length-1]?.path : '');
      out.push(node);
    });
    return out;
  };

  const post = async (payload) => {
    try {
      await fetch(`${endpoint}/api/v1/frames/${frameId}/annotations`,
                  {method: 'POST', headers, body: JSON.stringify(payload)});
    } catch (e) { /* never break the render loop */ }
  };

  const origRender = renderer.render.bind(renderer);
  renderer.render = function(s, cam) {
    origRender(s, cam);
    requestAnimationFrame(() => {
      post({
        plugin: 'gpa-threejs-plugin',
        plugin_version: '0.1',
        framework: 'three.js',
        framework_version: (window.THREE && window.THREE.REVISION) || 'unknown',
        renderer: {
          outputColorSpace: renderer.outputColorSpace,
          toneMapping: renderer.toneMapping,
          autoClear: renderer.autoClear,
          shadowMap: {enabled: renderer.shadowMap.enabled,
                      type: renderer.shadowMap.type},
          pixelRatio: renderer.getPixelRatio(),
        },
        scene: collectScene(),
      });
      frameId += 1;
    });
  };
}
```

Notes:
- POST happens inside a `requestAnimationFrame` *after* `renderer.render()` returns — does not stall the render loop.
- All exceptions swallowed; the plugin never breaks the host app.
- `draw_call_ids` is left empty on the JS side; correlation by `debug_group_path` happens server-side once Task 3 of the framework-integration plan lands (debug-marker pipeline).

---

## 5. Validation strategy

**Definition of "shipped":**

| Deliverable | Acceptance |
|---|---|
| `gpa inspect-scene` CLI | All flags listed in §2.1 implemented; `--help` shows ≥3 examples; integration test against a fixture annotation. |
| `gpa check-config` CLI | All flags listed in §2.2 implemented; ≥6 of the 8 starter rules pass unit tests; `--rules` lists them. |
| `GET /frames/<id>/check-config` endpoint | Returns via `safe_json_response()`; covered by `tests/unit/python/test_api_check_config.py`. |
| `gpa-threejs-plugin.js` | One eval scenario successfully POSTs scene-graph annotations and they are retrievable via `gpa inspect-scene`. |
| Eval delta | Cost delta on Cat-2 carryover slice flips negative or to ~$0 on Sonnet. |

**Eval rerun.** Take the four R9 carryover scenarios that regressed:

| ID | Description | Cat-2 sub-cell | Plugin needed |
|---|---|---|---|
| `r10` | three.js feedback-loop visual artefact | `framework-app-dev × web-3d` | three.js |
| `r22` | three.js point-sprites attenuation wrong | `framework-app-dev × web-3d` | three.js |
| `r25` | PIXI filter chain stale | `framework-app-dev × web-2d` | (PIXI plugin: out-of-scope for this spec) |
| `r27` | three.js black-square shadow artefact | `framework-app-dev × web-3d` | three.js |

For the three three.js scenarios, retrofit the plugin from §4 into the scenario's HTML page. Re-run `bazel run //tests/eval -- --tier sonnet --with-gpa` against just these scenarios. Expected:

- Cost delta vs the no-GPA control: **at least 0** (gap closed), ideally **negative** (the agent finds the bug faster from scene-graph than from grepping source).
- Tool-call mix shifts toward `gpa inspect-scene` and `gpa check-config` and away from `gpa dump`.
- `gpa check-config` produces ≥1 finding tagged to the actual bug in r10 and r27 (those are config bugs).

If the cost delta does not flip, the failure mode is informative: either the rules need expansion, the plugin needs more fields, or the bug class is actually a Cat-3 maintainer bug mis-labelled.

---

## 6. Out of scope

- **React-Three-Fiber-specific introspection.** R3F bugs map onto the underlying three.js scene tree; users embed the plugin once, R3F's reconciler keeps the scene in sync. Any R3F-specific hooks (e.g. surfacing `useFrame` callsites) are userland helpers, not GPA core.
- **Native engines (Godot / Unreal / Unity).** Different plugin model, different runtime; their own spec when we have a Cat-2-native scenario in eval.
- **Performance overhead beyond "negligible at frame end."** The plugin POSTs once per `renderer.render()`; for a 60 fps app that's a 60 Hz JSON payload. We do not premature-optimise (zero-copy SHM, delta encoding, etc.) until evidence demands it.
- **Schema validation for annotation payloads.** Free-form on the wire; rules in `check-config` defensively coerce. If a rule's input is missing, the rule emits `info: missing-field` and continues.
- **Write paths.** Both new commands are read-only. No `gpa annotate-scene` proposed here — the plugin writes; the agent reads.

---

## 7. Open questions

These should be resolved before the implementation plan is approved:

1. **Annotation schema versioning.** The annotation endpoint stores raw JSON. Should `inspect-scene` and `check-config` enforce a `plugin_schema_version` field? If yes, where does the schema live (`src/python/gpa/framework/schemas/threejs_v1.json`?) and how do we evolve it without breaking pinned plugins?

2. **Multi-plugin merge.** If two plugins POST to the same frame (a three.js plugin *and* a custom shader-uniform sidecar), do we merge dicts, last-writer-wins, or keep an array? The current `annotations_store.put()` is last-writer-wins. Cat-2 `web-3d` will probably want merge.

3. **Rule provenance.** `check-config` needs to print "fix: …" hints. Do those come from a hand-curated YAML in-tree (`src/python/gpa/checks/config_rules.yaml`) or from the docstring of the rule predicate function? Hand-curated YAML is reviewable; docstring is colocated with the code.

4. **Filter language scope.** Is `--filter type:Mesh,name:Helmet` (CSV AND) enough, or do we need a real expression grammar (e.g. `material.transparent=true AND geometry.vertex_count>1000`)? Recommend starting with the CSV form and adding an expression mode when an eval scenario actually demands it.

5. **Draw-call correlation.** Both subcommands are useful without correlation, but they get strictly better when scene nodes carry `draw_call_ids`. The full Tier-3 plan (`2026-04-18-framework-integration.md`) ties this to debug-marker capture (Task 3). Does this spec depend on Tier-3 Task 3 landing first, or do we ship `inspect-scene` against bare annotations and add correlation as a follow-up?

---

## Validation results — phase 1 (config-only)

`gpa check-config` was run against the four R9 carryover scenarios after capture
under the live engine + GL shim. No framework annotation was supplied, so this
exercises only the GL-state-derived rule path. Each scenario was a single-frame
capture; rules ran with `--severity info`.

| Scenario | Frame size | Findings | Rule ids fired |
|---|---|---|---|
| `r10_feedback_loop_error_with_transmission_an` | 800x600 | 2 | `depth-write-without-depth-test` (warn), `mipmap-on-npot-without-min-filter` (warn) |
| `r22_point_sprite_rendering_issues_with_three` | 800x600 | 0 | (none — frame state was clean against the 7 enabled rules) |
| `r25_filters_with_backbuffers_seem_not_to_wor` | 256x256 | 1 | `depth-write-without-depth-test` (warn) |
| `r27_bug_black_squares_appear_when_rendering_` | 512x512 | 1 | `depth-write-without-depth-test` (warn) |

Notes:

- All 8 rules loaded and evaluated. `unused-uniform-set` is disabled-by-default
  (info, awaits a FrameProvider field) so 7 rules ran for each frame.
- The `depth-write-without-depth-test` fire is a real GL signature in three
  scenarios — depth_test=False, depth_write=True. Whether it points at the
  underlying bug class for these specific scenarios will be measured in the
  next eval round; the value here is that the agent now has a one-shot
  GL-state warning to consult before reading source.
- `r22` produced no findings against the captured frame, which is the
  expected outcome for a bug class that does not project onto any of the
  current rules' GL signatures (it was a point-sprite vertex-attribute
  issue). It's a candidate for a future rule — `point-sprite-without-PROGRAM_POINT_SIZE`.
- This validates the rule pipeline end-to-end (engine load, REST query,
  frame-state extraction, rule fire, finding serialization). Cost-delta
  measurement against the no-GPA control is the next eval round's job;
  this section is evidence that check-config produces actionable output
  on real captures, not a cost-delta claim.
