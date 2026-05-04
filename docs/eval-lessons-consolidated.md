# OpenGPA Eval — Consolidated Lessons

*Rolling consolidation across eval rounds 1–6; last updated 2026-04-19.*

This is the single prioritized reference for "what worked, what didn't, what's
next" across all OpenGPA eval rounds. It supersedes the per-round journal for
decision-making purposes. Source docs (`eval-results.md`, `eval-lessons.md`,
`round[4-6]-*.md`, `eval-next-steps.md`) remain as historical record.

See also `docs/superpowers/eval/coverage-gaps.md` (auto-generated, do not edit).

---

## What's true across rounds

1. **Hint-stripped minimal reproductions are too easy.** (R1–R3) 100%/100%
   accuracy for both modes on single-file scenarios with `// BUG:` style
   comments, and even after stripping, the bug-*is*-the-codebase in 200-line
   reproductions. OpenGPA's value only becomes measurable when agents must
   navigate a real upstream framework snapshot (kicked in at R4).

2. **Scenario description quality + upstream source access dominates accuracy.**
   (R5, R6) With cleaned `## User Report` / `## Ground Truth` split and a
   full framework snapshot, both modes get 75–100 % on most scenarios. GPA
   is not a raw-accuracy lever on this setup; it's a *cost* lever.

3. **A stub `main.c` is a dead scenario for `with_gpa`.** (R4 r27, R5 r29)
   If the capture contains zero draw calls or undifferentiated state, the
   agent gets no signal and invents plausible-but-wrong hypotheses. A
   scenario qualifies for eval only when its captured frame has ≥1 draw call
   and ≥1 non-default pipeline-state field. R5's r29 added a new failure
   mode: segfault before first swap (fixed in `90d07ff`).

4. **Triage by scope, not location.** (R4 L1) Every visible rendering bug
   manifests as observable state somewhere in the capture — wrong uniform,
   missing draw call, unexpected binding. Do not exclude scenarios just
   because the root cause lives in JS/framework logic upstream of GL; the
   agent's job is to trace the anomaly backwards from GPA's runtime evidence.

5. **Live runtime evidence can be a red herring.** (R5 r27) When the visible
   artifact has multiple pathways (e.g. NaN→black patches from anisotropic
   GGX), `with_gpa` agents over-weight the vivid runtime signal and anchor
   on a plausible but wrong local fix, while code-only agents are forced to
   read the shader and reason about the semantic diff. This is the first
   round where GPA *regressed* accuracy — 0/4 on r27 with_gpa vs 2/2
   code-only. Mitigation: richer runtime evidence that actually
   discriminates between hypotheses (NaN-origin instruction traces), or
   prompting that forces runtime+source triangulation.

6. **The Haiku+GPA force-multiplier seen in R4 did not replicate at R5 scale.**
   R4 (n=4) showed Haiku+GPA 3/4 vs Haiku+code_only 2/4, and the rescue
   cell (r10 feedback loop) was exactly the "no heuristic required" case.
   R5 (n=20) showed Haiku code_only 20/20 and Haiku with_gpa 17/19 — the
   small-model rescue effect washed out. Working interpretation: R4's
   force-multiplier was scenario-selection bias, not a robust model-tier
   interaction. To measure it again, future rounds must deliberately select
   scenarios where the bug *requires* runtime data (pooled-resource
   aliasing, driver timing, feedback loops).

7. **GPA is a token-cost lever, not an accuracy lever — and only for the
   larger model.** (R6) After shipping the `gpa` CLI that bundles diagnostic
   checks into one Bash call, Sonnet with_gpa flipped from +$0.005/run to
   **−$0.022/run** vs code_only (first time ever cheaper). Haiku deltas
   halved (+$0.048 → +$0.019) but did not flip — the narrower context eats
   the CLI's ~500-token prompt overhead.

8. **R7's Haiku 65 % accuracy unpacks as ~20 % WRONG + ~15 % TIMEOUT, not
   35 % undifferentiated failure.** Retroactive verdict classification across
   R5-R8 (see `docs/eval-results.md`, "Verdict breakdown" per round) shows
   R7 Haiku with_gpa was 7/20 timeout + 0/20 wrong, while R7 Sonnet with_gpa
   was the mirror image (0/20 timeout + 5/20 wrong). Timeout-class failures
   respond to closure signals and narrower tools; wrong-class failures need
   better data quality. R8 validated the split: closure signal drove R8
   timeouts+wrong to 4/52 total, with zero wrong-class failures in either
   mode. Tracking separately since `729b4f8`.

---

## Capability gaps, ranked by leverage

Ordered by *current* leverage for the next round. Shipped items remain for
traceability.

| # | Gap | Evidence | Status |
|---|-----|----------|--------|
| 1 | Tier 3 framework plugins (mapbox-gl-js, three.js) — POST scene-graph / source-cache metadata per frame | R4 r27, R5 r28/r29, R6 r27/r28/r29 all 0/4 or 0/2; `SourceCache.maxzoom`, `TriangleIndexArray` type, symbol-layer placement state are purely JS-side and invisible to the GL shim | ❌ not shipped — spec at `docs/superpowers/plans/2026-04-18-framework-integration.md`. `b720e9c` shipped minimal Tier-3 annotations endpoint (foundation, no framework uses it yet) |
| 2 | NaN/Inf instruction-origin traces on framebuffer pixels (shader step-debug) | R5 r27: GPA *regressed* accuracy because NaN→black has two pathways (`D_GGX` vs `V_GGX`) that GPA can't distinguish; agents over-weighted vivid runtime signal | ❌ not planned — would require per-fragment dataflow capture. Partial mitigation via `b9dc91e` (NaN/Inf uniforms surfaced) |
| 3 | Tool-call transcript capture in eval harness | R6: cannot distinguish curl vs `gpa report` invocations from `claude -p --output-format json`; CLI-substitution hypothesis relied on self-reported counters | ✅ shipped in `2ccff06` (stream-json parser for per-turn telemetry) |
| 4 | `indexBufferType` / `index_type` on draw-call queries | R5 r28 Mapbox GLB 65 K index overflow: 0/3 with_gpa, type truncation invisible | ✅ shipped in `198773b` |
| 5 | NaN/Inf uniforms surfaced on draw-call detail | R5 r27 adjacent: agents could not see at a glance which uniform was NaN | ✅ shipped in `b9dc91e` |
| 6 | Full MRT attachment array on draw-call | R5 r32 three.js points-material MRT: sonnet code_only missed it | ✅ shipped in `9cb4eee` (R6 result: both modes 3/4 — still not universal, see gap 7) |
| 7 | Fragment output ↔ `glDrawBuffers` mismatch as a derived boolean | R5 r32 surfaced the need; `9cb4eee` exposed the raw data but agents don't yet cross-reference it | ❌ not shipped — add `fragment_outputs_mismatch_attachments: bool` from GLSL `layout(location=X) out` parse |
| 8 | Derived "texture is both bound sampler and current-FBO attachment" field | R4 r10 three.js feedback loop: Haiku+GPA had to cross-reference GL names manually | ✅ shipped in `8b7ad05` (derived feedback-loop detection endpoint) |
| 9 | `gpa` CLI bundling diagnostic checks into one Bash call | R5 token gap: with_gpa averaged +241 K cache_read and +$0.048/run vs code_only | ✅ shipped in `e28937a` + `eb5357c` + `5da024a` (MCP wrap). R6 measured impact: sonnet went net-cheaper; haiku halved |
| 10 | Prompt-footprint reduction: snapshot directory gated behind a `gpa dump source` tool, not dumped as-is into prompt | R6 haiku: still +251 K cache_read with CLI; re-reading framework files on top of `gpa report` | ❌ not planned — next-highest-leverage haiku-tier fix |
| 11 | Metal capture backend | R4 r15 Godot mobile macOS | ❌ out of scope (platform) — Vulkan/GL Godot builds would re-expose the pattern |
| 12 | JS / native call-stack attribution per GL call | Proposed R4 backlog; would skip "grep randomly through framework source" phase | ❌ not planned — `Error().stack` for WebGL, libunwind for native GL |
| 13 | `gpa.mark(key, value)` user-SDK — framework-agnostic annotation API for power users / plugin authors | R4 backlog; 1% of Tier-3 engineering cost for ~60% of the bugs it covers | ❌ not planned — partially realized by `b720e9c` endpoint; needs a stable client-side API |
| 14 | Differential capture (commit A vs commit B diff over uniforms/bindings/pixels) | R4 backlog; often the shortest symptom→cause path | ❌ not planned — better as a separate "regression bisect" product mode |

---

## Round-by-round highlights

### Rounds 1–3 (superseded)

Hint-stripped and hint-included minimal reproductions: both modes 100 %
accuracy, eval was unfair. Conclusion: needed upstream-snapshot scenarios.
Kept as historical record in `eval-results.md`; no decisions depend on
their numbers. Skip when planning future work.

### Round 4 (2026-04-19, 4 scenarios, $6.57)

First eval with real upstream framework snapshots (three.js, godot,
mapbox-gl-js). 4 scenarios × 2 modes × 2 models = 16 runs via `claude -p`.

- **First measurable GPA force-multiplier signal.** Haiku+GPA 3/4,
  Haiku+code_only 2/4; rescue cell was r10 three.js feedback loop (texture
  ID in FBO attachment AND sampler binding — GPA flagged it via two
  endpoints in one turn).
- **r27 universally missed 0/4.** `mapbox-gl-js` fractional `maxZoom` is a
  JS numeric mistake; all agents rathole'd in `transform.ts` /
  `source_cache.ts` instead of the one-line `Math.ceil` in `terrain.ts`.
  GPA has no visibility into JS-side state upstream of GL.
- **r27 stub revealed the "dead scenario" problem.** `main.c` was a
  black-frame stub → `with_gpa` had nothing to work with.
- **r15 Godot Metal — all 4/4 correct despite GPA providing nothing.**
  Metal is unreachable by OpenGPA's GL/Vulkan shims; agents succeeded
  purely from framework source reading. Confirms GPA scope boundary.

Source: `eval-results.md` §Round 4, `round4-capture-gaps.md`.

### Round 5 (2026-04-19, 20 scenarios, 78 runs, $30.94)

First statistically meaningful run. Contamination-validated scenarios.

- **No GPA accuracy advantage.** code_only Haiku 20/20 (100 %), with_gpa
  Haiku 17/19 (89.5 %); Sonnet 17/20 vs 16/19. R4's force-multiplier was
  sample-of-one.
- **r27 anisotropic GGX: GPA *regressed* accuracy.** Both with_gpa agents
  anchored on NaN-denominator hypothesis from live pixel evidence and
  missed the actual semantic change (`saturate()` removal on
  `V_GGX_SmithCorrelated_Anisotropic`). Code-only agents read the shader
  and got it right. First round where runtime signal hurt.
- **r28 GLB 65 K index overflow: 1/4.** The bug is JS-side
  `Uint16Array`, the GL stream shows truncated indices but no error.
  Direct motivation for `index_type` endpoint (shipped `198773b`).
- **with_gpa pays a token tax.** Haiku with_gpa averaged +$0.048/run and
  +384 K cache_read tokens vs code_only — not sustainable for production.
  Motivated the R6 `gpa` CLI experiment.

Source: `eval-results.md` §Round 5, `round5-capture-gaps.md`.

### Round 6 (2026-04-19, 20 scenarios, 80 runs, $34.03)

Shipped `gpa` CLI (`e28937a`, `eb5357c`, `5da024a`) + narrow REST
endpoints (`feedback-loops`, `nan-uniforms`, `attachments`) before the run.
Measured whether one-call `gpa report` substitutes for curl sequences.

- **Sonnet hypothesis confirmed.** with_gpa Sonnet is now the **cheapest
  cell in the matrix** ($0.555 vs $0.577 code_only, Δ = −$0.022/run,
  Δ cache_read = −64 K, Δ turns = −1.6). First time any round has had
  with_gpa beat code_only on cost.
- **Haiku hypothesis partially confirmed.** Δ cost halved (+$0.048 →
  +$0.019), Δ cache_read down 34 % (384 K → 251 K), but still positive.
  Narrower context eats the ~500-token CLI doc block.
- **Accuracy within noise.** 65/80 (81 %) vs R5 70/78 (90 %). Haiku
  code_only regressed from 20/20 to 16/20 — first haiku miss on this
  suite. Three scenarios (r27, r28, r29) universally 0/4 in both rounds.
- **Tool-substitution only inferred from self-report.**
  `claude -p --output-format json` lacks a tool trace; fixed in R7 setup
  via `2ccff06` (stream-json parser).

Source: `eval-results.md` §Round 6, `round6-findings.md`.

### Round 7 (not yet run)

Setup in place: stream-json telemetry (`2ccff06`, `6549c53`). Next-round
priorities below.

---

## Priorities for the next round

In decreasing order of leverage:

1. **Ship at least one Tier-3 framework plugin** (mapbox-gl-js first — it
   unlocks r27 R4, r29 R5, r28 R5 all at once). Design at
   `docs/superpowers/plans/2026-04-18-framework-integration.md`; endpoint
   shipped in `b720e9c`; no plugin consumes it yet.
2. **Gate the upstream snapshot behind `gpa dump source`** so prompt
   footprint stops blocking haiku cost flip. Measured need in R6 haiku
   +251 K cache_read delta.
3. **Curate scenarios that *require* runtime data** — pooled-resource
   aliasing, driver timing, feedback loops. The current suite is a strong
   baseline for code-only; GPA can't force-multiply where the bug is
   inferable from upstream source alone.
4. **Use R7's stream-json telemetry to verify `gpa` vs curl substitution
   directly**, not via self-reported counter.
5. **Add derived `fragment_outputs_mismatch_attachments` field** (R5 gap 4)
   — the raw MRT data is there (`9cb4eee`); the derivation is not.
6. R8 found 2/11 remaining Haiku timeouts from "warning surfaces symptom,
   not root cause" pattern. Tier-2 closure hint shipped as `3b99ef5`
   addresses this.

---

## Future capabilities backlog (unranked)

Ideas kept here for when the scenario set is strong enough to warrant the
engineering cost. Most were never in flight; see gaps table above for
items with active evidence.

- **JS / native call-stack attribution per GL call.** `Error().stack` on
  WebGL, libunwind on native GL. Lets agents skip the "grep randomly
  through framework source" phase.
- **`gpa.mark(key, value)` user-SDK.** Framework-agnostic annotation API
  for power users. 1% of Tier-3 engineering cost for ~60% of the bugs it
  covers. Partially enabled by `b720e9c` endpoint.
- **Differential capture.** Capture commit A (known-good) vs commit B
  (buggy), diff over uniforms / bindings / draw counts / pixel colors.
  Better as separate "regression bisect" product mode than always-on.
- **Tier 3 framework plugins** for three.js / mapbox-gl-js / godot that
  POST scene-graph metadata per frame. Highest ceiling; highest cost (per-
  framework, tracks upstream API).
- **Shader step-debug with per-instruction value capture** for a sample
  pixel. Addresses R5 r27-class "NaN has two pathways" ambiguity.
- **NaN/Inf mask on framebuffer.** `/frames/<id>/framebuffer/nan-mask`
  returning per-pixel bitmask. Less powerful than step-debug but cheaper.

---

## Round 9 findings

**Setup:** 20 C-repros + 1 browser pilot, 3 models (haiku / sonnet /
opus), both modes → 108 runs × $60.70. First round with native
`gpa trace` (DWARF globals + libunwind stack locals) plumbed.

### Lessons

1. **Native trace shipped but not discovered.** In 48 with_gpa runs,
   `gpa trace` was invoked **once** total. The prompt listed it as
   "preferred step 2" but agents consistently went `report → dump`,
   skipping it. Root causes: (a) scenarios pass clean `gpa report`, so
   the step-2 trigger condition ("you need the upstream value for a
   flagged warning") never fired; (b) `gpa dump drawcall` already
   returns captured uniforms with app-observable values, so the
   "reverse-lookup" framing of trace isn't an obvious next step. For
   R10: rewrite the prompt to front-load trace as "when you find
   yourself Grep'ing for a uniform value, stop and call `gpa trace
   value N` first."

2. **Source-logical category is not as hard as R5-R8 suggested.** R9's
   with_gpa numbers: haiku 6/8, sonnet 6/8, opus 8/8. Prior rounds hit
   0/4 on a smaller subset. The gap closed without the tool we shipped
   to close it — `gpa report`'s flagged warnings + the agent's own
   Grep/Read of snapshot source are sufficient for most source-logical
   bugs. Implication: native trace's value has to be demonstrated on a
   scenario where `gpa report` comes back clean, AND there's a captured
   numeric value that's the breadcrumb. R10 should mine for that
   specific pattern.

3. **Opus adds capability, not cost-efficiency.** 100% with_gpa on 16
   scenarios, 90% code_only on 20. Zero regressions vs sonnet. Cost
   premium is 1.4× sonnet (not 5× as list pricing would suggest) and
   timeouts dropped to 0 (vs sonnet 1, haiku 4). Good "insurance tier"
   choice for hard scenarios; not the default tier.

4. **Sonnet's state-collision cost advantage is stable.** R8
   −$0.088/pair → R9 −$0.090/pair. State-collision is the canonical
   "GPA saves reading" pattern. Carryover and source-logical both
   show *positive* Δcost (GPA adds cost when source is the real
   signal). Pattern: GPA's Δcost sign aligns with whether the bug
   expresses itself in GL state vs. in code branches.

5. **Haiku turn-cap hit 4/16 with_gpa.** Same rate as R8 (2/11). The
   report closure hint didn't close this gap — the remaining haiku
   timeouts are on scenarios where report is clean and haiku loops on
   dump/pixel-grid exploration. For R10: enforce a "try source first
   if report is clean" instruction for haiku specifically.

6. **Browser pilot pipeline works in MVP form.** Chromium launches,
   extension POSTs sources, engine accepts them. Phase 1 is scaffold;
   Phase 2 needs real WebGL capture (frame != 0) before a with_gpa
   agent run can be evaluated against a browser scenario.

### R9 token / cost deep-dive (post-run analysis)

**Per-run means (108 runs, $60.70 total, 22 min wall-clock):**

| Mode | Haiku | Sonnet | Opus |
|---|---|---|---|
| code_only | $0.37 | $0.53 | $0.75 |
| with_gpa | $0.37 | $0.61 | $0.75 |

**Opus multiplier recalibrated 5.0 → 1.4** in `src/python/gpa/eval/models.py`
(list pricing says ~5× raw input tokens, but Opus terminates faster on
hard problems; effective per-run cost is 1.33×). Budget planner now much
less restrictive.

**Paired Δcost (both correct, Sonnet by subset):**

| Subset | n | Δcost |
|---|---|---|
| State-collision | 3 | **−$0.090/pair** (R8 was −$0.088 — reproducible) |
| Source-logical | 4 | −$0.019/pair |
| R5-R8 carryover (framework-consumer) | 4 | **+$0.389/pair** |

The aggregate "+$0.11/pair" with_gpa regression is **entirely driven by
the R5-R8 carryover bucket**. Drop those → with_gpa wins. Insight:
framework-consumer bugs are net-negative with GPA; state-collision +
source-logical are net-positive. Forward mining should avoid
framework-consumer issues unless they exhibit a state collision.

**Cache-read inflation reversed on Sonnet** (first time in 5 rounds):

| | R5 Δ | R7 Δ | R9 Δ |
|---|---|---|---|
| Haiku with_gpa − code_only | +384K | +251K | +151K |
| Sonnet with_gpa − code_only | +57K | +121K | **−261K** |

Narrow-endpoints + CLI + closure-signal stack finally paid off on token
efficiency for Sonnet. Haiku still over-reads but improving.

**Opus with_gpa: cleanest cell ever recorded** — 16/16 solved, 0 timeouts,
0 wrong-class. Opus is a reliability tier, not a cost premium.

### R10 asks (preliminary)

- **Mine trace-discriminating scenarios**: bugs where `gpa report`
  comes back clean AND there's a captured literal whose provenance is
  what the agent needs to find. ~5 scenarios would be enough to
  demonstrate trace value.
- **Prompt rewrite** promoting trace to step 1 for scenarios with a
  numeric symptom (matrix element, stencil ref, viewport size).
- **Browser Phase 2**: real WebGL frame capture for `r21_tile_id_overflow`.
- **Haiku + clean-report loop mitigation**: explicit "if report clean
  then grep source" instruction, or a soft turn budget (20) before the
  hard cap.
- **Consider dropping carryover bucket** from future eval sets, or at
  least caveat it: Sonnet regresses +$0.39/pair there, dragging the
  aggregate GPA signal negative while subset data shows GPA is net
  positive on state-collision + source-logical.

---

## Round 12 + 12b — Codex-mined scenarios via claude-cli (2026-05-04)

Three max-effort subagents audited the round (mining pipeline, scoring
methodology, agent/system improvements). Per-area detail in
`docs/eval-lessons-{mining,scoring,system}.md`. Synthesis below.

### What's true after R12

11. **The codex mining pipeline mis-classifies framework-internal bugs
    as `consumer-misuse`/`user-config`.** All 14 R12 scenarios patch
    framework code (godot `servers/rendering/...`, maplibre
    `src/render/...`, cesium `packages/engine/Source/...`), yet 12 came
    out `consumer-misuse` and 2 `user-config`. The decision is made by
    a regex (`infer_bug_class` in `rules.py:313`) — the LLM `Triage`
    class is **dead code**, never instantiated by `run.py`. The
    deciding regex `app_resolution` has bare-token patterns
    (`use `, `set `, `enable `) that match almost any English issue
    body (e.g. "Enable Glow" or "Use a custom terrain source").
12. **`fix.files` is the raw whole-PR file list, padded with
    collateral.** Cesium's 12 gt files include 5 `*Spec.js` test files
    that the test-filter missed (it checks `.spec.js`, not Jasmine's
    `*Spec.js` convention). Godot scenarios carry header+impl+
    `_inc.glsl` + refactor sweep — the actual bug-causing file is 1
    of 13–22. This destroys file-level recall: the agent names the
    real bug file and scores 1/13.
13. **Legacy keyword scorer is unfit for advisor scenarios.** Mined
    scenarios have empty/templatey `ground_truth_diagnosis`, so the
    scorer pattern-matches user-report keywords against the
    diagnosis. Round 12 cesium "gave up" with one sentence and was
    marked ✓; round 12b cesium found the real bug (cache invalidation
    in `Picking.pickPositionWorldCoordinates`) and was marked ✗.
14. **The with_gla prompt advertises capabilities the agent doesn't
    have.** 14/14 R12b runs had `live capture unavailable` (no
    binaries, no engine), yet the prompt block in `cli_agent.py:80-96`
    lists 11 commands of which only 3 (`gpa upstream read|grep|list`)
    actually work, and ends with the literally-false line
    `"GPA_FRAME_ID is set so --frame is automatic."` Agent worked
    around the noise but ~75% of the prompt's tool block was unusable.
15. **Free signal is dropped at multiple layers.** The harness loads
    `scenario.framework`, `upstream_snapshot_repo`, `fix.fix_pr_url`,
    and resolves `bug_class` — but `cli_agent._render_prompt`
    threads only `description` + `source_path` into the prompt. The
    agent has to re-derive context that was already on disk.

### R12 priority backlog

**P0 — half-day each, unblocks honest measurement of every prior round:**

1. **Wire `Triage` LLM into the produce path** (mining). Call
   `Triage(...)` inside `_run_produce` and override
   `rec.bug_class_guess`. Belt-and-suspenders: if every entry in
   `rec.fix_files` resolves under a framework source path, force
   `bug_class=framework-internal`. → `eval-lessons-mining.md` rec #1
   + #6.
2. **Loosen file-level scorer trigger** from `bug_class ==
   "framework-internal"` to `scenario.fix is not None and
   scenario.fix.files`. One-line change in `harness.py:111` makes
   `score_maintainer_patch` available to the 14 R12 scenarios (and
   any future advisor-classed mine that retains real `fix.files`).
   → `eval-lessons-scoring.md` §2a.
3. **Stop lying in the with_gla prompt about live capture.** Branch
   the prompt block on `tools.get("snapshot_root")` vs runtime
   capture availability. Drop the "GPA_FRAME_ID is set" line when
   `frame_id is None`. Add a one-line "scenario blurb" with
   framework + repo + `fix_pr_url` + bug-summary so the agent doesn't
   re-derive context. → `eval-lessons-system.md` §5 fix #1 (~40 LoC).

**P1 — a day each, raises measurement ceiling:**

4. **Tighten `app_resolution` regex** to maintainer-response phrasing
   ("won't fix", "by design", "not a bug" with right-side `\b`).
   Drop the bare-token literals. → mining rec #3.
5. **Rank `fix.files` by diff size and cap at top-N** (default 5).
   Surfaces the bug-causing file rather than the PR sweep. Add
   `Specs/` segment + case-insensitive `*Spec.js` filter for Jasmine.
   → mining rec #4 + #5.
6. **Add the prose scorer + gave-up veto.** `scorer_prose.py`
   extracts paths/basenames/symbol tokens from free-form `FIX:` text;
   gave-up regex bank vetoes `solved=True` on bail-out diagnoses
   (8 patterns). New `ScoreVerdict` dataclass with `needs_review`
   bucket. → scoring §2b + 2d.
7. **Stop dropping free signal in the prompt.** Inject
   `scenario.framework`, `scenario.upstream_snapshot_repo`,
   `scenario.fix.fix_pr_url`, `tools["bug_class"]` into the agent
   prompt. → system §4.

**P2 — larger / opt-in:**

8. **LLM-judge tier.** Gate on `solved=False AND any_hit ≥ 1`
   (ambiguous residual). Reuses `gpa.eval.judge.run_semantic_judge` +
   `ClaudeCodeLLMClient` — no new client. Cost-bounded: ≤ 8 calls /
   round, ≤ 5 KB context, disk cache, default off behind
   `--llm-judge`. → scoring §2c.
9. **`gpa upstream find-symbol`** (~80 LoC). Symbol-aware verb beats
   grep+read chains; current `gpa upstream grep` has no `--context`
   and the 200 KB `_SNAPSHOT_MAX_BYTES` cap truncates godot files at
   369–402 KB. → system §2 gaps + §5 fix #2 (grep `--context` +
   raise cap to 512 KB) + fix #3.

### What we now know about with_gla on these scenarios

- **Token-efficiency win is real.** 38% faster wall, 8% fewer total
  output tokens, 15% fewer tool calls vs same-scenario code_only.
  Effect concentrated on godot (huge codebase: grep beats inferring
  shape from training data).
- **"Did the agent solve it" is a wash by current metrics**, but the
  metrics are broken (P0 #2 unlocks the real signal). Qualitatively,
  with_gla flipped cesium ✗→✓ (the kind of bug only solvable with
  snapshot access) and sharpened maplibre/mapbox diagnoses with
  symbol-level citations the snapshot enabled.
- **Web-map subset was a clear win**: 5/6 vs 4/6 file-level any-hit,
  precision 0.67 vs 0.58. Godot regressed (3/8 vs 5/8) but each
  godot "regression" is code_only's training-data guess landing on a
  collateral PR file while with_gla cited a different (probably
  also-relevant) file from the bug area. P1 #5 addresses this by
  cutting collateral from `fix.files` in future mines.

### R12 asks (concrete, ordered)

1. **Re-score rounds 4–12 against the new scorer stack** once P0 #2
   and P1 #6 land. No re-running the agent; results.json on disk has
   what we need. Expect existing "with_gla solved 0/27" type cells
   to flip on rounds where `fix.files` is well-shaped.
2. **Re-mine rounds 11–12 scenarios** after P0 #1 + P1 #4 + P1 #5
   land. `bug_class` distribution should shift toward
   `framework-internal` for the 14 R12 cases, and `fix.files`
   cardinality should drop to ~3 from ~10 average.
3. **Smoke-test the new `gpa upstream find-symbol` + raised file
   cap** on the godot scenarios that lost in R12b — this is the
   class of scenario where the symbol-aware verb should swing the
   scorer.

