# OpenGPA Eval Results

## Methodology

- 18 scenarios: 10 synthetic (e1-e10) + 8 real-world (r-prefix, from Three.js/Godot GitHub issues)
- Two modes: **Code-Only** (source + description) and **With OpenGPA** (source + description + live REST API)
- Agent: Claude Sonnet, non-directive prompts ("use whatever approach you think is best")
- Tracked: accuracy, tool sequence, unique OpenGPA insights

## Round 1: Synthetic Scenarios (e1-e10) — WITH hint comments

Both modes: 10/10 correct, high confidence. The bug-revealing comments (`// BUG:`, `// should be`) made code-only trivially easy. **Result: eval was unfair.**

## Round 2: Real-World Scenarios (r-prefix) — WITH hint comments

Both modes: 7/7 correct, high confidence. Again, comments made it too easy.

## Round 3 (pending): All scenarios — AFTER hint stripping

Comments stripped. The bugs are structurally present but not self-documented. This is the fair comparison. **Not yet run.**

## OpenGPA Unique Insights (from Round 2)

Even when both modes get the right answer, OpenGPA provides **runtime evidence** that code-only cannot:

| Scenario | OpenGPA Signal | Why Code-Only Can't See It |
|----------|-----------|---------------------------|
| r16 shadow cull | cull_mode=GL_FRONT (1028) | Distinguishes from r14's GL_BACK — same visual symptom, different root cause |
| r20 neg scale | det(model_matrix)=-1 from captured mat4 | Need to compute 4x4 determinant mentally from code |
| r17 SVG z-fight | Both DCs have uniform uZ=0.0 | Need to trace uniform value through code |
| r5 feedback loop | texture_id=1 bound to sampler AND FBO simultaneously | Need to trace FBO allocation + texture binding |
| r1 UBO overflow | Draw issued but pixel=clear color | Need to know GL_MAX_UNIFORM_BLOCK_SIZE limit |
| r31 missing clear | 2 DCs per frame, no glClear between them | Need to trace render loop control flow |
| e5 uniform collision | Bug doesn't manifest (uniform locs identical) | Impossible without runtime data |

## Tool Usage Patterns

**With OpenGPA mode tool sequence (consistent across all scenarios):**
```
read_source → query_drawcalls → inspect_drawcall → query_pixel
```

- **Pixel queries**: Used in 100% of scenarios (framebuffer trap confirmed)
- **State queries** (inspect_drawcall): Also 100% — used alongside pixels, not instead of
- **Texture queries**: Used when textures relevant (r5, e8)
- **Scene queries**: 0% — not useful without Tier 3 metadata

## OpenGPA Capture Limitations Found

| Limitation | Impact | Fix Needed |
|-----------|--------|-----------|
| `explain_pixel` returns draw_call_id=null | Can't trace pixel → specific draw call | Implement draw call ID buffer |
| Vec3 uniform values garbled | Multi-component float uniforms serialize wrong | Fix serialization for vec2/vec3/vec4 types |
| Render pass auto-detection empty | `list_render_passes` returns nothing without metadata | Expected — Tier 2 debug markers needed |
| shader_id always 3 | All scenarios show same program ID | Expected — single program per scenario |

## Improvement Backlog (from eval findings)

### P0: Fix vec3 uniform serialization
Several scenarios (r17, e10) depend on reading vec3/vec4 uniform values. Currently garbled.

### P1: Implement draw call ID buffer for pixel attribution
`explain_pixel` is the most powerful query but currently can't map pixel → draw call.

### P2: Add glClear interception
r31 (missing clear) would be immediately diagnosable if OpenGPA tracked clear calls between draw calls.

### P3: Track FBO attachments in shadow state
r5 (feedback loop) requires knowing which texture is attached to the current FBO. Currently not captured.

## Conclusions

1. **OpenGPA's primary value is distinguishing bugs with identical symptoms.** r14 and r16 both produce black screens from culling. Code analysis can find both, but OpenGPA instantly distinguishes them via `cull_mode` (1028 vs 1029).

2. **OpenGPA detects silent/compensating bugs.** e5's uniform collision doesn't manifest at runtime. Only OpenGPA can confirm this (code-only reports a false positive).

3. **The eval scenarios need hint-stripped code** for a fair comparison. Round 3 (pending) will show the real accuracy gap.

4. **The improvement backlog is concrete** — each limitation was discovered by running the eval, not hypothesized. This validates the eval-driven development loop.

## Round 4: Real upstream codebases (2026-04-19)

First eval run where subagents must navigate full upstream framework snapshots
(three.js, godot, mapbox-gl-js) to diagnose bugs. 4 scenarios with
`## Upstream Snapshot` metadata × 2 modes × 2 model tiers (Haiku 4.5,
Sonnet 4.5) = 16 non-directive diagnostic runs dispatched in parallel via
`claude -p`. Agents receive only the user-report portion of each scenario
plus `Read`/`Grep`/`Glob` tools over the snapshot dir, with `curl` added
to the REST API in `with_gpa` mode. Ground truth withheld. Max 40 turns
(80 for retries that hit the limit).

### Setup
- Xvfb :99 + OpenGPA engine on :18080 (token `EVALTOKEN`, socket
  `/tmp/gpa_eval.sock`, shm `/gpa_eval`).
- All 4 scenarios captured successfully into frames 1–4.
- Snapshot cache pre-populated under `/data3/opengpa-snapshots/` (three.js
  @ `1f2fea76…`, three.js @ `c2c56858…` (symlink — original SHA not
  reachable on GitHub, backed by the r6 snapshot which contains all files
  r10 needs), godot @ `5950fca3…`, mapbox-gl-js @ `97fc828f…`).

### Per-run results

| Scenario | Mode | Model | Correct | Turns | Files | GPA | Cost |
|---|---|---|---|---|---|---|---|
| r6  | code_only | haiku  | Y | 22 | 2 | 0 | $0.219 |
| r6  | code_only | sonnet | Y |  7 | 2 | 0 | $0.121 |
| r6  | with_gpa  | haiku  | Y | 23 | 4 | 5 | $0.223 |
| r6  | with_gpa  | sonnet | Y | 15 | 3 | 5 | $0.267 |
| r10 | code_only | haiku  | N | 29 | 3 | 0 | $0.328 |
| r10 | code_only | sonnet | Y | 33 | 5 | 0 | $0.765 |
| r10 | with_gpa  | haiku  | Y | 38 | 6 | 6 | $0.399 |
| r10 | with_gpa  | sonnet | Y | 19 | 2 | 4 | $0.302 |
| r15 | code_only | haiku  | Y | 48 | 8 | 0 | $0.492 |
| r15 | code_only | sonnet | Y | 37 | 4 | 0 | $0.912 |
| r15 | with_gpa  | haiku  | Y | 58 | 3 | 6 | $0.598 |
| r15 | with_gpa  | sonnet | Y | 26 | 3 | 6 | $0.501 |
| r27 | code_only | haiku  | N | 33 | 4 | 0 | $0.377 |
| r27 | code_only | sonnet | N | 12 | 2 | 0 | $0.247 |
| r27 | with_gpa  | haiku  | N | 21 | 6 | 0 | $0.216 |
| r27 | with_gpa  | sonnet | N | 37 | 5 | 6 | $0.608 |

"Correct" = keyword-match against `## Ground Truth` plus manual review of
near-miss results (r10 / r15 groups reviewed by hand; r27 confirmed no
agent reached the `Math.ceil` fix).

### Aggregate

| Mode      | Correct | Total cost | Avg turns | Avg framework files | Avg GPA queries |
|-----------|---------|-----------:|----------:|--------------------:|----------------:|
| code_only | 5 / 8   | $3.46      | 27.6      | 3.8                 | 0.0             |
| with_gpa  | 6 / 8   | $3.11      | 29.6      | 4.0                 | 4.8             |

Per-model:

| Model  | code_only | with_gpa |
|--------|-----------|----------|
| Haiku  | 2 / 4     | 3 / 4    |
| Sonnet | 3 / 4     | 3 / 4    |

Per-scenario (code_only | with_gpa):

| Scenario | code_only | with_gpa |
|----------|-----------|----------|
| r6  (three.js UBO overflow)    | 2/2 | 2/2 |
| r10 (three.js feedback loop)   | 1/2 | 2/2 |
| r15 (godot Metal flicker)      | 2/2 | 2/2 |
| r27 (mapbox fractional maxzoom)| 0/2 | 0/2 |

### Qualitative findings

1. **GPA rescues Haiku on a state-collision bug.** r10's bug is "a single
   texture object is both the FBO `COLOR_ATTACHMENT0` and the bound
   `transmissionSamplerMap` sampler." Haiku code-only made up a plausible
   but wrong root cause ("updateMultisampleRenderTarget unbinds the
   framebuffer and fails to rebind"). Haiku with_gpa queried
   `/frames/2/drawcalls/0/textures` and `/frames/2/drawcalls/0` and
   directly cross-referenced texture ID 1 appearing in both the bound
   sampler list and the FBO attachment list, then wrote "GPA frame
   capture confirmed: texture ID 1 is bound as both COLOR_ATTACHMENT0 and
   sampler slot 0." That's exactly the "no heuristic required" case
   predicted in the scenario's `## How OpenGPA Helps`.

2. **r27 is a universal miss across all four (scenario × mode) cells.**
   The bug lives in a JS numeric mistake (fractional `maxZoom` forwarded
   into an integer-indexed `SourceCache` constructor in
   `src/terrain/terrain.ts`, fixed by wrapping in `Math.ceil`). Every
   agent — including the two with full GPA access — went down the
   transform.ts / source_cache.ts quadtree path instead and produced
   sophisticated-sounding but wrong root causes. OpenGPA has no
   visibility into the JS `SourceCache.maxzoom` field upstream of any
   GL call, so GPA's runtime evidence could not steer the agent toward
   the right file. The scenario's own `## How OpenGPA Helps` predicts
   this ("an agent with OpenGPA would still need to read terrain.ts").
   Confirmed.

3. **Code-only agents burn turns on blind greps; with-GPA agents
   front-load a cheap 1–2 curl calls.** Haiku+GPA on r10 used 6 GPA
   queries and 6 file reads in 38 turns; Haiku code-only used 0 GPA
   queries and 3 file reads in 29 turns but still converged on the
   wrong answer. The GPA calls acted as a hypothesis-filter: the agent
   saw the FBO-attachment/sampler collision *first*, then went to the
   source to explain *why*, rather than reading files and trying to
   build a theory top-down.

4. **r15 shows OpenGPA's scope boundary.** The bug is in Godot's Metal
   backend (macOS/Metal only). OpenGPA cannot capture it — the repro in
   `tests/eval/r15_.../main.c` just submits a black frame as a stub.
   Nevertheless all four r15 agents (both modes) correctly identified the
   Metal dynamic-UBO path as the culprit, each pointing at a different
   but plausible offending symbol (`command_pipeline_barrier`,
   `MDUniformSet::bound_uniform_set`, argument-buffer `useResources`
   tracking). The scenario's ground truth is itself vague ("must be an
   issue with the dynamic uniform buffers… they appear to be corrupted")
   so scoring accepted any Metal-UBO-synchronization story. GPA gave no
   extra signal here because the captured frame was a stub — as the
   scenario metadata predicts.

5. **Sonnet dominates code-only; Haiku+GPA closes the gap.** The single
   cell where Haiku code-only failed (r10) is also the single cell where
   Haiku with_gpa succeeded. In contrast, Sonnet got r10 correct even
   without GPA by reading more framework source (5 files vs Haiku's 3).
   The working interpretation: GPA turns the smaller model's runtime
   evidence into what the bigger model would otherwise compensate for
   with broader source reading. Consistent with the "OpenGPA as
   force-multiplier for smaller models" hypothesis.

### Capture gaps surfaced

- **r27**: JavaScript-level state (`SourceCache.maxzoom`) upstream of any
  GL call is invisible to OpenGPA's Tier 1 shim. A Tier 3 framework
  plugin for mapbox-gl-js that POSTs `SourceCache` metadata per frame
  would close this — but no such integration exists. Candidate for the
  backlog.
- **r15**: No Metal capture backend. Already flagged in `## How OpenGPA
  Helps`; not new, but confirmed.
- **r10**: `get_draw_call` returns bound textures + FBO attachments as
  separate lists, but the agent had to cross-reference GL names
  manually. A derived `/frames/<id>/drawcalls/<dc>/feedback-loops`
  endpoint (or a field `collides_with_fbo_attachment: true` on each
  bound texture) would turn the diagnosis into a single query. Low
  cost, high leverage.

### Next-iteration backlog (from Round 4 findings)

1. **Framework plugin for at least one non-trivial JS framework**
   (mapbox-gl-js or three.js) — Tier 3 metadata lets OpenGPA cover bugs
   whose root cause is upstream of the GL call stream. Without this, any
   scenario like r27 is unreachable regardless of model size.
2. **Derived "collision" fields on draw-call queries**: mark bound
   textures that are also attachments of the currently-bound FBO. Would
   have made r10 a zero-reasoning query.
3. **Higher-difficulty upstream scenarios where state-collision /
   resource-leak patterns dominate** — this is where GPA actually pays
   off, and the current 4-scenario batch is too small to show
   statistical significance.

### Raw artifacts

- `/tmp/eval_round4/*.json` — 16 per-run Claude Code JSON outputs.
- `/tmp/eval_round4/scored.json` — scored aggregate.
- `/tmp/eval_round4/run_subagent.sh`, `score.py`, `summarize.py` — eval
  driver scripts.

## Round 5 — 20 Framework-Consumer Scenarios (2026-04-19)

First statistically meaningful run. 20 real-world scenarios (pixijs, three.js,
mapbox-gl-js, pmndrs/postprocessing, Pixelorama) × 2 modes × 2 models = 80 runs
budgeted, 78 executed (r29 segfaulted at startup — no GL capture, so its
`with_gpa` cells were skipped). 40-turn budget per run, 8 retries at 80 turns.

All scenarios pre-cleaned by the contamination validator: no hint comments,
`## User Report` and `## Ground Truth` separated. Subagents received only
`## User Report` + the upstream framework snapshot (for the 12 scenarios with
one — three.js, mapbox-gl-js, pixijs, postprocessing) + optional GPA curl.

### Setup

- Xvfb on `:99`, engine on `:18080`, shim + shm `/gpa_eval`, token `EVALTOKEN`.
- Built all `tests/eval:*` targets. Captured 19/20 scenarios with non-empty
  draw-call counts (1–5 draws each); r29 segfaulted before any GL call and
  only ran in `code_only` mode.
- Snapshots: three.js (977 MB), mapbox-gl-js (531 MB), pixijs and postprocessing
  cloned fresh (depth 200). Pixelorama (r12) was handled shader-only from the
  scenario directory.

### Aggregate Accuracy

| Mode      | Model  | N  | Correct | Accuracy |
|-----------|--------|----|---------|----------|
| code_only | haiku  | 20 | 20      | 100.0%   |
| code_only | sonnet | 20 | 17      | 85.0%    |
| with_gpa  | haiku  | 19 | 17      | 89.5%    |
| with_gpa  | sonnet | 19 | 16      | 84.2%    |

- **Total cost: $30.94** across all 78 runs.
- Avg turns: code_only 18–24; with_gpa 20–29.
- Avg framework files opened: 2.6–5.3. Avg GPA queries (with_gpa only): 3.6–4.7.

### Per-Scenario Matrix

`co_h / co_s` = code_only Haiku / Sonnet; `gp_h / gp_s` = with_gpa Haiku / Sonnet.
`-` = not applicable (capture failed).

| Scenario | co_h | co_s | gp_h | gp_s |
|----------|:----:|:----:|:----:|:----:|
| r11_three_js_effectcomposer_browser_window_r | Y | Y | Y | Y |
| r12_omniscale_cleanedge_scaling_issues | Y | Y | Y | Y |
| r15_post_effects_and_transparent_background_ | Y | Y | Y | Y |
| r15_unrealbloompass_produces_no_visible_outp | Y | Y | Y | Y |
| r20_three_js_meshdepthmaterial_depth_map_not | Y | Y | Y | Y |
| r22_point_sprite_rendering_issues_with_three | Y | Y | Y | Y |
| r23_using_multiple_alphamask_s_with_renderma | Y | Y | Y | Y |
| r24_artifacts_when_rendering_both_sides_of_a | Y | Y | Y | Y |
| r24_enabling_autogeneratemipmaps_breaks_filt | Y | Y | Y | Y |
| r25_filters_with_backbuffers_seem_not_to_wor | Y | Y | Y | Y |
| r25_three_js_transparency_disparition | Y | Y | Y | Y |
| r26_incorrect_behavior_in_colormatrixfilter_ | Y | Y | Y | Y |
| r27_bug_black_squares_appear_when_rendering_ | Y | Y | **N** | **N** |
| r28_bug_in_rendering_glb_models | Y | N | N | N |
| r29_add_an_animated_icon_to_the_map_not_work | Y | N | - | - |
| r30_incomplete_lines_problem_with_mixing_lay | Y | Y | Y | Y |
| r32_v7_issue_with_custom_points_shader_three | Y | N | Y | Y |
| r33_latest_build_6_38_1_got_glitchy_opacity_ | Y | Y | Y | Y |
| r34_depth_buffer_issue_when_using_depthoffie | Y | Y | Y | N |
| r3_material_shines_through_when_zooming_out | Y | Y | Y | Y |

### Qualitative Findings

**Round 4's Haiku+GPA force-multiplier pattern DID NOT reproduce at scale.**
Haiku with code_only scored 20/20 on this suite; GPA did not add a measurable
accuracy delta over code_only for either model. In 4 cells GPA *regressed*
relative to code_only (r27 both models, r28 haiku, r34 sonnet). The cleaned
scenario descriptions + upstream framework access are already sufficient for
an LLM to reason about most of these bugs; the smaller sample from Round 4
(4 scenarios) conflated scenario difficulty with a GPA effect.

**r27 is the most interesting regression.** Both GPA agents noticed NaN/black
patches in the framebuffer and anchored on "division by zero in
D_GGX_Anisotropic denominator" — an internally coherent but wrong hypothesis.
Code-only agents, lacking that empirical hint, read the fragment shader and
correctly identified the removed `saturate()` on `V_GGX_SmithCorrelated_Anisotropic`
plus the per-channel energy-conservation change. **Live pixel evidence led the
model toward a plausible local fix rather than the architectural cause.** This
is a new failure mode not seen in Rounds 1–4: GPA's runtime signal becomes a
red herring when the visible artifact (NaN→black) has multiple pathways.

**r28 (Mapbox GLB 65 k vertex limit)** — 1/4 correct. The bug lives in a
purely CPU-side type choice (`TriangleIndexArray` uses `Uint16Array`) that
never surfaces as a GL error; the GL stream just shows truncated indices.
Sonnet-code-only inventedfilter hypotheses; GPA-mode agents hallucinated
depth/projection issues from what was actually a degenerate wireframe draw.
**The repro frame didn't carry enough signal to disambiguate — this is a
scenario where Tier 3 framework metadata (reporting `indexBufferType:
"UNSIGNED_SHORT"` on the draw call) would directly fix it.**

**r29 (Mapbox animated-icon regression)** — 1/2 correct, no GPA cells. The
binary segfaulted before issuing any GL call (likely a scenario bug; only
Haiku code-only succeeded, speaking to scenario.md alone).

### Capability gaps for next iteration

See `docs/superpowers/eval/round5-capture-gaps.md`.

### Raw artifacts

- `/tmp/eval_round5/*.json` — 78 per-run Claude Code JSON outputs.
- `/tmp/eval_round5/scored.json` — scored aggregate (parsed dict per run).
- `/tmp/eval_round5/summary.txt` — mode × model and per-scenario tables.
- `/tmp/eval_round5/run_subagent.sh`, `score.py` — driver scripts.
- `/tmp/eval_round5/captures.txt` — scenario → frame_id + draw count.
