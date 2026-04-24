# OpenGPA Flywheel — Problem × Solution Matrix

*Living document. Last updated 2026-04-21.*

**Purpose.** Identifies common problems agents face per scenario category, maps
the API/CLI/tool solutions we've shipped to those problems, and exposes gaps
that should drive the next mining + build round. This is the single source of
truth for "what to build, what to measure, what to mine next." Prior scattered
docs (eval-lessons-consolidated, per-round findings, spec-per-capability) remain
as evidence; this doc aggregates decisions from them.

The flywheel executes against this matrix:

```
mine scenarios for cell X → run eval → measure whether X's shipped tools help →
  if yes → mark cell solved, move to next cell
  if no  → build a new tool for X, or decline X (not GPA's scope)
```

Every commit that adds a capability should cite which cells it addresses.
Every mined scenario should tag at least one cell. Every eval round should
report per-cell, not just aggregate.

---

## Scenario taxonomy

Three top-level categories, each with sub-categories. Every scenario in
`tests/eval/` belongs to exactly one primary cell (and optionally secondary
cells for cross-cutting patterns).

### 1. `graphics-lib-dev` — direct graphics API development

The dev writes OpenGL / Vulkan / WebGL / etc. directly. No high-level
framework between them and the GPU. Bug lives in their own code. Sub-cat by
API:

- `gl` — OpenGL desktop (our `LD_PRELOAD` shim supports)
- `webgl` — browser WebGL 1/2 (our browser extension supports)
- `vulkan` — partial native support
- `out-of-scope` — Metal, DirectX, console APIs

Today's `e*` synthetic scenarios are all `graphics-lib-dev × gl`.

### 2. `framework-app-dev` — application development atop a framework

The dev uses a higher-level engine/framework (three.js, godot, mapbox, unreal).
Bug is in their app code or configuration — the framework is doing what it
documents. Sub-cat by framework family:

- `web-3d` — three.js, babylon.js, A-Frame, PlayCanvas
- `web-2d` — PIXI.js, canvas-based
- `web-map` — mapbox-gl-js, maplibre, deck.gl, Leaflet+GL
- `native-engine` — godot, unreal, unity
- `scientific` — ParaView, VisIt, Blender Python

### 3. `framework-maintenance` — framework development

The dev is a maintainer or contributor to the framework itself. A user filed
an issue; the fix needs to land in framework source. Same sub-categories as
category 2.

---

## Problem × solution matrix

### Category 1: `graphics-lib-dev`

| Problem | Shipped solutions | Evidence | Gaps |
|---|---|---|---|
| What GL state was in effect at draw N? | `gpa report`, `gpa dump drawcall/shader/textures` | — | — |
| Is this texture both attached and sampled? | `/feedback-loops` narrow endpoint (`8b7ad05`) | R8 Sonnet state-collision −$0.088/pair | — |
| Is this uniform NaN/Inf? | `/nan-uniforms` narrow endpoint (`b9dc91e`) | R9 haiku r27 solve | — |
| Is the MRT attachment set complete? | `fbo_color_attachments[8]` + `/attachments` (`9cb4eee`) | — | No `GL_FRAMEBUFFER_STATUS` capture yet |
| Was the index-buffer type truncated? | `index_type` on drawcall (`198773b`) | — | No positive validation test |
| Did state leak between draws? | `gpa compare` (frame-to-frame diff) | — | **No per-draw-within-frame diff** |
| Which pixel came from which draw? | `gpa explain_pixel` (stub) | — | **Gap — draw-call ID buffer not wired** |
| Is my shader compile log clean? | — | — | **Gap — no shader compile log capture** |
| Per-instruction shader debug | — | — | Gap (large; likely outside GPA scope) |
| Stack at call site | Native DWARF stack walker (`536a64b`, `8bc6ba5`) | R9: 0 invocations on graphics-lib bugs | Well-provisioned; under-demanded so far |

**Health of this category:** most pain points covered. State-collision wins are stable and reproducible (R8 −$0.088 / R9 −$0.090 per pair for Sonnet).

### Category 2: `framework-app-dev`

| Problem | Shipped solutions | Evidence | Gaps |
|---|---|---|---|
| Why is my scene / view / map wrong? | `gpa report` shows GL result (indirect) | R9 carryover **+$0.39/pair regression** → tool doesn't fit | **Major gap — no scene-graph inspection** |
| Am I calling the framework API correctly? | — | R9 carryover | **Gap — no API-usage validator** |
| Which framework object produced this draw? | — | — | **Gap — object ↔ drawcall map** |
| What does the framework think is happening? | `/frames/*/annotations` POST endpoint (`b720e9c`) | No deployed plugins use it | **Partial — endpoint exists, no plugin authors** |
| Is my config wrong? (renderer.autoClear etc.) | — | — | **Gap — no config suggestion tool** |
| Stack from user-code → framework call | JS `Error().stack` via browser shim | — | Partial, untested |

**Health of this category:** **largely unserved.** The R9 +$0.39/pair carryover regression is the signature of this gap — every tool we have answers a GL question when the agent needs to answer an app-code question. Tier-3 plan exists (`docs/superpowers/plans/2026-04-18-framework-integration.md`) but no framework plugins authored.

### Category 3: `framework-maintenance`

| Problem | Shipped solutions | Evidence | Gaps |
|---|---|---|---|
| Reproduce the user's bug | Scenario repro + `gpa run` | — | — |
| Capture runtime state at reproduction | `gpa report`, all narrow endpoints | R4–R8 state-collision wins | — |
| Find the offending code location | `gpa trace` reverse value-lookup (`99ca5fa`, `7ac2b43`) | **R9: 1/48 invocations — mostly unused** | Scenarios haven't demanded it yet (see Mining Priorities) |
| Navigate the framework architecture | Generic `Read` / `Grep` / `Glob` on full snapshot | — | Adequate but inefficient — agents re-grep a lot |
| Impact analysis (what else does this function affect?) | — | — | **Gap — no callgraph / reference search** |
| Verify a fix doesn't regress | — | — | **Gap — no test-run tool** |
| Similar-bug history in this file | `git log` / blame via `Bash` | — | Generic; no ranked suggestion |
| API contract lookup for a symbol | — | — | **Gap — no doc lookup** |
| Stack trace at the GL call | Native DWARF (`536a64b`) + WebGL `Error().stack` | — | Present but under-demanded in current scenario set |
| Closure / non-global state reflection | JS `gpa.trace.addRoot()` SDK | No real-world users yet | Works in principle |

**Health of this category:** runtime-capture side is strong; code-navigation / impact-analysis / test-run side is under-served. `gpa trace` is built but the scenario set doesn't exercise it — R10 scenarios should be designed to demand it.

---

## Round-by-round evidence

Each row tags the dominant category + key finding. Full detail in
`docs/eval-results.md`.

| Round | Primary category | Headline result |
|---|---|---|
| R4 (4 scen) | `graphics-lib-dev` | First force-multiplier signal (Haiku+GPA rescued r10 feedback loop) |
| R5 (20 scen) | mixed (mis-labeled) | No GPA advantage at n=20; cache_read +26% |
| R6 (20 scen) | mixed (mis-labeled) | First Sonnet win (−$0.022/pair) after CLI shipped |
| R7 (20 scen) | mixed (mis-labeled) | Stream-json telemetry revealed Haiku timeouts vs Sonnet wrong-class |
| R8 (15 scen) | `graphics-lib-dev` state-collision | **−$0.088/pair** — cleanest win; reproducible |
| R9 (21 scen, 3 tiers) | mixed | Sonnet state-collision −$0.090; carryover **+$0.389**; Opus 100% with_gpa; trace 1/48 uses |

**The "mixed" label on R5–R7** is the biggest lesson: we evaluated two or
three categories in one batch and averaged signals that moved in opposite
directions. Going forward eval rounds run per-category and report per-cell.

---

## Mining priorities (derived from gaps)

Ordered by expected leverage:

1. **`framework-maintenance × web-3d` with code-navigation emphasis.** Target
   closed-as-fixed three.js / godot / mapbox issues where the fix is 1-3
   files, < 50 changed lines, and the fix location is NOT obviously named in
   the user's issue body. This is where `gpa trace` should finally earn its
   keep. ~10 scenarios needed.

2. **`framework-app-dev × web-3d` canonical config bugs.** `autoClear`,
   `physicallyCorrectLights`, `colorSpace`, `toneMapping` — common consumer
   misunderstandings. The "right answer" is an API-usage change, not a
   framework patch. Tests whether we can add a config-validator tool
   (currently a gap). ~5 scenarios.

3. **`graphics-lib-dev × gl` explain_pixel attribution cases.** Bugs where
   one pixel is wrong and the agent needs to identify which draw drew it.
   Motivates wiring the draw-call ID buffer. ~3 scenarios.

4. **`graphics-lib-dev × webgl` via the browser pilot.** Phase 2 of the
   browser-eval runner — real three.js page, real capture. The `r21` pilot
   scaffold exists (`0d16ae8`). ~3 scenarios needed.

---

## How to use this doc

### When adding a scenario

Tag its primary cell in the scenario's YAML frontmatter:

```yaml
## Flywheel Cell
primary: framework-maintenance.web-3d.code-navigation
secondary:
  - graphics-lib-dev.gl.state-collision   # if cross-cutting
```

(Field isn't parsed yet; loader will gain support in the next schema bump.)

### When shipping a feature

Cite cells in the commit message body:

```
feat(api): /drawcalls/{id}/feedback-loops endpoint

Addresses: graphics-lib-dev.gl — "is this texture both attached and sampled?"
```

### When running an eval

Segment `summary.txt` by cell. Aggregate-only reports are explicitly
discouraged after R9.

### When this doc gets updated

Any time:
- A new scenario cell or sub-category is introduced
- A gap gets closed (shipped or declined)
- An eval provides new evidence about a cell's health
- A mining priority gets addressed

Update the timestamp at top.

---

## Out of scope for GPA

These problems exist but we explicitly don't address them:

- **Shader per-instruction debugging** — huge effort; existing tools (RenderDoc
  / Nsight) do this better
- **Non-GL graphics APIs** (Metal, D3D, console) — we'd need per-vendor shim
- **Non-visible-frame bugs** (audio, physics, AI) — out of GPA's sensor range
- **Developer experience / IDE integration** — separate product; GPA is a
  service the IDE calls
- **Performance profiling / timing** — adjacent but different problem class

---

## Referenced docs (historical evidence)

- `docs/eval-results.md` — full per-round journal (rounds 4–9)
- `docs/eval-lessons-consolidated.md` — rolling cross-round lessons pre-2026-04-21
- `docs/superpowers/specs/2026-04-19-gpa-cli-design.md` — CLI surface rationale
- `docs/superpowers/specs/2026-04-20-gpa-trace-design.md` — trace (JS) design
- `docs/superpowers/specs/2026-04-20-gpa-trace-native-design.md` — trace (native DWARF)
- `docs/superpowers/specs/2026-04-20-gpa-browser-eval-design.md` — browser eval scaffold
- `docs/superpowers/specs/2026-04-21-maintainer-framing-design.md` — maintainer-framing scorer
- `docs/superpowers/plans/2026-04-18-framework-integration.md` — Tier-3 plan

After this doc proves itself across 1–2 rounds, the `eval-lessons-consolidated`
can be retired; per-round detail stays in `eval-results.md`.
