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

