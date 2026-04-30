# with_gpa vs code_only — multi-scenario (4 buggy GL apps, single tier)

*Run: 2026-04-30. Model: Opus 4.7 (1M context) via Claude Code subagent
dispatch. Extends [r10-with-gpa-vs-code-only.md](./r10-with-gpa-vs-code-only.md).*

## Setup

Six parallel `general-purpose` subagents — one pair (`code_only` /
`with_gpa`) per scenario, 3 new synthetic scenarios + the R10 result
re-stated for comparison. All agents got:

- The user-report section verbatim from `scenario.md` (Ground Truth /
  Fix metadata redacted).
- Read access to the `.c` reproduction file.
- A 20-tool-call budget cap.
- Required output: `DIAGNOSIS:` + `FILE:<path>:<line>`.

`with_gpa` agents additionally got `curl` access (no auth) to a running
OpenGPA engine at `localhost:18080` with the per-scenario captured
frames documented up-front (frame_id, draw_call layout, available
endpoints).

## Scenario shape

| Scenario | Repro | LoC | Bug class | Difficulty |
|---|---|---|---|---|
| **R10** (`r10_feedback_loop…`) | three.js example + cherry-pick of regression PR | multi-file | framework-internal (PR #32444 regression) | hard (cross-file) |
| **e1** (`e1_state_leak`) | single `.c` | ~200 | core: state collision (uniform/texture leak across draws) | easy (1/5) |
| **e22** (`e22_depth_test_gl_greater…`) | single `.c` | ~155 | core: state pollution (helper leaks `glDepthFunc=GL_GREATER`) | medium (3/5) |
| **e26** (`e26_depth_buffer_not_cleared…`) | single `.c` | ~165 | core: missing-clear-bit (only `GL_COLOR_BUFFER_BIT`) | medium (3/5) |

## Aggregate results

### Diagnosis accuracy

**6/6 correct** (3/3 code_only, 3/3 with_gpa). All agents named the
right root cause; all fix lines exact. **No accuracy delta** at this
sample size.

### Cost per scenario

| Scenario | Mode | Tool calls | Tokens | Wall (s) |
|---|---|---|---|---|
| R10 | code_only | 5 | 21,266 | 37 |
| R10 | with_gpa  | 4 | 19,313 | 24 |
| e1  | code_only | 2 | 23,555 | 16 |
| e1  | with_gpa  | 5 | 25,945 | 29 |
| e22 | code_only | 2 | 23,101 | 22 |
| e22 | with_gpa  | 4 | 24,619 | 22 |
| e26 | code_only | 2 | 23,145 | 20 |
| e26 | with_gpa  | 5 | 24,803 | 27 |

### Per-scenario Δ (with_gpa vs code_only)

| Scenario | Δ calls | Δ tokens | Δ wall |
|---|---|---|---|
| **R10** (framework, multi-file) | **−20%** | **−10%** | **−35%** |
| e1  (single `.c`, ~200 LoC) | +150% | +10% | +78% |
| e22 (single `.c`, ~155 LoC) | +100% | +7%  | +3%  |
| e26 (single `.c`, ~165 LoC) | +150% | +7%  | +36% |

### Mean across the 3 synthetic single-file scenarios

| | code_only | with_gpa | Δ |
|---|---|---|---|
| Tool calls | 2.0 | 4.7 | **+135%** |
| Tokens | 23,267 | 25,122 | +8% |
| Wall time | 19.4 s | 26.2 s | +35% |

## Takeaways

1. **GPA tools shift cost in the *opposite* direction on small synthetic
   scenarios.** When the bug fits in one ~150-line `.c` file, a single
   `Read` call beats any number of REST queries. The agent has to
   query GPA *and then* still read the file to confirm and locate the
   line — strictly more work than reading the file alone.

2. **The R10 win is not generalizable as-is.** R10's win came from
   GPA delivering a single-call smoking gun (`textures.collides_with_fbo_attachment:
   true`) that let the agent skip a source-navigation step on a
   *multi-file framework regression* where the relevant source lived
   behind cross-repo navigation. That cost structure doesn't exist on
   single-file synthetic scenarios.

3. **The "where code_only fails" expectation didn't materialize at
   N=3.** All three synthetic scenarios were single-file, well-formed,
   and Opus 4.7 solved them code-only in 2 tool calls each. To exercise
   cases where code_only struggles, future eval pairs should target:
   - **Multi-file framework bugs** (like R10) where source navigation
     is the dominant cost.
   - **Bugs requiring runtime state** that isn't visible in source —
     uniform NaN propagation, dynamic shader recompilation, runtime
     depth/blend state set indirectly via library configuration, GPU
     resource lifecycle (e.g. an FBO bound at a moment that doesn't
     correspond to any source line).
   - **Frameworks that abstract the GL surface** — the user can't
     directly inspect what GL state is active because the framework
     wraps it. (This is exactly the R13 maintainer-framing scenario
     shape, which currently lacks captured frames.)

4. **Accuracy is uniform; cost dominates.** Both modes nailed all 4
   scenarios. The decision of when to use GPA tooling is purely
   efficiency-driven, not capability-driven, on this scenario set.

## What this implies for the toolkit

- **Don't auto-suggest GPA queries on sub-200-LoC scenarios** — the
  ranking heuristic (or future agent prompt scaffolding) should weight
  source LoC and file count, defaulting to source-first when the bug
  surface is small.
- **The killer use case is framework bugs where the source surface is
  large.** R10 shape is where the eval should concentrate to amplify
  the win.
- **N=4 is still small.** Replicate at multiple tiers
  (haiku/sonnet/opus) when API key is available — the cost-per-tool-call
  varies by model and a 5-vs-2 call delta might invert if cheaper
  models have higher per-call success variance.

## Open follow-ups

- **Capture frames for R13 maintainer-framing scenarios** (run the
  buggy three.js examples under the OpenGPA shim) to get a with_gpa
  measurement on the framework-bug scenario shape.
- **Multi-tier matrix** on a balanced scenario mix (1× R10-shape +
  3× e-shape + 4× R13-shape) once the API key is available.
  Estimated cost ~$25 based on R10v2/R11 means.
- **Stress-test the −LoC-aware suggestion logic** — once added, run
  the same 4-scenario set and confirm with_gpa mode now declines on
  e1/e22/e26 and only fires on R10.
