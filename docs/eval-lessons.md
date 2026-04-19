# Eval Lessons

Running notes on what each round taught us — separate from `eval-results.md`
(which records what the numbers were) and from `coverage-gaps.md` (which records
concrete capture capabilities to implement).

## L1 — Don't filter by "root cause location"

**Round 4 trap:** After r27 (mapbox fractional `maxZoom`) scored 0/8, the
instinct was to declare bugs whose root cause lives in JS logic "upstream of
GL" as out-of-scope for OpenGPA. That's wrong. Every visible rendering bug
manifests as observable state somewhere in the capture — wrong uniform,
missing draw call, unexpected binding. OpenGPA's job is to surface the
anomaly; tracing the anomaly back to the upstream cause in JS / framework
source is the agent's job.

The correct triage rule is scope-based (rendering bug vs docs/build/API
question), not location-based. Triage prompt was reverted in this direction.

## L2 — A stub main.c is a dead scenario

**Round 4 r27 was universally missed because its `main.c` never reproduces
the bug.** The file is a black-frame stub that issues `glClearColor` +
`glClear` + `glXSwapBuffers` and nothing else. Round 4 agents querying OpenGPA
saw an empty capture (zero draw calls, zero uniforms, zero textures). There
was no signal to surface.

**Implication for scenario curation:** a scenario qualifies for eval only if
its `main.c` actually exercises the bug-pattern in GL calls such that the
capture contains differentiated state. The drafter/validator should reject
stubs. Add a check: captured frame must have ≥1 draw call and ≥1 non-default
pipeline-state field.

**What a good r27-class scenario looks like:** a small GL app that uploads
an integer-indexed texture atlas, then samples it with a fractional index
that gets truncated — producing the same "wrong tile" symptom under GL that
the mapbox bug produces in JS. The bug pattern transfers; the specific
framework does not.

## L3 — GPA as force-multiplier for smaller models

**Round 4 signal:** Haiku+code_only got 2/4; Haiku+with_gpa got 3/4. The
rescue scenario (r10 feedback loop) was one where GPA exposed a texture ID
simultaneously in the FBO attachment list and a sampler binding. Sonnet
didn't need GPA because it read five framework files and triangulated from
code alone.

**Working hypothesis:** GPA turns smaller models' runtime evidence into what
bigger models would otherwise compensate for with broader source reading.
The eval harness should weight Haiku-tier results heavily — that's where
the measurable delta appears.

## Future capabilities backlog

Ideas kept here for when the scenario set is strong enough to warrant the
engineering cost. Not in any priority order.

- **JS / native call-stack attribution per GL call.** On each wrapped GL
  call, capture `Error().stack` (WebGL) or a libunwind trace (native GL)
  and store it on the draw call. Agents get a direct pointer to the JS
  file/line that issued the draw, not just the state it issued — lets
  them skip the "grep randomly through framework source" phase.
- **`gpa.mark(key, value)` user-SDK.** A framework-agnostic annotation
  API that lets power users / plugin authors POST suspect upstream state
  without OpenGPA having to ship per-framework code. 1% of the work of
  Tier 3 metadata integration, ~60% of the value for the bugs it covers.
- **Differential capture.** Capture the same app at commit A (known-good)
  and commit B (buggy), then compute a diff over uniforms / bindings /
  draw counts / pixel colors. The diff is often the shortest path from
  visible symptom to upstream cause, even when the agent never reads the
  framework source at all. Useful as a separate product mode ("regression
  bisect") rather than an always-on feature.
- **Tier 3 framework plugins** for three.js / mapbox-gl-js / godot that
  POST scene-graph metadata per frame. Ceiling is high (covers bugs where
  the captured GL state alone is insufficient to identify the affected
  object by user-facing name), but cost is per-framework and each plugin
  needs to track the upstream API. Current plan lives at
  `docs/superpowers/plans/2026-04-18-framework-integration.md`.
