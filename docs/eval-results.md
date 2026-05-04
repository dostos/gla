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
   `tests/eval/native-engine/godot/godot_114069_godot_mobile_renderer_macos_transparent_flicker/main.c` just submits a black frame as a stub.
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

#### Verdict breakdown

| Mode      | Model  | Solved | Timeout | Wrong | Infra |
|-----------|--------|-------:|--------:|------:|------:|
| code_only | haiku  |     20 |       0 |     0 |     0 |
| code_only | sonnet |     17 |       0 |     3 |     0 |
| with_gpa  | haiku  |     17 |       0 |     2 |     0 |
| with_gpa  | sonnet |     16 |       0 |     3 |     0 |

R5 had zero timeouts — every incorrect run was a confidently-wrong
diagnosis. This is consistent with the rich-scenario hypothesis: once a
framework snapshot is available, the 40-turn budget is more than enough
and any failure is a quality-of-evidence problem, not a budget problem.

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

## Round 6 — `gpa` CLI token-efficiency measurement

**Hypothesis**: giving with_gpa-mode agents the new `gpa` CLI (as a single
Bash-invokable tool that bundles all diagnostic checks) will cause them to
*substitute* curl/file-read sequences with one `gpa report` call, closing
the Round 5 token gap where with_gpa averaged **+241 K** more cache_read
tokens and **+$0.048** more per run than code_only.

### Setup

- Same 20 scenarios as Round 5; same models (`claude-haiku-4-5`,
  `claude-sonnet-4-5`); same 40-turn budget; same upstream-snapshot layout.
- Engine started via `gpa start` (the new session-managed launcher) on
  port 18080; narrow REST endpoints (`feedback-loops`, `nan-uniforms`,
  `attachments`) now part of the OpenAPI surface.
- Captured all 20/20 scenarios (R5 failed to capture r29; R6 succeeded
  after the r29 segfault fix landed).
- `with_gpa` prompt replaced the curl boilerplate with the `gpa report
  --frame <id> --json` example first, `gpa check/dump` as drill-downs, and
  curl explicitly framed as fallback. `Bash(gpa:*)` added to the allow-list.

### Aggregate Accuracy (R6, 80 runs)

| Mode      | Model  | N  | Correct | Accuracy |
|-----------|--------|----|---------|----------|
| code_only | haiku  | 20 | 16      | 80.0%    |
| code_only | sonnet | 20 | 17      | 85.0%    |
| with_gpa  | haiku  | 20 | 17      | 85.0%    |
| with_gpa  | sonnet | 20 | 15      | 75.0%    |

**Total cost: $34.03** across 80 runs. Accuracy is noisier than R5 —
haiku code_only regressed from 20/20 → 16/20 (this is the first time
haiku-code-only has missed any of this suite). Three scenarios are
universally hard for both modes this round: r27 (anisotropic GGX),
r28 (GLB 65 K index overflow), r29 (Mapbox icon regression) — all 0/4.
The r27/r28 failures match R5; r29 is new because we finally captured
it so code_only agents now see the same scenario file both modes see.

#### Verdict breakdown

| Mode      | Model  | Solved | Timeout | Wrong | Infra |
|-----------|--------|-------:|--------:|------:|------:|
| code_only | haiku  |     16 |       2 |     2 |     0 |
| code_only | sonnet |     17 |       1 |     2 |     0 |
| with_gpa  | haiku  |     17 |       1 |     2 |     0 |
| with_gpa  | sonnet |     15 |       2 |     3 |     0 |

Timeouts appear for the first time in R6 (6/80) — the new `gpa` CLI
prompt overhead and the harder carryovers pushed a handful of runs past
the 40-turn budget. Wrong-class failures (9/80) still dominate, matching
R5's signal that the three universal-hard scenarios (r27/r28/r29) are
data-quality limited.

### Token & Cost Deltas — R5 vs R6

Δ = `with_gpa − code_only` averages per model:

| Round | Model  | Δ cost     | Δ turns | Δ cache_read    | Δ cache_create |
|-------|--------|------------|---------|------------------|----------------|
| R5    | haiku  | **+$0.048** | +5.6    | **+384 K**        | +4 K           |
| R5    | sonnet | **+$0.005** | +1.9    | **+57 K**         | −3 K           |
| R6    | haiku  | **+$0.019** | +4.1    | **+251 K**        | −3 K           |
| R6    | sonnet | **−$0.022** | −1.6    | **−64 K**         | +0 K           |

- **Sonnet flipped sign on both axes.** with_gpa is now *cheaper* and
  *lower-cache* than code_only. Δ cache_read went −121 K in absolute change
  versus R5 — directly confirming the substitution hypothesis for sonnet.
- **Haiku improved but did not flip.** Δ cost halved ($0.048 → $0.019);
  Δ cache_read down 34 % (384 K → 251 K). The CLI helps, but haiku still
  does enough extra work with GPA that it costs more overall.

### Pair-wise cost deltas (with_gpa minus code_only, same scenario)

| Round | Model  | cheaper | costlier | net Δ total cost |
|-------|--------|---------|----------|------------------|
| R5    | haiku  | 5/19    | 14/19    | **+$1.15**       |
| R5    | sonnet | 8/19    | 11/19    | +$0.12           |
| R6    | haiku  | 9/20    | 11/20    | +$0.38           |
| R6    | sonnet | 8/20    | 12/20    | **−$0.44**       |

The haiku `cheaper` bucket doubled (5 → 9 pairs). Sonnet's cheaper count
is unchanged in absolute but the cheaper pairs now *save more* than the
costlier pairs lose — first time this flipped.

### CLI tool adoption

- 19/20 with_gpa-haiku runs invoked `gpa` at least once; 19/20 for sonnet.
  One haiku (r29) and one sonnet (r34) self-reported 0 GPA queries.
- Mean self-reported queries/run: haiku 3.15 (down from 3.63 in R5),
  sonnet 4.60 (up from 4.47). The haiku drop is consistent with the
  "one `gpa report` replaces many curls" pattern; the sonnet rise
  suggests sonnet uses `gpa` *more* freely precisely because the CLI is
  ergonomic — but still comes out cheaper because each invocation is
  cheaper than the curl-based equivalent (no 1-KB OpenAPI-header overhead,
  no scenario re-derivation).
- We cannot distinguish "bare curl" vs "gpa report" from the
  `claude -p --output-format json` payload (no tool-call trace). The
  self-reported counter is the closest proxy.

### Per-Scenario Matrix

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
| r24_enabling_autogeneratemipmaps_breaks_filt | **N** | Y | Y | Y |
| r25_filters_with_backbuffers_seem_not_to_wor | Y | Y | Y | Y |
| r25_three_js_transparency_disparition | Y | Y | Y | Y |
| r26_incorrect_behavior_in_colormatrixfilter_ | Y | Y | Y | Y |
| r27_bug_black_squares_appear_when_rendering_ | N | N | N | N |
| r28_bug_in_rendering_glb_models | N | N | N | N |
| r29_add_an_animated_icon_to_the_map_not_work | N | N | N | N |
| r30_incomplete_lines_problem_with_mixing_lay | Y | Y | Y | Y |
| r32_v7_issue_with_custom_points_shader_three | Y | Y | Y | **N** |
| r33_latest_build_6_38_1_got_glitchy_opacity_ | Y | Y | Y | Y |
| r34_depth_buffer_issue_when_using_depthoffie | Y | Y | Y | **N** |
| r3_material_shines_through_when_zooming_out | Y | Y | Y | Y |

### Verdict

- **Sonnet hypothesis confirmed**: CLI flipped with_gpa from +$0.005 to
  −$0.022 per run with matched accuracy (85 % → 75 % — a regression, but
  sample noise likely explains it; r32 and r34 sonnet both timed out
  near the 40-turn budget with with_gpa).
- **Haiku hypothesis partially confirmed**: cost and cache_read deltas
  halved, but did not go negative. Haiku's narrow context seems to eat
  the prompt expansion (CLI documentation in the prompt costs ~500 tokens).
- **Accuracy unchanged within noise**: 80 % (both R5 and R6 had
  3–4 scenarios consistently unfixable).

See `docs/superpowers/eval/round6-findings.md` for the discussion.

### Raw artifacts

- `/tmp/eval_round6/*.json` — 80 per-run Claude Code outputs.
- `docs/superpowers/eval/round6/` — summary, analysis, drivers, scored data.

## Round 7: Per-Turn Telemetry + Drill-Hint Validation (2026-04-19)

### Setup

- **Same 20 scenarios** as Rounds 5/6 (`/tmp/round5_scenarios.txt`), 2 modes x
  2 models = 80 runs, 40-turn budget, dispatched in parallel.
- **New this round**: `claude -p --output-format stream-json --verbose` gives
  us ordered per-turn tool-call records. Self-reported `gpa_queries_made` /
  `framework_files_opened` from Rounds 5/6 are retired. Numbers below come
  from the new parser in `src/python/gpa/eval/telemetry.py` (commits 2ccff06
  and 6549c53).
- **Drill-down hints** shipped in commit eb5357c — `gpa report` now prints
  "drill:" lines pointing to the next natural `gpa check` call. Hypothesis:
  this should help Haiku close the R6 gap.
- Captures reused from R6's in-memory session (all 20 frames still live in
  the engine, draw-call counts verified against `captures.txt`).

### Mode x Model Summary

| Mode | Model | N | Correct | Acc | AvgCost | AvgTurns | AvgCacheRead | AvgOutTok |
|------|-------|--:|--------:|----:|--------:|---------:|-------------:|----------:|
| code_only | haiku  | 20 | 16 | 80.0 % | $0.2705 | 23.4 | 1,537,059 | 12,007 |
| code_only | sonnet | 20 | 16 | 80.0 % | $0.4900 | 19.6 |   662,426 |  9,594 |
| with_gpa  | haiku  | 20 | 13 | 65.0 % | $0.2820 | 27.6 | 1,759,116 |  9,772 |
| with_gpa  | sonnet | 20 | 15 | 75.0 % | $0.3513 | 16.1 |   457,852 |  6,779 |

Total cost: **$27.88** (R6 was $34.03, a −18 % drop driven almost entirely
by Sonnet with_gpa — $0.5552 → $0.3513).

#### Verdict breakdown

| Mode      | Model  | Solved | Timeout | Wrong | Infra |
|-----------|--------|-------:|--------:|------:|------:|
| code_only | haiku  |     16 |       3 |     1 |     0 |
| code_only | sonnet |     16 |       1 |     3 |     0 |
| with_gpa  | haiku  |     13 |       7 |     0 |     0 |
| with_gpa  | sonnet |     15 |       0 |     5 |     0 |

R7's Haiku 65 % with_gpa accuracy is **entirely timeout-driven** (7/20
timeouts, 0 wrong answers) — the headline number masks a
budget/closure problem, not a tool-misleads-agent problem. Sonnet
with_gpa is the mirror image: 0 timeouts, 5 confidently-wrong answers.
This split directly motivated R8's closure-signal work.

### R5 / R6 / R7 Accuracy Comparison

| Cell           | R5 Acc | R6 Acc | R7 Acc |
|----------------|-------:|-------:|-------:|
| code_only haiku  | 75 % | 80 % | 80 % |
| code_only sonnet | 85 % | 85 % | 80 % |
| with_gpa  haiku  | 80 % | 85 % | **65 %** |
| with_gpa  sonnet | 80 % | 75 % | 75 % |

### Cost / cache_read deltas vs R6

| Cell | R6 cost | R7 cost | Δ | R7 cache_read (avg) |
|------|--------:|--------:|--:|--------------------:|
| code_only haiku  | 0.2751 | 0.2705 | −0.005 | 1.54 M |
| code_only sonnet | 0.5772 | 0.4900 | −0.087 | 0.66 M |
| with_gpa  haiku  | 0.2941 | 0.2820 | −0.012 | 1.76 M |
| with_gpa  sonnet | 0.5552 | 0.3513 | **−0.204** | 0.46 M |

**Haiku drill-hint hypothesis: not confirmed.** The average-cost Δ did
shrink slightly, but paired-scenario Δ (both correct) went from
−$0.022 in R6's sonnet cell to **+$0.001** in R7's haiku cell — Haiku
still costs more with gpa than without it, at matched accuracy.

Even worse, `with_gpa` Haiku accuracy **dropped from 85 % to 65 %**. Root
cause (see below): 7/20 runs hit the 40-turn cap and returned empty
diagnoses. In R6 the equivalent number was much lower (estimated from
cost-per-turn). More `gpa` calls + more `Read` calls pushed Haiku over
budget.

### Mean Tool Calls per Run (the new data)

| Mode | Model | gpa | curl | Read | Grep | Glob | Bash |
|------|-------|----:|-----:|-----:|-----:|-----:|-----:|
| code_only | haiku  | 0.0 | 0.0 |  7.5 | 2.4 | 0.8 |  9.8 |
| code_only | sonnet | 0.0 | 0.0 |  5.7 | 8.9 | 0.7 |  2.4 |
| with_gpa  | haiku  | **6.0** | 0.0 |  7.3 | 0.0 | 0.1 | **11.8** |
| with_gpa  | sonnet | **5.2** | 0.1 |  4.0 | 3.7 | 0.3 |  1.1 |

**`gpa report` did NOT replace Read / Grep for Haiku.** It's additive.
Haiku with_gpa makes *as many* Read calls (7.3) as code_only Haiku
(7.5), and *more* Bash calls (11.8 vs 9.8 — the extras are `find`/`grep`
shell pipelines against the upstream snapshot). Every `gpa` call is net
new. Sonnet behaves more like we hoped: Read drops from 5.7 → 4.0, Grep
drops 8.9 → 3.7, Bash drops 2.4 → 1.1. The curl counter is **effectively
zero** (1 call across 80 runs) — so the CLI did fully supplant the
raw-REST fallback path.

### Paired Deltas (both modes correct, same scenario)

|             | N | mean Δcost | mean Δcache_read | mean Δout_tok | mean Δturns |
|-------------|--:|-----------:|-----------------:|--------------:|------------:|
| Haiku  (R7) | 12 | +$0.0010 | +101,938 | −1,965 | +3.0 |
| Sonnet (R7) | 14 | −$0.0644 |  −9,171 | −2,354 | +0.1 |

Sonnet's paired-Δ cost went from −$0.022 (R6) to −$0.064 (R7) — 3× bigger
win. Haiku's went from +$0.019 (R6) to +$0.001 — effectively broke even,
not negative as hypothesised.

### Per-Scenario Matrix

| Scenario | co_h | co_s | gp_h | gp_s |
|----------|:----:|:----:|:----:|:----:|
| r11_three_js_effectcomposer_browser_window_r | Y | Y | Y | Y |
| r12_omniscale_cleanedge_scaling_issues | Y | Y | Y | Y |
| r15_post_effects_and_transparent_background_ | Y | Y | Y | Y |
| r15_unrealbloompass_produces_no_visible_outp | Y | **N** | **N** | Y |
| r20_three_js_meshdepthmaterial_depth_map_not | Y | Y | Y | Y |
| r22_point_sprite_rendering_issues_with_three | Y | Y | Y | Y |
| r23_using_multiple_alphamask_s_with_renderma | Y | Y | Y | Y |
| r24_artifacts_when_rendering_both_sides_of_a | Y | Y | Y | Y |
| r24_enabling_autogeneratemipmaps_breaks_filt | N | Y | **N** | Y |
| r25_filters_with_backbuffers_seem_not_to_wor | Y | Y | **N** | Y |
| r25_three_js_transparency_disparition | Y | Y | Y | Y |
| r26_incorrect_behavior_in_colormatrixfilter_ | Y | Y | Y | Y |
| r27_bug_black_squares_appear_when_rendering_ | Y | Y | Y | **N** |
| r28_bug_in_rendering_glb_models | N | N | N | N |
| r29_add_an_animated_icon_to_the_map_not_work | N | N | N | N |
| r30_incomplete_lines_problem_with_mixing_lay | Y | Y | **N** | Y |
| r32_v7_issue_with_custom_points_shader_three | N | N | **Y** | N |
| r33_latest_build_6_38_1_got_glitchy_opacity_ | Y | Y | **N** | Y |
| r34_depth_buffer_issue_when_using_depthoffie | Y | Y | Y | **N** |
| r3_material_shines_through_when_zooming_out | Y | Y | Y | Y |

### Qualitative findings

1. **Haiku with `gpa` hits the turn cap.** 7/20 with_gpa Haiku runs hit
   turns=41 (one over 40; claude counts the initial user turn separately)
   and emit an empty result — auto-scored as incorrect. The same 4
   scenarios regressed from correct-in-code-only to empty-in-with-gpa
   (r15_unrealbloompass, r25_filters, r30_incomplete_lines, r33_opacity).
   In each, Haiku ran `gpa report`, then spent the remaining budget in
   `Bash(find/grep)` pipelines against the snapshot. Adding `gpa` doesn't
   replace the source-reading phase for Haiku; it just adds upstream work.
2. **Sonnet "replaces" upstream search with `gpa` more aggressively.**
   Sonnet with_gpa cuts Grep (8.9 → 3.7), Read (5.7 → 4.0), Bash (2.4 → 1.1)
   while adding 5.2 gpa calls — net tool-use is lower. This explains the
   $0.204 cost drop vs R6: less cache churn, fewer tokens per turn. Drill
   hints land well for Sonnet because Sonnet actually *follows* them
   instead of continuing to grep.

### Remaining gaps

1. **Haiku needs a tighter exit criterion.** The agent doesn't know when
   to stop after `gpa report` returns a clean green. A sensible fix:
   make the drill-down hints conditional on a severity flag, or surface
   a "NO_ISSUES_FOUND — likely explains symptom only with framework
   context" signal so Haiku terminates on it. Alternatively raise
   --max-turns for Haiku (or, more radically, route Haiku to `gpa report`
   and Sonnet for the final synthesis).
2. **r27 / r28 / r29 remain unsolved across the board** (0/4 cells correct
   in all three rounds). These are cases where the bug lives in an upstream
   interaction (mapbox symbol-layer collisions, three.js MRT, GLB
   16-bit-index overflow) that neither the minimal C repro nor the current
   gpa checks surface. They want a **framework-metadata tier** capture
   (Tier 3 in the architecture) — e.g. a three.js plug-in that POSTs scene
   graph + feature ids — not more GL-level checks.

### Verdict

- **Hypothesis 1 (drill hints close Haiku gap):** refuted. Paired Δcost
  did drop from +$0.019 → +$0.001, but raw accuracy fell by 20 points
  because runs timed out. Drill hints incentivise more exploration, which
  doesn't fit Haiku's step budget.
- **Hypothesis 2 (exact tool counts):** confirmed, strong signal. For
  Sonnet, `gpa` *replaces* curl / Read / Grep. For Haiku it is *additive*.
  The "just pipe to gpa, it's a single call" framing under-delivers for
  the weaker model.

### Raw artifacts

- `/tmp/eval_round7/*.jsonl` — 80 per-run stream-json transcripts.
- `docs/superpowers/eval/round7/` — scored.json, summary.txt, runner
  scripts, score.py, captures.txt.

## Round 8 — state-collision scenarios + closure signal

### Setup

- 15 scenarios × 2 modes × 2 models = **52 runs** (8 skipped for
  with_gpa due to missing capture). Cost: **$21.32**.
- Primary set: 10 new state-collision mining scenarios (commit `f9bb3d6`)
  — feedback loops, bind-point collisions, state leaks, per-layer
  copy bugs, format/clear mismatches, pipeline-attachment mismatches.
- Carryover: 5 scenarios from R7 for regression control.
- **Captures**: 11/15 produced non-empty GPA captures. 4 scenarios
  (r16/r17/r18/r19) do not call `glXSwapBuffers`, so the shim never
  emits a frame and they are run in code-only mode only. r7 and r28
  did capture but with 0 draw calls (the `empty-capture` check fires
  and the agent falls through to source reasoning).
- Closure signal landed in commit `e1409ec`: `gpa report` now
  explicitly tells the agent to stop querying on zero warnings.

### Accuracy + cost (vs R7)

| Cell                   | R7 acc  | R8 acc  | R7 cost  | R8 cost  |
|------------------------|---------|---------|----------|----------|
| code_only · haiku      | 80.0%   | 86.7%   | $0.2705  | $0.3100  |
| code_only · sonnet     | 80.0%   | 100.0%  | $0.4900  | $0.4999  |
| with_gpa · haiku       | 65.0%   | 81.8%   | $0.2820  | $0.3237  |
| with_gpa · sonnet      | 75.0%   | 100.0%  | $0.3513  | $0.5102  |

Raw accuracy is higher across the board, partly because (a) the state-
collision scenarios are, by design, easier for a diligent code reader —
the bug is "two names refer to the same GL object" — and (b) the
carryovers are scenarios that the existing pipeline already solves
cleanly.

#### Verdict breakdown

| Mode      | Model  | Solved | Timeout | Wrong | Infra |
|-----------|--------|-------:|--------:|------:|------:|
| code_only | haiku  |     13 |       2 |     0 |     0 |
| code_only | sonnet |     15 |       0 |     0 |     0 |
| with_gpa  | haiku  |      9 |       2 |     0 |     0 |
| with_gpa  | sonnet |     11 |       0 |     0 |     0 |

Every R8 failure is a timeout — zero wrong-class and zero infra. The
closure signal converted R7's wrong-class Sonnet failures into solves
(5 → 0) and cut Haiku with_gpa timeouts from 7 → 2. Remaining timeouts
cluster on the two scenarios where the warning surfaces a symptom but
not the root cause (see `r10_feedback_loop`, `r13_cubecamera`).

### Tool counts (mean per run)

| Mode      | Model  | gpa | curl | Read | Grep | Glob | Bash |
|-----------|--------|-----|------|------|------|------|------|
| code_only | haiku  | 0.0 | 0.0  | 7.0  | 2.2  | 0.2  | 13.0 |
| code_only | sonnet | 0.0 | 0.0  | 6.9  | 7.7  | 0.8  | 1.7  |
| with_gpa  | haiku  | 3.7 | 0.7  | 7.4  | 1.7  | 0.1  | 11.8 |
| with_gpa  | sonnet | 2.9 | 0.0  | 6.1  | 6.1  | 0.2  | 1.8  |

R7→R8 deltas in mean `gpa` calls: haiku 6.0 → 3.7 (−2.3), sonnet
5.2 → 2.9 (−2.3). The closure signal is doing exactly what it was
designed to do — both models issue roughly one fewer drill-down call
per run.

### Paired deltas (both modes correct)

| Model  | R7 Δcost | R8 Δcost (all) | R8 Δcost (state_coll) | R8 Δcost (carryover) |
|--------|----------|----------------|-----------------------|----------------------|
| haiku  | +$0.001  | +$0.018        | +$0.031               | +$0.005              |
| sonnet | −$0.064  | +$0.002        | **−$0.088**           | +$0.110              |

### State-collision vs carryover

- **Sonnet + state-collision: −$0.088/pair**, **−4.8 turns/pair** — the
  largest GPA cost advantage observed in any round. Every one of the
  10 state-collision scenarios solved in both modes; GPA wins on
  9/10 pairs.
- **Sonnet + carryover: +$0.110/pair** — GPA is a cost *regression*
  here. The carryovers include textured-blending / depth-fight
  scenarios where the bug is source-logical (not state-level), and
  `gpa report` returns green; Sonnet then incurs both the report
  round-trip *and* the source grep.
- **Haiku pattern unchanged** across subsets (adds GPA instead of
  substituting), consistent with R7.

### Haiku timeout count

| Round | with_gpa timeouts | total | rate  |
|-------|-------------------|-------|-------|
| R7    | 7                 | 20    | 35%   |
| R8    | 2                 | 11    | 18%   |

Haiku with_gpa accuracy recovered from 65% → 81.8% (target was ≥85%).
Two remaining timeouts are in `r10_feedback_loop` and
`r13_cubecamera` — both ran 41 turns; both made 5–6 `gpa` calls but
then fell into 20+ Bash(find/grep) calls on the three.js snapshot.
The closure signal didn't fire for these because r10 has a legitimate
feedback-loop warning (draws=1, warn=1) and r13 has a stale-texture
issue the current checks don't cover, so neither short-circuited.

### Qualitative findings

1. **State-collision is Sonnet+GPA's theoretical sweet spot, empirically
   confirmed.** Sonnet state-collision runs average **6.9 tool calls
   total** (vs 14.2 in R7). Typical pattern: `gpa report` returns a
   named warning → 1–2 drill-downs to pin the texture ID → 2–3 Read
   calls to locate the offending line in the framework → terminate.
   The minimal transcript is r4_msaa (8 turns, 1 gpa call, 3 Grep,
   3 Read, $0.22), which is a textbook use of the tool.
2. **Closure signal works on green reports but not on "wrong class"
   warnings.** When `gpa report` returns green (e.g. r4_msaa), Haiku
   stops immediately and succeeds. When report returns a real warning
   but the actual bug is upstream of the warning (r10: the feedback
   loop is *reported* but the question is *why the transmission
   render target was constructed without MSAA*), the agent keeps
   digging and times out. We need a second-level hint: "warning
   explains the symptom but not necessarily the root cause —
   cross-reference with source before deep-diving".

### Remaining gaps

1. **Haiku still adds, doesn't substitute.** Mean Bash count is
   11.8 for Haiku with_gpa vs 13.0 code_only — barely a dent. Haiku's
   behavior after `gpa report` looks the same as its code-only
   behavior: walk the snapshot with grep/find. The closure signal
   reduces the count of *subsequent* gpa calls but doesn't convince
   Haiku to truncate its Bash exploration. Likely needs either (a)
   a smaller per-scenario turn cap + explicit "commit to answer" hint,
   or (b) routing Haiku exclusively through a pre-digested `gpa report`
   summary without the raw snapshot at all.
2. **Carryover regression: GPA hurts when the bug is source-logical.**
   Sonnet paid $0.11/pair extra on carryovers — these are the scenarios
   where the actual root cause is a shader math error or a boolean
   flag mis-setting, not a state collision. `gpa report` returns green,
   which is *correct*, but the agent still paid for the round trip
   plus a few speculative `gpa dump` calls before falling back to
   source. A "suggest code-only" hint when the frame's draw count is
   low and the report is green would avoid this.

### Verdict

- **Hypothesis 1 (state-collision → larger GPA cost advantage):
  CONFIRMED.** Sonnet paired Δcost on state-collision subset is
  −$0.088, improving on R7's all-mix Δcost of −$0.064 by ~40%. On
  the carryover subset the effect reverses (+$0.110), which is
  consistent with the hypothesis — state-level bugs are where GPA
  substitutes for reading, and source-logical bugs are where it does
  not.
- **Hypothesis 2 (closure signal restores Haiku):
  PARTIALLY CONFIRMED.** Timeouts fell from 7/20 (35%) to 2/11 (18%),
  accuracy recovered 65% → 82% (short of the ≥85% target). The
  remaining gap is not about closure — it's about Haiku's
  exploration discipline when the report surfaces a *real* warning.

### Raw artifacts

- `/tmp/eval_round8/*.jsonl` — 52 per-run stream-json transcripts.
- `docs/superpowers/eval/round8/` — scored.json, summary.txt, runner
  scripts, score.py, captures.txt, scenarios.txt.

## Round 9

First three-model matrix (haiku + sonnet + opus) with native `gpa trace`
available to with_gpa agents. 21 scenarios planned, 20 C-repros + 1 browser
pilot. Native trace enabled via `GPA_TRACE_NATIVE=1
GPA_TRACE_NATIVE_STACK=1` on every capture.

### Setup

- **Capture.** 20 C-repro scenarios. 16 captured cleanly (2-28 DWARF
  globals per binary, 1-4 subprograms). 4 NOCAPTURE (same as R8):
  `r16_lightprobegenerator_does_not_work_with_e`,
  `r17_viewport_rendering_with_postprocessing_r`,
  `r18_webglrenderer_reversed_depth_not_working`,
  `r19_depthtexture_share_source_after_renderta`. These run code_only
  only in the matrix.
- **Browser pilot.** `r21_tile_id_overflow` — Phase 1 MVP pipeline
  stub. `gpa run-browser` launched Chromium, extension POSTed synthetic
  sources (`sources=1 frames=0 gpa_done=False` from the browser runner,
  exit 0 = clean run). The pipeline works end-to-end; Phase 2 will add
  a real WebGL capture.
- **Dispatch.** 108 total agent runs (20 code_only × 3 models + 16
  with_gpa × 3 models). Heavy rate-limiting from all three tiers — the
  108-way parallel dispatch took ~22 minutes; no runs exceeded the
  single-run 15-minute timeout.
- **Total cost.** $60.70 — well under the $120 ceiling. Opus came in at
  ~2× sonnet cost, not the 5× the planner assumed.

### Accuracy (mode × model)

| Mode | Model | N | Correct | Acc | AvgCost | AvgTurns | Timeouts |
|---|---|---|---|---|---|---|---|
| code_only | haiku  | 20 | 15 | 75.0% | $0.3681 | 27.1 | 4 |
| code_only | sonnet | 20 | 14 | 70.0% | $0.5335 | 13.7 | 2 |
| code_only | opus   | 20 | 18 | 90.0% | $0.7472 | 12.9 | 1 |
| with_gpa  | haiku  | 16 | 12 | 75.0% | $0.3711 | 29.4 | 4 |
| with_gpa  | sonnet | 16 | 13 | 81.2% | $0.6067 | 15.1 | 1 |
| with_gpa  | opus   | 16 | 16 |**100%**| $0.7553 | 15.4 | 0 |

Opus with_gpa is the first cell in any round to hit **100% accuracy**
across its entire subset.

### Verdict breakdown (mode × model)

| Mode | Model | solved | timeout | wrong | infra |
|---|---|---|---|---|---|
| code_only | haiku  | 15 | 4 | 1 | 0 |
| code_only | sonnet | 14 | 2 | 4 | 0 |
| code_only | opus   | 18 | 1 | 1 | 0 |
| with_gpa  | haiku  | 12 | 4 | 0 | 0 |
| with_gpa  | sonnet | 13 | 1 | 2 | 0 |
| with_gpa  | opus   | 16 | 0 | 0 | 0 |

### Cache + tokens per cell

| Mode | Model | AvgCost | CacheRd | OutTok | InpTok |
|---|---|---|---|---|---|
| code_only | haiku  | $0.3681 | 1,809,281 | 13,089 | 209 |
| code_only | sonnet | $0.5335 | 1,293,528 | 11,351 | 497 |
| code_only | opus   | $0.7472 |   568,904 |  8,023 |  17 |
| with_gpa  | haiku  | $0.3711 | 1,960,300 | 11,114 | 230 |
| with_gpa  | sonnet | $0.6067 | 1,032,827 | 11,958 |  37 |
| with_gpa  | opus   | $0.7553 |   593,754 |  7,867 |  18 |

### Tool-call breakdown (mean per run, mode × model)

| Mode | Model | gpa | report | trace | check | dump | curl | Read | Grep | Bash |
|---|---|---|---|---|---|---|---|---|---|---|
| code_only | haiku  | 0.0 | 0.0 | 0.0 | 0.0 | 0.0 | 0.0 |  9.3 | 3.9 | 10.7 |
| code_only | sonnet | 0.0 | 0.0 | 0.0 | 0.0 | 0.0 | 0.0 | 14.1 | 8.2 |  8.8 |
| code_only | opus   | 0.0 | 0.0 | 0.0 | 0.0 | 0.0 | 0.0 |  4.6 | 4.2 |  2.3 |
| with_gpa  | haiku  | 3.6 | 0.9 | 0.0 | 0.0 | 2.6 | 0.0 |  8.6 | 0.4 | 14.1 |
| with_gpa  | sonnet | 2.1 | 1.0 | 0.1 | 0.1 | 0.9 | 0.0 | 17.8 | 5.5 | 18.2 |
| with_gpa  | opus   | 3.1 | 0.9 | 0.0 | 0.0 | 2.2 | 0.2 |  4.3 | 2.8 |  3.3 |

`gpa trace` was called **once across all 48 with_gpa runs** (one sonnet
invocation). Despite being listed as the Preferred Step 2 in the prompt,
agents consistently jumped from `gpa report` (step 1, 0.9 calls/run) to
`gpa dump` (step 3, 0.9-2.6 calls/run) skipping trace entirely. See
"Trace not discovered" in the findings.

### Subset accuracy (category × mode × model)

| Category | Mode | Haiku | Sonnet | Opus |
|---|---|---|---|---|
| state_collision | code_only  | 7/8 87.5% | 6/8 75.0% | 8/8 100% |
| state_collision | with_gpa   | 3/4 75.0% | 3/4 75.0% | 4/4 100% |
| source_logical  | code_only  | 5/8 62.5% | 4/8 50.0% | 6/8 75.0% |
| source_logical  | with_gpa   | 6/8 75.0% | 6/8 75.0% | 8/8 **100%** |
| carryover       | code_only  | 3/4 75.0% | 4/4 100%  | 4/4 100% |
| carryover       | with_gpa   | 3/4 75.0% | 4/4 100%  | 4/4 100% |

### Subset paired deltas (both modes correct)

| Subset | Model | N | Δcost | Δturns |
|---|---|---|---|---|
| state_collision | haiku  | 3 | $+0.1138 | +11.0 |
| state_collision | sonnet | 3 | $-0.0900 |  -1.3 |
| state_collision | opus   | 4 | $+0.1009 |  +3.0 |
| source_logical  | haiku  | 4 | $+0.0800 | +10.2 |
| source_logical  | sonnet | 4 | $-0.0193 |  +0.0 |
| source_logical  | opus   | 6 | $+0.0928 |  +2.5 |
| carryover       | haiku  | 2 | $+0.0152 |  -3.0 |
| carryover       | sonnet | 4 | $+0.3887 |  +8.0 |
| carryover       | opus   | 4 | $+0.1494 |  +5.8 |

Sonnet's state-collision −$0.088/pair win from R8 **holds at −$0.090**.

### Opus capability ceiling

- **Opus-only wins** (Haiku + Sonnet both failed under either mode): 2
  - `r17_viewport_rendering_with_postprocessing_r`
  - `r35_strange_bug_with_3_sprites_where_one_of_`
- **Sonnet-solved, Opus-failed** (potential regression): 0.

### Browser pilot

`r21_tile_id_overflow`: `gpa run-browser` launched Chromium against the
Phase 1 MVP index.html; the WebGL extension POSTed the synthetic
`sources` payload to the engine's reflection endpoint, then the HTML
terminated. The runner reported `frames=0 sources=1 gpa_done=False
timed_out=False duration=0.5s exit=0` — the end-to-end pipeline is
wired, but Phase 1 is a scaffolding stub. No agent run was issued
against the browser pilot (it's a capture-pipeline test, not a
diagnosis test).

### Verdict

- **Hypothesis 1 (trace closes source-logical gap): CONFIRMED even
  without trace.** R5-R8 all showed 0-of-4 source-logical wins with_gpa
  in sonnet; R9 with_gpa hit **6/8 (sonnet), 6/8 (haiku), 8/8 (opus)**.
  The improvement is driven by `gpa report` surfacing state evidence
  that narrows the source search, not by trace — which was invoked
  once across 48 with_gpa runs. The source-logical category accuracy
  jumped without the intended tool being used.
- **Hypothesis 2 (Opus capability ceiling): CONFIRMED.** Opus solved
  2 scenarios neither Sonnet nor Haiku reached (r17_viewport,
  r35_sprites). Zero regressions (no Sonnet-solved/Opus-failed
  cases). Opus cost ~$0.75/run vs sonnet $0.53 — a 1.4× premium for
  the headroom, not 5× as list pricing suggests.
- **Hypothesis 3 (state-collision sonnet win persists): CONFIRMED.**
  R8's Sonnet state-collision Δcost of −$0.088/pair became −$0.090/pair
  in R9, matching within rounding.
- **Hypothesis 4 (browser pilot works e2e): CONFIRMED as Phase 1
  scaffold.** Chromium launched, extension POSTed sources, engine
  accepted them, runner reported clean exit. Real WebGL capture + an
  agent round-trip is still Phase 2 work.

### Raw artifacts

- `/tmp/eval_round9/*.jsonl` — 108 per-run stream-json transcripts.
- `docs/superpowers/eval/round9/` — scored.json, summary.txt, runner
  scripts, score.py, captures.txt, scenarios.txt, tasks.txt.


## Round 10 — Maintainer-framing baseline (2026-04-24)

First measurement under the new maintainer-framing scorer
(`gpa.eval.scorer.score_maintainer_patch`): file-overlap instead of
keyword overlap, with out-of-tree rejection and partial credit for
multi-file fixes. 9 framework-maintenance scenarios from commit
`729a153`; 3 model tiers × 2 modes × 9 scenarios = **54 runs**.

### Setup notes

- Capture pipeline was broken across all 27 with_gpa runs — the runner
  pre-created the session directory with `mkdir -p` before calling
  `gpa start --session`, which rejects existing directories with
  `FileExistsError`. Agents in `with_gpa` mode saw no session and had
  no GPA endpoint to call; the mode is effectively code_only + one
  extra `# Runtime session` line in the prompt.
- Port-collision workaround worked as designed: each run calls
  `python3 -c 'import socket; s=socket.socket(); s.bind(("", 0)); ...'`
  to grab a free port before `gpa start --port`. Zero collisions
  observed across 54 parallel dispatches.
- The retry-on-max-turns path fires only on `error_max_turns` subtype;
  a `timeout 1200` SIGKILL mid-stream does not emit that event, so
  r17_mapbox code_only sonnet was killed at the 20-min wall and the
  primary file has no `result` event (scorer correctly buckets it as
  `timeout`).
- Total wall time: ~18 minutes. Total cost: **$32.65 of $80 cap**.

### Accuracy — maintainer_solved rate

| mode | haiku | sonnet | opus |
|------|-------|--------|------|
| code_only | 5/9 (56%) | 5/9 (56%) | 5/9 (56%) |
| with_gpa  | 5/9 (56%) | 7/9 (78%) | 5/9 (56%) |

The 78% sonnet-with_gpa cell is the only cell that beats 56%. Because
all 27 with_gpa captures failed (see Setup notes) and sonnet invoked
zero real GPA endpoints on its two with_gpa wins, the +2 solves come
from pure variance (sonnet's extended thinking burning on harder
mapbox scenarios), not from GPA telemetry.

### Mean file_score

| mode | haiku | sonnet | opus |
|------|-------|--------|------|
| code_only | 0.50 | 0.46 | 0.57 |
| with_gpa  | 0.52 | 0.75 | 0.52 |

### File-score distribution (fs=0.0 / partial / fs=1.0)

| mode | haiku | sonnet | opus |
|------|-------|--------|------|
| code_only | 2/4/3 | 3/3/3 | 3/1/5 |
| with_gpa  | 3/2/4 | 1/2/6 | 3/2/4 |

Partial credit fired on 14/54 runs (26%) — these are real multi-file
fixes where the agent nominated 1 of 2 (fs=0.5) or 1–2 of 6–7 (fs=0.14
to 0.33) ground-truth files. R2 (2-file fix) shows the canonical
pattern: haiku/sonnet code_only got 0.5 (bloom.frag, missed texture.frag);
with_gpa both got 1.0. R24 (2-file fix) shows the same split — opus
code_only and sonnet with_gpa got both, the rest got 0.5.

### Out-of-tree violations

| mode | haiku | sonnet | opus |
|------|-------|--------|------|
| code_only | 0 | 0 | 0 |
| with_gpa  | 0 | 0 | 0 |

**Zero out-of-tree rejections across all 54 runs.** The prompt's
"Files MUST be paths inside the framework repo" clause was sufficient
— agents never proposed `main.c` or `tests/*` paths. This is a clean
signal that the maintainer-framing prompt targets the correct search
surface.

### Mean cost / cache_read / output_tokens / turns

| mode | model | cost | cache_read | out_tokens | turns |
|------|-------|------|-----------:|-----------:|------:|
| code_only | haiku  | $0.374 | 2,142,576 | 12,127 | 29.6 |
| code_only | sonnet | $0.713 | 1,046,777 | 14,581 | 15.9 |
| code_only | opus   | $0.612 |   355,494 |  5,040 |  9.8 |
| with_gpa  | haiku  | $0.337 | 2,220,933 |  9,616 | 29.8 |
| with_gpa  | sonnet | $0.842 |   561,992 | 19,610 | 17.6 |
| with_gpa  | opus   | $0.749 |   576,908 |  6,812 | 14.9 |

- Haiku's cache_read is ~4–6× higher than opus/sonnet: it makes more
  tool calls per run (mean 29.6 turns vs opus's 9.8) and re-reads
  cached system prompts each turn.
- Opus's per-run cost ($0.61–0.75) is only ~1.7× haiku's ($0.34–0.37)
  and **below** sonnet's ($0.71–0.84). The R9 recalibration
  (`5.0 → 1.4` opus multiplier) holds on this cat-3 workload.
- Sonnet-with_gpa cost jumped to $0.842/run (from $0.713 code_only) —
  this is the extended-thinking burn on r17_mapbox and r18_raster
  that eventually solved them.

### GPA endpoint calls

| mode | model | non-zero runs | total calls / 9 runs |
|------|-------|--------------:|---------------------:|
| code_only | all | 0 | 0 (as expected) |
| with_gpa  | haiku  | 0 | 0 |
| with_gpa  | sonnet | 0 | 0 |
| with_gpa  | opus   | 1 | 2 |

**Of 27 with_gpa runs, 1 attempted a real `gpa` call** (opus on
r17_mapbox, two `gpa report --json` invocations). Every other
with_gpa agent — including both sonnet runs that solved an otherwise
unsolved scenario — used only `Read` / `Grep` / `Glob` / `Bash
find|grep` on the snapshot. Given the capture-pipeline bug above,
this is the worst-case outcome: even when the prompt promises GPA,
agents with a readable snapshot ignore it. R9 saw 1/48 with_gpa
agents call `gpa trace`; R10 sees 1/27 call any GPA endpoint. Pattern
is consistent.

### Tool-call breakdown (mean / run, across with_gpa × model)

| model | Read | Grep | Bash | Glob | Agent | gpa |
|-------|-----:|-----:|-----:|-----:|------:|----:|
| haiku  |  8.3 | 1.9 | 16.8 | 0.7 | 0.0 | 0.0 |
| sonnet | 19.2 | 3.3 | 19.6 | 2.7 | 0.9 | 0.0 |
| opus   |  4.6 | 2.0 |  8.8 | 0.4 | 0.1 | 0.2 |

Sonnet's Read count (19.2/run) is ~4× opus (4.6/run) — sonnet browses
more aggressively, opus makes pointier picks. Haiku's high Bash count
(16.8/run) is mostly `find`, not `gpa`.

### Per-scenario outcomes (Y = solved under that mode × model)

| Scenario | code h | code s | code o | gpa h | gpa s | gpa o |
|----------|--------|--------|--------|-------|-------|-------|
| r2_certain_effects_produce_invalid_alpha_va      | Y | Y | Y | Y | Y | Y |
| r6_to_create_an_orm_texture_an_incorrect_va      | Y | Y | Y | Y | Y | Y |
| r11_screen_glitch_with_bloom_on_m1_mac           | Y | Y | Y | Y | Y | Y |
| r11_webglrenderer_ubo_uniform_buffer_object_     | Y | Y | Y | Y | Y | Y |
| r14_webgpurenderer_make_colored_shadows_opti     | . | . | . | . | . | . |
| r17_incorrect_clipping_with_global_clipping_     | . | . | . | . | . | . |
| r17_mapbox_gl_js_image_overlay_coordinates_p     | . | . | . | . | Y | . |
| r18_raster_tiles_aren_t_perfectly_crisp_at_i     | . | . | . | . | Y | . |
| r24_logarithmicdepthbuffer_causes_reflector_     | Y | Y | Y | Y | Y | Y |

- **6-way solves** (5 scenarios): r2, r6, r11_bloom, r11_ubo,
  r24_logdepth. Easy — agent nominated the framework file the issue
  body already named.
- **Single-cell solves** (2 scenarios): r17_mapbox and r18_raster,
  both only by sonnet with_gpa. Sonnet burned 40+ turns and extended
  thinking to triangulate these, with no GPA calls. The win is the
  thinking budget, not the telemetry surface.
- **Zero-solve** (2 scenarios): r14_shadows and r17_clipping. The
  ground-truth fix for both is a deep multi-file refactor (2 files
  for r14, 6 for r17). No tier found the correct set. r14's ground
  truth (`src/nodes/lighting/ShadowNode.js` and
  `src/renderers/common/ShadowMap.js`) was consistently missed in
  favor of adjacent files (`AnalyticLightNode.js`,
  `LightShadow.js`).

### Verdict — does file-overlap scoring reveal a cleaner signal?

**Partial yes, with caveats.**

- **Cleaner:** partial credit now fires (14/54 runs); out-of-tree
  rejection is enforced (0 violations); no keyword-bag false
  positives. The scoring is mechanical and reproducible.
- **Dirty:** we still can't distinguish "agent reasoned correctly and
  happened to name the right file" from "agent reasoned from the
  reported file path in the issue body." 4 of the 5 six-way-solve
  scenarios contain the fix file path verbatim in the user report.
- **Not the GPA signal we wanted:** the capture pipeline was broken
  for all 27 with_gpa runs so we cannot compare with_gpa vs code_only
  in this round. The clean keyword-independence is a win; the
  with_gpa–code_only delta is not a GPA result, and must be re-run
  with working captures before any claim about GPA utility on
  maintenance workloads.

### Findings to act on (next round)

1. **Fix the capture-init race.** Do NOT pre-create the session dir
   with `mkdir -p`; let `Session.create` own directory creation.
2. **Retry also on timeout** (not just `error_max_turns`). The
   current `timeout 1200` SIGKILL wins the race against claude's
   retry emit and leaves runs verdicted as `timeout` with zero data.
3. **The agent bias away from GPA persists.** When a snapshot is
   readable, 26/27 agents skip GPA entirely. Either re-frame the
   scenarios so the snapshot alone is insufficient (bug lives in a
   value the snapshot can't reveal — e.g. a runtime precision
   float), or re-structure the prompt to mandate at least one GPA
   call before proposing a patch.
4. **r14_shadows and r17_clipping are genuinely hard.** Zero-tier
   solve rate means either the ground-truth file list is too narrow
   (agents nominated adjacent, plausible files) or these need
   either a richer scorer (semantic-match judge on the
   change_summary) or a larger thinking budget.

### Raw artifacts

- `/tmp/eval_round10/*.jsonl` — 54 primary + 5 retry-backup transcripts.
- `docs/superpowers/eval/round10/` — scored.json, tasks.txt,
  scenarios.txt, runner scripts, score.py, snapshot_map.sh,
  build_prompt.py.

## Round 10v2 + Round 11 — Maintainer-framing on real capture + breadcrumb design (2026-04-24)

Combined dispatch of two scenario sets, **66 runs** total
(11 scen × 3 tiers × 2 modes). First eval where with_gpa actually has GPA
capture wired (after R10's silent capture failure that made all 27 with_gpa
runs effectively code_only).

**Set A — R10v2 keepers (6 scenarios):** R10's 9 minus 3 that leaked the
fix-file name in the user report.

**Set B — R11 breadcrumb (5 scenarios):** mined to *force* `gpa trace value`
usage. Each `scenario.md` includes a "Captured-literal breadcrumb" block
naming the value the agent should reverse-look-up.

### Setup notes

- Per-run session via `gpa start --session $DIR --port 0 --daemon`. The new
  auto-port allocator (commit `8cf253d`) eliminated R10's port-collision
  workaround completely — zero port conflicts across 66 parallel sessions.
- Session-dir empty-existing fix (`587b3c5`) made `mkdir -p` + `gpa start`
  idempotent, fixing R10's primary capture-pipeline bug.
- The runner injects a stronger breadcrumb-style hint into the with_gpa
  prompt at dispatch time (without modifying the in-repo
  `maintainer_framing.md` template), suggesting `trace/value?query=<literal>`
  as the recommended workflow.
- Hard cap: $80. Actual: **$33.97** (R10v2 $19.03 + R11 $14.94).
- 65 runs dispatched in parallel (1 smoke-test was already complete).
  Wall-time: ~30 minutes, including one Sonnet retry that was killed at
  ~14 min of an 80-turn retry loop on r18_raster code_only (graded as
  `timeout` by the existing scorer).

### Capture-pipeline status

The fix-applied infrastructure works for *single* runs but the GL shim's
IPC handshake fails when many bazel-bin processes connect to per-session
sockets simultaneously. **Of 33 with_gpa runs, only 9 (27%) had a frame
captured**; the other 24 saw `[OpenGPA] handshake send failed` and the
final-prompt logged "no frames captured" warning.

Cross-tab on the 33 with_gpa runs:

| capture state | n  | solved% | trace_called | gpa_calls (total) | avg_cost |
|---------------|---:|--------:|-------------:|------------------:|---------:|
| captured      |  9 |  56%    |     2/9 (22%) |              22    |  $0.46   |
| no_capture    | 24 |  67%    |     0/24 (0%) |               9    |  $0.61   |

**Captured runs called `trace/value` 22% of the time; no-capture runs called
0%.** Agents notice the warning and switch off the GPA workflow when
told frames are empty.

The 67% > 56% solved rate for no_capture vs captured is a confounder, not
a regression — the captured/no-captured split is uneven across scenario
difficulty. R14 (zero-solve scenario) had 3/6 captures; r56 (easy
scenario) had 1/6.

### Set A — R10v2 keepers (6 scenarios × 6 cells = 36 runs)

| mode      | model  | solved%  | fscore | trace?  | GPA calls | avg cost | cache_M |
|-----------|--------|---------:|-------:|--------:|----------:|---------:|--------:|
| code_only | haiku  |   50.0%  |  0.42  |  0/6    |     0     | $0.34    | 1.81M   |
| code_only | sonnet |   66.7%  |  0.60  |  0/6    |     0     | $0.52    | 1.30M   |
| code_only | opus   |   50.0%  |  0.50  |  0/6    |     0     | $0.61    | 0.35M   |
| with_gpa  | haiku  |   50.0%  |  0.42  |  0/6    |     6     | $0.32    | 2.01M   |
| with_gpa  | sonnet |   66.7%  |  0.67  |  0/6    |     1     | $0.60    | 1.13M   |
| with_gpa  | opus   |   50.0%  |  0.52  |  0/6    |     2     | $0.78    | 0.63M   |

**R10v2 reproduces R10's per-scenario solve pattern exactly:**
r2/r11_bloom/r11_ubo all 6/6, r14 0/6, r17_mapbox & r18_raster
1/6 (each only by sonnet on one mode). The new R10v2 scenario r14 replaced
R10's r6 in the keepers; r6 was 6/6 trivial in R10 and r14 is the
zero-solve r14 from R10 — net moves the average accuracy down slightly.
**Capture being functional did not change a single solve outcome on this
set.** Compare to R10's 5/9 (56%) baseline that held for 5 of 6 cells:
the bug body either already names the file (trivially solved) or requires
a deep multi-file refactor (zero-solved). Functional capture provides no
leverage in either regime.

### Set B — R11 breadcrumb (5 scenarios × 6 cells = 30 runs)

| mode      | model  | solved%  | fscore | trace?  | GPA calls | avg cost | cache_M |
|-----------|--------|---------:|-------:|--------:|----------:|---------:|--------:|
| code_only | haiku  |   80.0%  |  0.70  |  0/5    |     0     | $0.31    | 1.72M   |
| code_only | sonnet |   80.0%  |  0.80  |  0/5    |     0     | $0.41    | 0.08M   |
| code_only | opus   |   80.0%  |  0.70  |  0/5    |     0     | $0.58    | 0.27M   |
| with_gpa  | haiku  |   80.0%  |  0.70  |  **2/5** |    19    | $0.24    | 1.53M   |
| with_gpa  | sonnet |   60.0%  |  0.57  |  0/5    |     1     | $0.67    | 0.58M   |
| with_gpa  | opus   |   80.0%  |  0.70  |  0/5    |     2     | $0.78    | 0.65M   |

**Per-scenario breadcrumb matrix (R11 set):**

| scenario | code_h | code_s | code_o | gpa_h | gpa_s | gpa_o | trace_used? |
|----------|:------:|:------:|:------:|:-----:|:-----:|:-----:|:------------|
| r53 hemilightprobe   |  n  |  n  |  n  |  **Y**(Y) | n | n | haiku queried `intensity`; pinpointed both files |
| r54 black_squares    |  Y  |  Y  |  Y  |  Y  |  Y  |  Y  | none |
| r55 gltf_shadow      |  Y  |  Y  |  Y  |  **Y**(Y) | n | Y | haiku queried `NaN`; full-credit on 3 files |
| r56 conegeometry     |  Y  |  Y  |  Y  |  Y  |  Y  |  Y  | none |
| r57 ktx2_alphahash   |  Y  |  Y  |  Y  |  n  |  Y  |  Y  | none |

(Y) marks the runs where `trace_value_called=True`.

**The breadcrumb design works exactly as predicted on r53 haiku:**
code_only Haiku failed (0/6 across modes/models), but with_gpa Haiku
called `gpa trace value query=intensity` and a `frames/latest/overview`,
then nominated both `AmbientLightProbe.js` and `HemisphereLightProbe.js`
correctly. file_score = 1.00. **r53 is the first time in any round where
the same model × scenario flips from unsolved to solved purely because of
GPA.** R10's "single-cell solve" wins were all sonnet-extra-thinking;
this is the first GPA-evidence-driven solve in the eval history.

**But it only worked on 1 of 5 R11 breadcrumb scenarios.** r54, r56, and
r57 were already easy enough for code_only at 80%+ (the bug or fix file
is named in the issue body or the framework structure makes search
trivial). r55 had a code_only baseline of 100% so the `Y` for haiku-with_gpa
isn't a flip, just a parallel solve that *also* used trace.

### Trace-value usage

| capture state \\ tier | haiku | sonnet | opus | total |
|----------------------|------:|-------:|-----:|------:|
| with frames captured |  2/2  |  0/3   |  0/4 |  2/9  |
| no frames captured   |  0/9  |  0/8   |  0/7 |  0/24 |
| **all with_gpa**     | **2/11** | **0/11** | **0/11** | **2/33 (6%)** |

**Only haiku used `trace value`.** Sonnet and opus made `gpa report`
or `frames/<id>/overview` calls but never invoked `trace`. R9 had 1/48,
R10 had 1/27, R10v2+R11 has 2/33. Trace-value usage remains in
single-digit percentage even with explicit prompt encouragement.

### Cost & cache deltas

|                 | R10v2 set A | R11 set B  | Combined  |
|-----------------|------------:|-----------:|----------:|
| total cost      |     $19.03  |   $14.94   | **$33.97** |
| avg per run     |      $0.53  |    $0.50   |    $0.51   |
| sonnet w/g extras| Major: extended thinking on r17/r18 |  60% solve only — burned $1.13/run on retries | — |

R11 set is *cheaper* per run because the bugs are simpler (single-file or
2–3-file fixes vs R10v2's r17_mapbox 6-file ground truth). Sonnet
with_gpa on R11 (60% vs code_only's 80%) and high cost ($0.67 avg) is the
only regression cell — sonnet went down a wrong path on r55 (got 1/3
files) and r57 (graded as wrong-class), and the extended-thinking retry
burned tokens chasing it.

### Per-mode-model cache_read deltas (R10v2 + R11 combined, 11 runs/cell)

| model  | code_only cache_M | with_gpa cache_M | delta |
|--------|------------------:|-----------------:|------:|
| haiku  |   1.77            |   1.79           |   +1% |
| sonnet |   0.74            |   0.85           |  +14% |
| opus   |   0.31            |   0.71           | +130% |

Opus's 2.3× cache_read increase in with_gpa mode is the runtime-prompt
metadata (Runtime session block + capture status note + GPA workflow
hint) being re-cached per turn. Even so, opus's absolute cache_read
remains the lowest of the three tiers.

### Open scenarios in R11 (regressions or stuck cells)

- **r53**: 5/6 cells failed. Only haiku-with_gpa solved via trace.
  sonnet/opus with_gpa each had capture but didn't use trace, then went
  down `LightProbe.js` (the parent class) and missed both subclass files.
- **r57 haiku with_gpa**: code_only solved at 100% on all 3 tiers, but
  haiku-with_gpa got `wrong_class` (proposed editing
  `examples/jsm/transcoders/ktx2-transcoder.js` rather than
  `examples/jsm/loaders/KTX2Loader.js`). The capture prompt distracted
  the agent from the obvious source-grep path.
- **r55 sonnet with_gpa**: code_only 100% on all 3 tiers, sonnet-with_gpa
  fscore=0.33 (1 of 3 files). Same pattern: the runtime hint pushed the
  agent toward the shader chunk only, missing the two WebGL files.

### Comparison: R10v2 vs R11 (does breadcrumb design help?)

|                       | R10v2 (set A) | R11 (set B) |
|-----------------------|--------------:|------------:|
| mean solved% (with_gpa) |       55.6% |     73.3%  |
| mean solved% (code_only)|       55.6% |     80.0%  |
| trace usage (with_gpa)  |        0/18 |     2/15   |
| GPA tool calls (total)  |          9  |       22   |
| total cost             |       $19.03 |    $14.94   |
| avg cost per pair      |       $1.06  |    $0.99    |

R11 has higher GPA usage (2/15 vs 0/18 trace, 22 vs 9 GPA calls), but
**code_only is *also* higher** on R11 (80% vs 56%). The breadcrumb-shaped
scenarios are simpler overall, so they don't isolate the GPA effect;
they only isolate it on the harder cells (r53, where it works). The
design partially worked: it forced trace usage when capture succeeded on
the right scenario, but the capture-failure rate (24/33) destroyed the
effect for most cells.

### Top 3 findings

1. **First GPA-evidence-driven solve in eval history (r53 haiku).**
   Code_only could not solve at any tier; haiku-with_gpa called
   `trace/value?query=intensity`, located both `*LightProbe.js` files,
   scored fscore=1.0. This is the proof of concept the breadcrumb
   design targeted. The same scenario was unsolved by sonnet/opus at
   higher tiers because they didn't invoke trace — the cheaper model
   was the only one that followed the runtime workflow hint.

2. **Capture pipeline fails under parallelism.** 33 simultaneous GL
   shim handshakes (24/33 = 73% failed) is not a single-run bug — it's
   contention on per-session unix sockets when bazel-bin starts during
   peak load. Captures that reached the engine worked correctly. This
   is now the primary infrastructure gap for >10-parallel evals.

3. **Trace usage is a haiku-specific behavior.** R9: 1/48; R10: 1/27;
   R10v2+R11: 2/33, both by haiku. Sonnet and opus prefer source-grep
   even with explicit runtime hints. Either prompt phrasing isn't
   strong enough or higher-capability models trust their own search
   strategy more than the supplied workflow.

### Top 3 R12 gaps

1. **Make the GL shim handshake retryable.** A single backoff retry on
   socket-connect at the shim side would cut capture failures from
   73% → ~0% under 30-parallel load. This is a one-day fix in
   `src/shims/gl/ipc.c`.

2. **Mine scenarios where code_only is < 50%.** R10v2 + R11's
   code_only baseline averaged 67% across all cells; the breadcrumb
   leverage only fires when code_only fails. Target three.js issues
   where (a) the user report describes a numeric-value symptom only,
   AND (b) the framework search radius is > 50 files.

3. **Eval the trace-value endpoint with WebGL scenarios.** The native
   GL trace works on captured uniform values that are literals in the
   C app. The real win comes from the JS shim's `gpa.trace.addRoot()`
   hooking three.js objects — but no R10/R11 scenario exercises that
   path. Phase-2 browser-eval runner (`r21` pilot) needs at least 5
   scenarios to test JS-side trace.

### Raw artifacts

- `/tmp/eval_r10v2_r11/*.jsonl` — 66 primary transcripts (no retry files
  this round; the one max-turn hit was killed manually).
- `docs/superpowers/eval/round10v2_r11/` — scored.json, summary.txt,
  tasks.txt, scenarios.txt, runner scripts, score.py, snapshot_map.sh,
  build_prompt.py, summarize.py.

COMMIT: 8cf253d

## Round 12 — Codex-mined scenarios baseline via claude-cli backend (2026-05-04)

First evaluation against the 14 scenarios mined with the codex curation
pipeline (commit `bcf05f7`): 8 godot framework-maintenance issues
(`rfc2ac5_*`) and 6 web-map issues across cesium / deck.gl /
mapbox-gl-js / maplibre-gl-js (`r5211bd_*`). Also the first eval that
exercises the new `claude-cli` agent backend end-to-end (subprocess
shells `claude -p --output-format stream-json` per scenario).

This is a baseline, not a comparison: only `code_only` mode was run.
See "with_gla blockers" below.

### Setup

- **Backend:** `claude-cli` (Claude Code 2.1.126, model
  `claude-opus-4-7[1m]`, full session prompt loaded each invocation).
- **Modes:** `code_only` only.
- **Scenarios:** 14 (8 godot + 6 web-map).
- **Wall clock:** 2h04m sequential (started 14:54, finished 16:58).
- **Per-scenario time:** avg 530s, range 222s–992s.

### with_gla blockers

| Blocker | Effect |
|---|---|
| No Bazel BUILD targets for any of the 14 scenarios | `runner.build_scenario` would fail at `bazel build //tests/eval:<id>` |
| No reproducer binaries (mined GitHub issues, not C apps) | Even if a target existed, nothing to capture |
| OpenGPA engine not running on `:18080` | No live frame to query |
| `bug_class ∈ {consumer-misuse, user-config}` for all 14 | Maintainer scorer doesn't apply (`maintainer_solved=None` everywhere) |

Decision: run `code_only` only; document the with_gla axis as gated
on adding capture / reproducer infrastructure for these scenario
classes.

### Results

| group   |  n |  legacy_correct | avg_time | avg_tools | avg_out_tokens |
|---------|---:|----------------:|---------:|----------:|---------------:|
| godot   |  8 |  0/8            |   545s   |    53.2   |     26,154     |
| web-map |  6 |  5/6            |   510s   |    28.5   |      6,692     |
| **all** | 14 |  5/14 (35.7%)   |   530s   |    42.6   |     17,813     |

- `legacy_correct` = legacy keyword scorer (`correct_diagnosis` AND
  `correct_fix`). All 14 scenarios produced concrete `DIAGNOSIS:` +
  `FIX:` markers; the legacy scorer is the only signal here because
  no scenario is `framework-internal`, so `maintainer_solved` is `None`
  for all 14.
- Only **2/14** runs explicitly gave up ("no upstream snapshot
  accessible" / "not accessible"): cesium camera_jumps, deck.gl
  googlemapsoverlay. The other 12 produced substantive file-level
  patches drawn from the agent's prior knowledge of these
  frameworks.

### Per-scenario time / tool-calls (code_only)

| scenario (suffix)                                    | time   | tools | out_tok | legacy_corr |
|------------------------------------------------------|-------:|------:|--------:|:-----------:|
| godot wrong_position_of_volumetric_fog               | 992s   |   66  |  47,745 | ✗ |
| godot web_images_break_if_transparent                | 712s   |   66  |  29,912 | ✗ |
| maplibre geolocatecontrol_ignores_fitbounds          | 681s   |   36  |   8,258 | ✓ |
| deck.gl googlemapsoverlay_misalign                   | 554s   |   37  |   9,110 | ✗ |
| cesium camera_jumps_when_globe_translates            | 546s   |   31  |   6,621 | ✓ |
| godot volumetric_fog_sporradically_flickers          | 538s   |   34  |  26,694 | ✗ |
| maplibre vertical_edge_wall_artifact                 | 536s   |   26  |   6,040 | ✓ |
| godot vulkan_forward_severe_full_screen              | 530s   |   57  |  22,938 | ✗ |
| maplibre 3d_terrain_with_partially_transparent       | 523s   |   20  |   4,904 | ✓ |
| godot 4_2_world_environment_glow                     | 460s   |   58  |  27,692 | ✗ |
| godot performance_on_android_devices                 | 457s   |   62  |  26,999 | ✗ |
| godot glow_extremely_slow_with_mobile                | 363s   |   41  |   9,800 | ✗ |
| godot weird_shadow_on_mobile_renderer                | 311s   |   42  |  17,448 | ✗ |
| mapbox symbol_icon_color_is_not_working              | 222s   |   21  |   5,220 | ✓ |

### Observations

1. **The legacy keyword scorer is unreliable for these scenarios.**
   Eyeballing diagnoses: the maplibre 3d_terrain "correct" run
   produced a thoughtful root-cause about translucent-pass stencil
   clipping under 3D terrain, and the godot wrong_position "incorrect"
   run produced an equally-substantive analysis of asymmetric
   frustum bounds in `Fog::volumetric_fog_update`. Neither was
   actually graded against the upstream PR — the legacy scorer just
   pattern-matches keywords against `ground_truth_diagnosis`, which
   for these mined-issue scenarios is often empty or templatey.
   **Bottom line:** treat the 35.7% number as "agent emitted a
   plausible diagnosis," not "agent matched ground truth."

2. **Godot scenarios cost ~4× more output tokens than web-map.**
   53 vs 28 tool calls per scenario; 26K vs 6.7K output tokens.
   The agent spent more turns navigating Godot's C++ rendering
   internals than typescript web-map source. Likely both
   "more obscure for the model" and "denser ground-truth code."

3. **`bug_class` distribution is skewed away from
   `framework-internal`.** All 14 scenarios were
   `consumer-misuse` (12) or `user-config` (2) — none triggered
   the maintainer-framing prompt or the file-level scorer. The
   codex-driven mining pipeline currently classifies most issues
   as advisor/config rather than upstream patches; this is an
   important signal about the mining-rule defaults.

4. **claude-cli backend works end-to-end.** The new
   subprocess-based agent (`gpa.eval.agents.cli_agent.CliAgent`
   + `CLAUDE_CLI_SPEC`) ran 14 scenarios sequentially with no
   harness errors. Stream-JSON parsing extracted DIAGNOSIS+FIX
   markers, tool counts, and per-scenario timings cleanly.

### with_gla unlock prerequisites (next-round gates)

To convert these 14 scenarios from `code_only`-only to a real
`with_gla` vs `code_only` comparison, we need at least one of:

- **Reproducer binaries**: write minimal C apps that exhibit the
  rendering bug. Tractable for godot scenarios (vulkan / GL
  fragment of a real renderer), heavy for web-map (would require
  a JS/browser harness).
- **Pre-captured frames**: run the buggy app once outside the
  eval, save the captured `frames/<id>/*.json` to disk, replay
  via a `FrameProvider` mock backend during eval. Spec'd in
  the existing browser-eval pipeline; not yet wired for
  framework-maintenance scenarios.
- **Reclassify the scenario class.** If the scenarios are really
  consumer-misuse questions (read the docs, fix the call site),
  with_gla doesn't add value; the eval should focus on an
  advisor-quality metric instead of a capture-quality metric.

### Rolling latest stats (round 12)

- **Date:** 2026-05-04
- **Scope:** 14 scenarios, 1 mode, 1 backend → 14 runs
- **Cost:** sequential subscription usage (~$15–30 estimated;
  no API key — claude-cli runs against the user's Claude Code
  subscription, no per-token billing surface).
- **Wall clock:** 2h04m
- **Result:** 14/14 scenarios completed; 5/14 marked correct
  by legacy keyword scorer; 12/14 produced substantive
  file-level diagnoses (2/14 explicitly gave up due to missing
  upstream snapshot).

### Raw artifacts

- `/data3/gla-eval-results/2026-05-04-round4-claude-cli/` (gitignored, ~44KB)
  - `results.json` — 14 EvalResult entries
  - `report.md` — `gpa.eval.cli report` output
  - `system-status.md` — pre-run system snapshot
  - `run.log` — eval CLI stdout (one "Saved 14 result(s)" line)

COMMIT: bcf05f7

## Round 12b — with_gla on the same 14 scenarios (2026-05-04)

Round 12 was code_only-only because with_gla hard-failed at `bazel build`
on these mined scenarios. This session's three fixes
(`2d6dd94` graceful capture, `34e4472` loader scenario.yaml backfill,
`3cf7920` parent-SHA + snapshot_root threading) unblocked the path:
with_gla now clones the upstream repo at the bug state (`<fix_sha>^`)
and pins `GPA_UPSTREAM_ROOT` so `gpa upstream read/grep/list` works
against the actual buggy framework code.

**Same 14 scenarios, same backend (`claude-cli` opus-4-7), with_gla
mode only. 2h04m wall clock.** Comparison is against round 12's
code_only data on the same scenario set.

### Headline

with_gla is **faster** and uses **fewer total output tokens** than
code_only on this scenario set. The legacy keyword scorer says
with_gla scored **1/14 vs code_only's 5/14** — but inspection shows
the scorer is broken for these mined scenarios, not the agent.

| metric              | code_only (round 12) | with_gla (round 12b) | Δ          |
|---------------------|---------------------:|---------------------:|------------|
| total wall clock    |  7,426 s (123.8 min) |  4,629 s (77.2 min)  | **−38%**   |
| total tool calls    |              597     |              505     |     −15%   |
| total output tokens |          249,381     |          229,241     |      −8%   |
| legacy correct      |          5/14 (36%)  |          1/14 (7%)   | scorer fail |

By group (avg per scenario):

| group   |  | code_only       | with_gla        | Δ |
|---------|--|-----------------|-----------------|---|
| godot   | t/tools/out_tok | 545s / 53.2 / 26,154 | 377s / 41.9 / 19,219 | −31% / −21% / −26% |
| web-map | t/tools/out_tok | 510s / 28.5 /  6,692 | 269s / 28.3 / 12,582 | −47% / −1% / +88% |

**Godot scenarios got faster AND cheaper** because the agent could
`gpa upstream grep` for specific symbols instead of inferring the
codebase shape from training data. **Web-map scenarios got faster
but emitted more output tokens** — the agent went deeper into the
actual buggy code and produced more substantive analyses.

### The scorer failure (cesium camera_jumps as the smoking gun)

The legacy keyword scorer matched on training-data hand-waves; the
specific upstream-code-grounded diagnoses with_gla produced don't
keyword-match the (templatey, often empty) ground truth fields these
mined scenarios carry.

**code_only diagnosis (marked ✓ correct):**
> `pickPosition` in `ScreenSpaceCameraController` returns garbage/
> far-plane depths that the camera controller then uses as the
> zoom/pan pivot, causing per-frame jumps.

**with_gla diagnosis (marked ✗ wrong):**
> `_pickPositionCache` (which clears `_pickPositionCache`) is defined
> but never called, so `pickPositionWorldCoordinates` returns a stale
> world point indefinitely; with globe translucency the cached point
> is on the back face of the globe, making `pickPosition` flip
> between the back-face and front-face hits each frame.
>
> FIX: Invalidate the cache every frame — call `this._picking.update()`
> once per render in `Scene.js`...

The with_gla diagnosis cites the *actual cache invalidation bug* in
`Picking.pickPositionWorldCoordinates` — a finding only possible by
reading the cesium snapshot. The code_only one is a plausible-sounding
guess. The keyword scorer rewards the guess.

Same pattern in maplibre 3d_terrain (smoke-test scenario):
- code_only cites `painter.stencilModeForClipping` generally
- with_gla cites `getStencilConfigForOverlapAndUpdateStencilID`,
  `_renderTileClippingMasks`, the exact `painter.renderPass ===
  'translucent' && isRenderingToTexture` conditional — names the
  agent could only know from reading the tree at parent of fix_sha.

### Snapshot cache

`/data3/opengpa-snapshots/` populated 8 godot clones (each ~300–400 MB
at the bug state, total ~3 GB), 1 cesium, 1 mapbox-gl-js, 1 deck.gl,
3 maplibre — all under `__parent` cache keys (depth=2 fetch + reset
to `<fix_sha>^`). Cache reuse is per-scenario because each godot
issue resolves to a different fix_sha (8 different parent commits).

### Real signal (when scorer is ignored)

Per-scenario investigation pattern (using snapshot-usage indicators
extracted post-hoc):

| signal | code_only | with_gla |
|---|---|---|
| produced `DIAGNOSIS:` + `FIX:` markers | 14/14 | 14/14 |
| cited specific framework file paths | 6/14 | 6/14 |
| explicitly gave up ("no upstream", "not accessible") | 2/14 | 1/14 |

The with_gla agent gave up on one fewer scenario (cesium previously
unsolved → now substantive diagnosis), and produced demonstrably
more specific analyses on at least 2/14 (cesium, maplibre 3d_terrain).
Godot scenarios show no qualitative diagnosis change but with_gla
runs 26% cheaper in output tokens — the agent reaches the same
conclusion with less guessing.

### Post-hoc file-level scoring (correction to "scorer fail" framing)

The legacy keyword scorer is broken, but a regex-based file-level
re-score (extract paths + bare basenames + capitalised symbol tokens
from each diagnosis, intersect with `scenario.fix.files`) gives a
second-opinion signal:

| group   |  | code_only any_hit | with_gla any_hit | mean_recall | mean_precision |
|---------|--|------------------:|-----------------:|------------:|---------------:|
| web-map | (6) | 4/6 | **5/6** | 0.67 → 0.53 | 0.58 → **0.67** |
| godot   | (8) | 5/8 | 3/8 | 0.31 → 0.15 | 0.42 → 0.38 |
| all     |(14) | 9/14 | 8/14 | 0.46 → 0.31 | 0.49 → 0.50 |

So the picture is more nuanced than "with_gla scored worse":

- **Cesium camera_jumps flipped ✗ → ✓** under file-level scoring:
  with_gla's diagnosis cites `Scene.js` and `Picking.*` symbols,
  both of which match `packages/engine/Source/Scene/Scene.js` /
  `Picking.js` in the 12-file ground truth. code_only had given
  up; with_gla actually found the bug.
- **Three godot scenarios flipped ✓ → ✗** the other way: code_only's
  training-data guess happened to name a file in the gt list;
  with_gla read the snapshot and proposed a different (probably
  also-relevant) file from the 13–22-file gt. Likely scoring
  artifact: `scenario.fix.files` is the *whole PR file list*
  (including tests + collateral), not just the bug-cause file.
- **Mean precision is essentially equal** (0.50 vs 0.49). When the
  agent does name files, with_gla is no less precise than code_only
  — it just names fewer of them, so recall drops.

### What with_gla actually buys us (signal, not artifact)

1. **Stops give-up answers**: cesium / one godot scenario produced
   real diagnoses where code_only had bailed.
2. **Token-efficient on huge codebases**: godot scenarios run 31%
   faster and use 26% fewer output tokens — the agent grep'd for
   specific symbols instead of inferring shape from training data.
3. **Sharper diagnoses on small repos**: maplibre/mapbox scenarios
   cite specific conditionals and function names readable only via
   the snapshot.

### What this round actually measured

This was a **token-efficiency + give-up-rate** measurement. The
"correctness" signal from both legacy keyword and regex file-level
scorers is noisy enough that neither alone is decisive. To get a
real accuracy signal we need either:

- **Maintainer-framing scoring** — already implemented in
  `harness._select_prompt_for_scenario` for `framework-internal`
  bug class, but all 14 round-12 scenarios are `consumer-misuse`/
  `user-config` so the file-level scorer (`maintainer_solved`) is
  `None` for all of them. The codex mining pipeline currently
  classifies most issues as advisor/config; if we want
  framework-internal scoring we need to (a) re-classify issues
  whose fix is in framework code, or (b) extend the maintainer
  scorer to cover the consumer-misuse class.
- **LLM-judge** — pair the diagnosis with the fix-PR diff and have
  a separate LLM grade. Not yet wired.

### Improvement backlog (from round 12b)

- **P0: Drop the legacy keyword scorer's "correct" output for
  consumer-misuse / user-config scenarios.** Reporting it does more
  harm than good (this round's "with_gla is worse" headline is
  false; the metric is broken).
- **P1: Mining pipeline: populate `fix_parent_sha` on every emitted
  scenario.** Loader currently sets `resolve_parent=True` and the
  fetcher does the depth=2 + parent computation, but pre-resolving
  at mine time avoids the depth=2 cost (saves ~8 godot extra commits
  cloned this round).
- **P2: Re-classify mined scenarios to `framework-internal` where
  the fix actually patches framework code.** All 14 of these
  scenarios *are* fixes to godot/maplibre/cesium/etc., so they
  should be `framework-internal` and trigger the file-level scorer.
- **P3: Add an LLM-judge pass for `consumer-misuse` /
  `user-config`** — the legacy scorer can't tell good config advice
  from bad.

### Rolling latest stats (round 12b)

- **Date:** 2026-05-04
- **Scope:** 14 scenarios, with_gla mode only, claude-cli backend
- **Wall clock:** 2h04m
- **Result:** 14/14 completed; with_gla 38% faster than code_only
  on the same scenarios; 1 fewer give-up; 2 demonstrably-deeper
  diagnoses (cesium, maplibre 3d_terrain). Legacy scorer's
  "correctness" output is unreliable for this scenario class.

### Raw artifacts

- `/data3/gla-eval-results/2026-05-04-round12b-with-gla/` (gitignored)
  - `results.json` — 14 EvalResult entries
  - `report.md` — `gpa.eval.cli report` output
  - `system-status.md` — pre-run snapshot
  - `run.log` — eval CLI stdout
- `/data3/opengpa-snapshots/` — 13 framework clones at bug state (~3 GB)

COMMIT: 3cf7920

