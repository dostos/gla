# GLA Real-World Evaluation Set — Design Specification

## 1. Overview

This document specifies an expansion of GLA's evaluation set. The existing eval suite (`tests/eval/e1_state_leak.{c,md}` … `e10_compensating_vp.{c,md}`) is a hand-authored synthetic adversarial collection. It is small (10 scenarios), hand-invented (not grounded in reported bugs), and exercises only the minimal-OpenGL-C repro form.

The expansion adds:

1. A **core tier** of 30-40 additional scenarios, each ported from a real issue or fix commit in an OSS graphics project. Same minimal-C repro format as `e1`-`e10`; the difference is that the bug pattern is sourced from a real upstream report rather than invented.
2. A **showcase tier** of 6-10 scenarios authored as real framework apps (three.js, Babylon.js, PlayCanvas) running under the WebGL shim. These exist to validate that GLA's value extends through high-level framework abstractions, not only to raw OpenGL programs.
3. A **coverage log** that records every upstream issue the pipeline reviewed — included and excluded — with a helpfulness classification and, for non-helped cases, an attributed failure mode. The log is the feedback loop: it tells the GLA team which real-world bug classes current GLA covers and which require new features.

All new artifacts are produced by an automated curation pipeline (discover → triage → draft → validate → run eval → classify → commit). The existing `e1`-`e10` scenarios remain untouched.

## 2. Requirements

### 2.1 Functional requirements

**FR-1: Source grounding.** Every scenario in the new set cites an upstream source (GitHub issue, fix commit, or Stack Overflow post with accepted answer). The source URL, type, date, and attribution string are recorded in the scenario's `.md`.

**FR-2: Two-tier structure.**
- **Core tier**: 30-40 scenarios. Repro form is a minimal single-file OpenGL C application compiled via `cc_binary` Bazel targets, identical to the existing `e1`-`e10` structure. Files live in `tests/eval/r<N>_<slug>.{c,md}`.
- **Showcase tier**: 6-10 scenarios. Repro form is a three.js / Babylon.js / PlayCanvas application with `index.html`, `app.js`, `package.json`, and `scenario.md`. Runs in headless Chromium under the GLA WebGL extension. Files live in `tests/eval/showcase/s<N>_<framework>_<slug>/`.

**FR-3: Representative admission.** The pipeline does not filter upstream issues by whether GLA appears likely to help. Any in-scope rendering bug (with a reproducible pattern and clear ground-truth diagnosis) is admitted. The helpfulness determination is recorded on the scenario, not used as an admission filter.

**FR-4: Coverage log.** For each upstream issue the pipeline reviews (whether admitted, rejected at triage, rejected at validate, or rejected at eval), an entry is appended to `docs/superpowers/eval/coverage-log.jsonl`. The human-readable summary `docs/superpowers/eval/coverage-gaps.md` is regenerated from the log after each pipeline run.

**FR-5: Helpfulness classification.** Every committed scenario has three helpfulness-related fields:
- `predicted_helps` — set by the drafting agent based on whether runtime GPU-state inspection plausibly diagnoses the bug.
- `observed_helps` — derived post-eval from the scores (GLA mode correct and code-only wrong → yes; both correct with GLA tokens ≤ 0.5× code-only → yes; both wrong → no; else ambiguous).
- `failure_mode` — populated when `observed_helps=no`; a categorical label (e.g., `shader_compile_not_exposed`, `framework_internal_state`, `needs_temporal_diff`, `driver_specific`) with 1-2 sentences of detail.

**FR-6: Reuse of existing eval harness.** The new scenarios are consumed by the existing `EvalHarness` (`src/python/gla/eval/harness.py`) without changes to its public API. The `ScenarioLoader` is extended to discover scenarios in subdirectories (showcase tier) in addition to the top-level glob.

**FR-7: Automated pipeline.** A Python script `src/python/gla/eval/curation/pipeline.py` orchestrates all stages. Each stage is idempotent per issue URL; re-running the pipeline on a partially-processed issue resumes from the failed stage. The pipeline runs in batches, not continuously.

**FR-8: Validation gate.** Before a scenario commits, a validation stage (a) builds it, (b) runs it headless, (c) captures a frame via GLA, (d) confirms the frame exhibits the symptom described in the `.md`'s `Actual Broken Output` section. Failure logs `rejection_reason: symptom_mismatch_at_validation`.

**FR-9: Eval-in-the-loop acceptance.** A scenario is committed only if the eval harness runs cleanly on it (both modes produce a diagnosis that the scorer can interpret). Scorer-ambiguous scenarios are held for manual review.

### 2.2 Non-functional requirements

**NFR-1: Throughput.** A full batch producing 40 core + 8 showcase scenarios (plus rejected entries for ~100 total reviewed issues) completes in 2-3 wall-clock days of pipeline runtime.

**NFR-2: Budget.** Full batch cost under ~$400 using Claude Opus 4.7 with prompt caching enabled throughout the drafting and triage stages.

**NFR-3: Reproducibility.** The coverage log is append-only. Pipeline runs are deterministic given the same discovery queries and issue snapshots (triage and drafting use temperature 0 or near-0).

**NFR-4: Licensing safety.** Showcase-tier apps consume frameworks as npm dependencies; the scenario code itself is authored by the pipeline (not copy-pasted from upstream repos). Source issues are cited but not inlined.

**NFR-5: CI compatibility.** Core tier scenarios run in existing Bazel-based CI. Showcase tier runs on demand (Chromium + GLA stack is too expensive for default CI), gated by a workflow flag.

### 2.3 Out of scope (v1)

- **Vulkan** scenarios (defer until VK shim stabilizes and Vulkan bug volume justifies the eval infrastructure).
- **Continuous / scheduled discovery**. Pipeline runs in batches on demand; no background service.
- **Auto-generating GLA feature PRs** from coverage gaps. Coverage gap categories inform human-authored feature work; they don't automate it.
- **Non-English upstream issues.** Pipeline skips at discovery.
- **Real-time dashboard.** `coverage-gaps.md` is the dashboard.
- **Migrating existing `e1`-`e10`** into the new schema. They remain as-is; the new schema is a superset so downstream consumers handle both.
- **Running the showcase tier as part of default CI.** Too expensive — showcase runs on a separate workflow triggered manually.

## 3. Architecture

### 3.1 Pipeline overview

```
┌───────────────────────────────────────────────────────────────────┐
│                  Curation Pipeline (per batch)                     │
│                                                                    │
│  ┌──────────┐   ┌────────┐   ┌─────────┐   ┌────────────────┐    │
│  │ Discover │ → │ Triage │ → │  Draft  │ → │    Validate    │    │
│  │ (scoped  │   │ (scope │   │ (repro  │   │ (build, run,   │    │
│  │  search) │   │  check)│   │ + .md)  │   │  symptom match)│    │
│  └──────────┘   └────────┘   └─────────┘   └────────┬───────┘    │
│                                                      │            │
│                                                      ▼            │
│  ┌─────────┐   ┌───────────┐   ┌──────────────────────────┐      │
│  │ Commit  │ ← │ Classify  │ ← │  Run Eval (both modes)   │      │
│  │ to      │   │ (predict, │   │  via existing            │      │
│  │ tests/, │   │  observe, │   │  EvalHarness             │      │
│  │ log     │   │  attribute│   │                          │      │
│  └─────────┘   │  failure) │   └──────────────────────────┘      │
│                └───────────┘                                      │
└───────────────────────────────────────────────────────────────────┘
```

Each stage is a specialized subagent invocation with a narrow remit. Artifacts accumulate in a per-issue workdir (`.eval-pipeline/<issue_id>/`), so any stage can be rerun independently and partial failures do not force restart.

### 3.2 Stage responsibilities

**Discover** — Queries the scoped source list via `gh api` (GitHub Search) and the Stack Overflow API. Rate-limited, cached per run. Produces `queue.jsonl` with one candidate per line (`url`, `source_type`, `weight_bucket`, raw metadata). Stops when the batch quota (default 20 candidates per run, tunable) is reached.

**Triage** — For each candidate, fetches and reads the issue thread or commit diff. Classifies:
- `in_scope` — rendering bug with observable GPU symptom and a discoverable ground-truth diagnosis (maintainer explanation in thread, commit message, or accepted SO answer).
- `out_of_scope` — compile error, build bug, documentation issue, non-visual logic bug, or insufficient information.
- `ambiguous` — queued for drafting but tagged; if drafting fails or validation fails, the ambiguous tag flags the issue for manual review.

Dedupes by `root_cause_fingerprint` (LLM-generated short key representing the bug pattern, e.g., `state_leak:texture_binding_between_draws`). Fingerprint comparison is exact-string on the `<category>:<specifics>` form; the LLM is prompted to normalize vocabulary (the categories are a closed set seeded with `state_leak`, `uniform_lifecycle`, `matrix_math`, `numeric_precision`, `depth_precision`, `winding_culling`, `sync`, `shader_compile`, `bind_point_collision`, `other`; new categories may be added but not silently renamed). A match against an already-committed scenario still produces a coverage-log entry with `rejection_reason: duplicate_of_existing_scenario` and `scenario_id` set to the matching committed scenario; drafting is skipped.

**Draft** — Produces the scenario artifacts:
- **Core tier**: minimal OpenGL C file (target: <250 LOC, single `main()`, uses GLX or EGL for context creation, no external dependencies beyond GL/X11/m) + structured `.md` following the schema in §3.4. The bug pattern is ported; framework code from the source is not copied.
- **Showcase tier**: `index.html` + `app.js` + `package.json` + `scenario.md`. `app.js` consumes the framework as an npm dependency and reproduces the bug pattern in a minimal user-code form (not a replay of the upstream app).

Drafting prompts require citing the upstream thread or commit for every diagnostic claim in the `.md`. Scenarios without citations fail validation.

**Validate** — Builds the scenario (Bazel for core, `npm install && npm run build` for showcase). Runs it headless (Xvfb for core, Puppeteer for showcase). Captures a frame via the appropriate GLA shim. Checks the captured frame against the scenario's declared `## Bug Signature` (§3.4) using either a heuristic comparator (6-8 signature types) or, as fallback, an LLM visual check. Failure logs `rejection_reason: symptom_mismatch_at_validation`.

**Run Eval** — Invokes `EvalHarness.run_scenario(scenario_id, mode, agent_fn)` for `mode in {"with_gla", "code_only"}`. Records `correct_diagnosis`, `correct_fix`, `input_tokens`, `output_tokens`, `tool_calls`, `num_turns`, `time_seconds` for each mode. This is also the eval-in-the-loop gate: if the scorer cannot interpret either mode's output, the scenario is held for manual review (`rejection_reason: eval_scorer_ambiguous`).

**Classify** — Emits three fields to the scenario `.md` and coverage log:
- `predicted_helps` — already set by the drafting agent.
- `observed_helps` — derived from eval scores. Let `ratio = with_gla_total_tokens / code_only_total_tokens`. Rules evaluated in order; first match wins:
  1. `correct_with_gla AND NOT correct_code_only` → `yes`.
  2. `NOT correct_with_gla AND correct_code_only` → `no` (GLA caused regression).
  3. `both_wrong` → `no`.
  4. `both_correct AND ratio < 0.5` → `yes`.
  5. `both_correct AND ratio > 0.8` → `no`.
  6. Everything else (e.g., `both_correct AND 0.5 ≤ ratio ≤ 0.8`) → `ambiguous`.
- `failure_mode` — when `observed_helps=no`, a post-hoc subagent categorizes why. Categories are open-ended but clustered: new failure modes appear over time as coverage gaps are discovered. Initial seed list: `shader_compile_not_exposed`, `framework_internal_state`, `needs_temporal_diff`, `driver_specific`, `scorer_ambiguous`, `bug_requires_multi_frame_capture`.

**Commit** — Writes scenario files to `tests/eval/` (core) or `tests/eval/showcase/<id>/` (showcase). Appends a row to `docs/superpowers/eval/coverage-log.jsonl`. Regenerates `docs/superpowers/eval/coverage-gaps.md` from the updated log.

### 3.3 Discovery scope (source list)

**Default query set**, declared as constants in the pipeline script (the agent does not invent queries):

```
# Framework issue trackers — primary (target 70% of discoveries)
repo:mrdoob/three.js is:issue label:"Rendering" -label:"Help (please use the forum)"
repo:BabylonJS/Babylon.js is:issue label:"bug"
repo:playcanvas/engine is:issue label:"area: rendering"
repo:godotengine/godot is:issue label:"topic:rendering"
repo:bevyengine/bevy is:issue label:"A-Rendering"

# Fix commits — secondary (target 20%)
repo:<same repos> type:commit ("fix:" OR "bugfix:") AND (
  "render" OR "shader" OR "visual" OR "draw" OR "z-fight" OR
  "precision" OR "culling" OR "depth" OR "uniform" OR "texture"
)

# Stack Overflow — tail (target 10%)
tag:webgl has:accepted_answer
tag:opengl has:accepted_answer
tag:glsl has:accepted_answer
```

Weights are soft targets, not hard quotas. If fix-commit mining produces higher-quality candidates on a given run, the allocation shifts within the batch quota.

### 3.4 Scenario `.md` schema

The schema extends the current `ScenarioMetadata` dataclass. New sections are **Source**, **Tier**, **API**, **Framework**, **Predicted GLA Helpfulness**, **Observed GLA Helpfulness**, **Failure Mode**, **Bug Signature**.

```markdown
# R12: Material Clone Uniform Loss

## Source
- **URL**: https://github.com/mrdoob/three.js/issues/12345
- **Type**: issue
- **Date**: 2024-03-17
- **Commit SHA**: (n/a, issue only)
- **Attribution**: Reported by @user, resolved in PR #12346 by @maintainer

## Tier
core

## API
webgl2

## Framework
none  # (the core-tier port uses raw OpenGL to exhibit the same pattern)

## Bug
[textual description — same as existing E1-E10 format]

## Expected Correct Output
...

## Actual Broken Output
...

## Ground Truth Diagnosis
[required to cite the upstream thread or commit]

## Difficulty Rating
[existing format]

## Adversarial Principles
[existing format]

## How GLA Helps
[existing format]

## Bug Signature
```yaml
type: color_histogram_in_region
spec:
  region: [0.4, 0.4, 0.6, 0.6]      # normalized (x0, y0, x1, y1)
  dominant_color: [0.8, 0.2, 0.2, 1.0]
  tolerance: 0.1
```

## Predicted GLA Helpfulness
- **Verdict**: yes
- **Reasoning**: The bug manifests as a shader uniform not being updated between draw calls.
  `inspect_drawcall(dc_id, include=["shader"])` directly exposes the stale uniform value.

## Observed GLA Helpfulness
*(populated post-eval)*
- **Verdict**: yes
- **Evidence**: correct_with_gla=True, correct_code_only=False, token_ratio=0.31

## Failure Mode
*(populated only when observed_helps=no; omitted otherwise)*
```

Showcase scenarios use the same schema, renamed file (`scenario.md`), and stored in the scenario subdirectory with `index.html`, `app.js`, `package.json`.

### 3.5 Coverage log

`docs/superpowers/eval/coverage-log.jsonl` — append-only JSONL, one entry per reviewed issue:

```json
{
  "issue_url": "https://github.com/mrdoob/three.js/issues/12345",
  "reviewed_at": "2026-04-17T10:23:45Z",
  "source_type": "issue",
  "triage_verdict": "in_scope",
  "root_cause_fingerprint": "shader_uniform_state:clone_loses_uniforms",
  "outcome": "scenario_committed",
  "scenario_id": "r12_material_clone_uniform_loss",
  "tier": "core",
  "rejection_reason": null,
  "predicted_helps": "yes",
  "observed_helps": "yes",
  "failure_mode": null,
  "eval_summary": {
    "with_gla": {"correct_diagnosis": true, "total_tokens": 1820},
    "code_only": {"correct_diagnosis": false, "total_tokens": 5940}
  }
}
```

Rejected entries use the same schema with `scenario_id: null` and a populated `rejection_reason` chosen from a closed set:
- `out_of_scope_compile_error`
- `out_of_scope_not_rendering_bug`
- `out_of_scope_insufficient_info`
- `duplicate_of_existing_scenario`
- `not_reproducible`
- `symptom_mismatch_at_validation`
- `eval_scorer_ambiguous`
- `non_english`

### 3.6 Coverage gaps summary

`docs/superpowers/eval/coverage-gaps.md` — human-readable, regenerated from the JSONL log:

```markdown
# GLA Coverage Gaps

*Last regenerated: 2026-04-17 by pipeline run batch-2026-04-17a*

## Summary
- Issues reviewed: 137
- Scenarios committed: 43 (31% admission rate)
  - Core: 36
  - Showcase: 7
- Helpfulness prediction accuracy: 84% (32 observed_helps match 38 predicted_helps out of 43 scored)

## Helpfulness Distribution
| observed_helps | count | % of committed |
|---|---|---|
| yes | 32 | 74% |
| no | 8 | 19% |
| ambiguous | 3 | 7% |

## Failure Modes (observed_helps=no, count: 8)

### shader_compile_not_exposed (count: 3)
Scenarios where the bug is a silent shader compile/link failure...
**Example scenarios**: r18, r24, r31
**Suggested GLA feature**: expose glGetShaderInfoLog / glGetProgramInfoLog
results per draw call's shader program.

### framework_internal_state (count: 2)
...

### (one section per distinct failure mode)

## Rejection Breakdown (94 total)
- duplicate_of_existing_scenario: 31
- out_of_scope_not_rendering_bug: 28
- symptom_mismatch_at_validation: 14
- not_reproducible: 11
- out_of_scope_insufficient_info: 7
- eval_scorer_ambiguous: 3
```

### 3.7 Showcase tier runtime

```
Pipeline (Python)
  │
  ├─► Puppeteer driver (Node.js) ──► Chromium (headless) + GLA WebGL extension
  │                                        │
  │                                        ▼  (target app)
  │                                    three.js app running
  │                                        │
  │                                        ▼
  │                                   GLA WebGL shim
  │                                        │ WebSocket
  │                                        ▼
  └─► GLA Node.js bridge ──► Unix socket ──► GLA core engine
                                                  │
                                                  ▼
                                          REST API + MCP
```

New components:

- `src/python/gla/eval/curation/showcase_runner.py` — launches the Puppeteer + GLA stack, waits for the "frame captured" signal from the shim, hands off the running session to the eval agent (which queries GLA via MCP).
- `tests/eval/showcase/_harness/run.js` — reusable Puppeteer boilerplate: `chromium.launch({ args: ['--load-extension=<gla-webgl-ext-path>'] })` → loads the showcase app from a local file:// URL → waits for `window.__GLA_READY__` (set by the shim after first frame capture) → signals pipeline over stdout → keeps Chromium alive for the duration of the eval session.
- `tests/eval/showcase/_harness/package.json` — shared Puppeteer dependency; each showcase scenario directory has its own `package.json` for the framework dependency.

**Code-only mode for showcase** — important asymmetry: the agent sees `app.js` (user code) but **not** the framework's source. This mirrors the real developer experience where three.js is consumed as a library.

Enforcement mechanism: the `code_only` mode's `read_source` tool (in `EvalHarness._build_tools`) is scoped to the showcase scenario's own directory (`tests/eval/showcase/<id>/`), excluding `node_modules/`. The agent may read `app.js`, `index.html`, `package.json`, and `scenario.md`, but `read_source` rejects any path under `node_modules/`. The agent is informed of this restriction in its system prompt ("You may not read the framework's source. Treat the framework as a black-box library."). No filesystem sandboxing is required beyond the tool-level check.

With GLA enabled, the agent can query actual GL calls the framework generated — exactly where GLA's value proposition lives for framework users.

### 3.8 Symptom-match validation

The weakest link in the pipeline. Concrete approach:

**Declared signatures** — the scenario `.md` includes a `## Bug Signature` section containing a fenced YAML block. The block parses to `{type: str, spec: dict}`; `signature_matchers.py` dispatches on `type` to a per-type comparator that validates `spec` against a declared schema. Drafting prompts are constrained to emit exactly one fenced YAML block in this section. Signature types (initial set):

| Type | Spec | Example |
|---|---|---|
| `color_histogram_in_region` | dominant color + region rect | z-fighting produces mixed colors in a region |
| `unexpected_color` | expected color + actual color + pixel coord | wrong texture bound |
| `nan_or_inf_in_uniform` | which uniform, which draw call | NaN propagation |
| `high_overdraw` | pixel coord, min depth-chain length | overdraw scenarios |
| `missing_draw_call` | expected draw call count, actual | object not submitted |
| `unexpected_state_in_draw` | pipeline state field, expected vs actual | scissor leak |
| `framebuffer_dominant_color` | overall framebuffer dominant color | solid-color failures (e.g., all black) |

**Heuristic comparators** — one Python function per signature type. Operates on the captured framebuffer PNG + GLA's draw-call metadata.

**LLM fallback** — for signatures not covered by heuristics, or when the heuristic returns ambiguous, a small LLM call judges: "Given the scenario's `Actual Broken Output` description and this captured framebuffer, does the frame exhibit the described bug?"

**Meta-eval** — 10% random sample of committed scenarios gets human review. False positives (pipeline admitted scenarios that don't actually exhibit the bug) feed back into the drafting and signature-matcher prompts.

## 4. Data Flow

1. Pipeline is invoked: `python -m gla.eval.curation.pipeline --batch <N> --config <cfg.yaml>`.
2. **Discover** runs declared queries, writes `queue.jsonl`. Deduplicates against the coverage log (skip already-reviewed URLs).
3. For each URL in the queue, pipeline runs stages 2-6 sequentially. Each stage writes its output to `.eval-pipeline/<issue_id>/<stage>.json`. Stages skip if their output already exists and the input hash matches.
4. **Triage** fetches thread/diff, produces `triage.json` with verdict + fingerprint. Out-of-scope or duplicate → log entry, skip to next issue.
5. **Draft** produces scenario files in a staging directory. In-scope ambiguous issues are still drafted but flagged.
6. **Validate** builds and runs; produces `validate.json` with pass/fail and frame capture. Failure → log entry with `rejection_reason: symptom_mismatch_at_validation`, skip.
7. **Run Eval** invokes `EvalHarness` twice (both modes), produces `eval.json`. Scorer-ambiguous → log entry with `rejection_reason: eval_scorer_ambiguous`, hold for manual review.
8. **Classify** produces `classify.json` with all three helpfulness fields.
9. **Commit** moves files from staging to `tests/eval/` or `tests/eval/showcase/`. Appends log entry. Regenerates `coverage-gaps.md`.
10. Pipeline exits. A second invocation resumes from where the first left off (per-issue staging dirs persist).

## 5. Testing strategy

**Unit tests** (`tests/python/eval/curation/`):
- `test_discovery.py` — stubbed GitHub/SO API responses; assert correct queries, dedup, rate-limit handling.
- `test_triage.py` — 20 hand-labeled fixture issues; assert triage verdicts are stable.
- `test_scenario_schema.py` — round-trip parse of generated scenarios through `ScenarioLoader`; assert all new fields extract cleanly and existing E1-E10 still parse.
- `test_signature_matcher.py` — per-signature-type cases with synthetic framebuffer PNGs.
- `test_coverage_log.py` — append / read / regenerate cycle for JSONL + markdown summary.

**Integration test** (`tests/python/eval/curation/test_pipeline_end_to_end.py`):
Runs the whole pipeline against a fixture of 3 issues covering: (a) one that should become a committed scenario, (b) one that should be rejected at triage, (c) one that should fail at validate. Asserts correct outcome and that the coverage log has 3 new rows.

**Meta-eval** (one-time): human reviews 10% random sample of first batch; findings regenerate pipeline prompts.

## 6. Integration with existing harness

- `ScenarioLoader` extended to glob `tests/eval/*.md` AND `tests/eval/showcase/*/scenario.md`. File path parsing distinguishes tier.
- `ScenarioMetadata` dataclass gains fields: `source_url`, `source_type`, `source_date`, `tier`, `api`, `framework`, `bug_signature`, `predicted_helps`, `observed_helps`, `failure_mode`. All optional (existing E1-E10 parses without them).
- `EvalHarness.run_scenario` unchanged.
- `EvalResult` gains optional `observed_helps` and `failure_mode` fields for post-eval writeback.

## 7. Risks and mitigations

| Risk | Mitigation |
|---|---|
| Drafting agent fabricates diagnoses not in upstream thread | Stage 3 prompt requires quoting the thread/commit for every diagnostic claim. Validate stage rejects `.md`s with no citation. |
| Showcase apps copy too much upstream code (licensing) | Showcase apps consume frameworks as npm deps. `app.js` is authored from the issue's description, not copy-pasted. Each `scenario.md` cites its source. |
| Symptom-match heuristic false positives | LLM fallback + 10% human meta-eval on each batch. |
| Agent-driven discovery drifts | Queries are declared constants in pipeline code, not agent-invented. |
| Eval-in-the-loop cost dominates | Eval results cache by `(scenario_files_hash, agent_version)`. Rerunning pipeline on unchanged scenarios reuses prior eval. |
| Coverage log staleness | `reviewed_at` timestamps. A quarterly refresh script can re-triage old entries and flag ones where upstream was fixed. |
| Duplicate scenarios | Triage dedupes by `root_cause_fingerprint` against committed scenarios. |
| Upstream repo rate limits | `gh api` respects limits automatically; pipeline uses conditional requests (ETags) and caches raw responses per-run. |

## 8. File structure

```
src/python/gla/eval/
  curation/                           # NEW
    __init__.py
    pipeline.py                        # main orchestrator CLI
    discover.py                        # GitHub/SO query runner
    triage.py                          # triage subagent
    draft.py                           # drafting subagent (core + showcase)
    validate.py                        # build + symptom-match
    classify.py                        # helpfulness + failure-mode
    signature_matchers.py              # heuristic comparators per signature type
    showcase_runner.py                 # Puppeteer harness wrapper
    coverage_log.py                    # JSONL + markdown summary
  scenario.py                          # EXTENDED — new fields, subdir discovery

tests/eval/
  e1_state_leak.{c,md}                # existing, unchanged
  ...
  e10_compensating_vp.{c,md}          # existing, unchanged
  r1_<slug>.{c,md}                    # NEW core tier
  r2_<slug>.{c,md}
  ...
  showcase/                           # NEW showcase tier
    _harness/
      run.js                          # Puppeteer boilerplate
      package.json
    s1_three_<slug>/
      index.html
      app.js
      package.json
      scenario.md
    ...

tests/python/eval/curation/          # NEW tests
  test_discovery.py
  test_triage.py
  test_scenario_schema.py
  test_signature_matcher.py
  test_coverage_log.py
  test_pipeline_end_to_end.py

docs/superpowers/eval/                # NEW dir
  coverage-log.jsonl                  # append-only log
  coverage-gaps.md                    # human-readable summary (regenerated)
```

## 9. Budget and throughput

Rough per-issue cost estimates, Claude Opus 4.7 with prompt caching:

| Stage | Input tokens | Output tokens | Approx cost |
|---|---|---|---|
| Triage | ~3,000 (thread) | ~500 | $0.05 |
| Draft (core) | ~8,000 | ~4,000 | $0.30 |
| Draft (showcase) | ~15,000 | ~8,000 | $0.60 |
| Eval (both modes) | variable | variable | $0.50-1.50 |
| Classify + failure-mode | ~2,000 | ~500 | $0.10 |

Per-scenario total: ~$1.00-2.50 (core), ~$1.50-3.00 (showcase).

Assuming a ~3× review-to-admission ratio (rejections cost triage but not drafting for early rejects, or triage+draft+validate for late rejects):

- Full batch of 40 core + 8 showcase with ~100 reviewed issues: **~$250-400**.
- Wall-clock: ~2-3 days.

Parallelism: the pipeline processes up to `N_WORKERS` issues concurrently (default 4). Discovery is serial (API rate limits). Triage, draft, and validate parallelize freely across issues. Eval (Run Eval stage) parallelizes up to the number of eval-harness instances that can coexist on the host — for core-tier, bounded by available Xvfb displays (default 4); for showcase-tier, bounded by Chromium RAM (default 2). Within a single issue, stages remain serial.

A human-authored equivalent is ~60-80 hours of skilled graphics-developer work. The pipeline is cost-competitive and reproducible.

## 10. Milestones

1. **M-EV1**: Pipeline scaffolding (stages as stubs, scenario schema extension, coverage log format). Hand-run one issue end-to-end to validate the pipeline contracts.
2. **M-EV2**: Discovery + triage stages implemented; produce a queue of 50 candidate issues and triage results for manual spot-check.
3. **M-EV3**: Drafting stage for core tier (OpenGL C ports). Produce 5 scenarios end-to-end through validate.
4. **M-EV4**: Eval-in-the-loop and classify stages. Using the 5 scenarios from M-EV3 plus a fresh discovery batch, produce a first cohort of 10 committed scenarios with helpfulness classification.
5. **M-EV5**: Full core-tier batch (target 30-40 scenarios committed).
6. **M-EV6**: Showcase runtime (Puppeteer + WebGL extension integration).
7. **M-EV7**: Drafting stage for showcase tier. First 2 showcase scenarios end-to-end.
8. **M-EV8**: Full showcase batch (target 6-10 scenarios committed) + coverage-gaps.md generation + first GLA feature requests derived from failure modes.

## 11. Key design decisions

| Decision | Choice | Rationale |
|---|---|---|
| Two tiers | Core (minimal C) + Showcase (framework apps) | Keeps quantitative eval cheap to run; showcase demonstrates the framework-debugging value proposition where GLA's abstraction-bridging matters most. |
| Admission filter | Representative sampling (no helpfulness filter) | Honest benchmarking; rejection stats become a contribution themselves. |
| Helpfulness classification | Predicted + observed + failure-mode attribution | Makes the feedback loop actionable — we can identify specific GLA feature gaps rather than just reporting a helpfulness percentage. |
| Pipeline structure | Multi-stage with eval-in-the-loop gate | Reliable; stages are independently rerunnable; eval validation catches non-reproducible scenarios. |
| Seeding | Declared queries run by agent | Prevents agent drift into irrelevant sources while keeping the per-issue processing autonomous. |
| Sources | Framework trackers (70%) + fix commits (20%) + SO (10%) | Framework trackers have the best signal-to-noise for visual bugs; fix commits give uniquely reliable ground truth; SO covers the tail. |
| Tiered reproducibility | Patterns for core, faithful replays for showcase | Matches each tier's purpose: quantity vs. authenticity. |
| `e1`-`e10` preservation | Keep as-is; new scenarios use `r`/`s` prefix | Existing synthetic set remains valid; new schema is a superset so tooling handles both. |
| Validation gate | Heuristic signature match + LLM fallback + 10% human meta-eval | Addresses the "does the repro actually show the bug?" risk in layers. |
| Coverage log format | Append-only JSONL + regenerated markdown summary | JSONL is machine-consumable; markdown is the human feedback surface. |

## 12. References

- Current eval harness: `src/python/gla/eval/`
- Existing scenario format: `tests/eval/e1_state_leak.{c,md}`
- Main GLA design spec: `docs/superpowers/specs/2026-04-16-gla-design.md` (§9 Evaluation Scenarios)
- Claude API prompt caching (via claude-api skill): used throughout drafting and triage stages.
