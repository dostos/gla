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
