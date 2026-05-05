# OpenGPA Eval — Next Steps

## What We Learned

Minimal single-file reproductions (200 lines) are too easy for any LLM model tier.
All 3 rounds: 100% accuracy for both code-only and with-OpenGPA across Haiku and Sonnet.

**Root cause**: The bug IS the entire codebase. There's nothing to search through.

## What Would Show OpenGPA's Value

OpenGPA's value appears when the agent must choose between:
- **Reading 50,000 lines** of framework source to trace state (expensive, slow)
- **Querying 3 OpenGPA endpoints** to see the actual runtime state (cheap, fast)

This requires eval scenarios that include the **actual upstream codebase**, not a minimal reproduction.

## The Plan: Real Codebase Eval

### Setup
1. Use `SnapshotFetcher` to clone upstream repos at the pre-fix commit SHA
2. Give the agent: upstream source (Three.js/Godot) + the bug report + the app code
3. The agent must find the root cause in the framework source

### Two Modes
- **Code-only**: Agent reads bug report + app code + framework source. Must grep/read through framework files to find the state management bug. Token-expensive.
- **With OpenGPA**: Agent reads bug report + app code + queries OpenGPA for runtime state. Can skip reading framework source entirely if the captured state reveals the issue.

### Metrics
- **Tokens consumed**: How much framework source did the agent read?
- **Files opened**: How many framework files did the agent explore?
- **Accuracy**: Did it find the correct root cause?
- **Time**: Wall clock to diagnosis

### Expected Results
- Code-only: reads 5-20 framework files (10,000-50,000 tokens) to trace the state
- With OpenGPA: reads 0-2 framework files (0-5,000 tokens) because the runtime state directly shows the problem

### Candidates (from SnapshotFetcher)

Scenarios that already have upstream snapshot references:
- Issues with `upstream_snapshot.repo` and `upstream_snapshot.sha` in their metadata
- The snapshot contains the actual buggy framework code at the pre-fix commit
- The `relevant_files` list tells which framework files contain the root cause

### Implementation
1. `SnapshotFetcher.fetch(repo, sha)` → clones to `/data3/snapshots/{repo}/{sha}/`
2. Eval agent gets the snapshot path as a "working directory" to explore
3. For code-only: agent can `Read` any file in the snapshot
4. For with-OpenGPA: agent can also query the REST API

### Priority Candidates (multi-file, state bugs)

| Issue | Framework | Root Cause Location | Files to Read |
|-------|-----------|--------------------|----|
| three.js #26762 (depthMask) | Three.js r157 | `src/renderers/webgl/WebGLState.js` | ~5 files |
| three.js #25618 (texture cache) | Three.js r155 | `src/renderers/webgl/WebGLTextures.js` | ~8 files |
| godot #76334 (blend equation) | Godot 4.1 | `drivers/gles3/rasterizer_scene_gles3.cpp` | ~10 files |
| three.js #32444 (transmission) | Three.js r182 | `src/renderers/webgl/WebGLRenderer.js` | ~6 files |

## Status

- [x] Minimal reproduction eval (rounds 1-3): 100% accuracy, too easy
- [x] Curation pipeline discovers real issues
- [x] SnapshotFetcher clones upstream repos
- [x] Scenarios have upstream_snapshot metadata
- [x] Eval harness passes snapshot path to agents (upstream tools wired)
- [x] Live capture unblocked: `runner.py` derives nested-taxonomy Bazel
      target paths so `run_with_capture` actually emits frames
- [x] `fix_parent_sha` populated end-to-end so the snapshot serves the
      buggy parent state, not the post-fix state
- [x] Scenario verifier (`gpa.eval.curation.verify`) with static /
      network / build tiers; failed scenarios moved to
      `tests/eval-quarantine/`
- [x] Re-run R12-style cohort with capture working + verified scenarios
      (R12c, 2026-05-05): with judge enabled, **10/14 with_gla, 10/14
      code_only** — was 1/14 with stale snapshots. 10× lift from
      infrastructure alone.
- [x] Measure token reduction from OpenGPA on the cleaned cohort:
      with_gla 147k vs code_only 163k total (≈10% reduction overall).
      with_gla matches code_only at 71% solved while using 90% of the
      tokens. See `docs/eval-results.md` "R12c+R12d with LLM-judge".
- [x] Wire LLM-judge as default scorer. Reads the actual fix-PR diff
      and grades semantic match. Lifted R12c from 6/14 → 10/14 just
      by upgrading partial-hit verdicts. Cost ~$0.07 per 14-scenario
      cohort. CLI flags: `--judge / --no-judge / --judge-backend /
      --judge-model / --judge-cache-dir`.
- [x] Fix three silent scoring bugs surfaced by R12c→R12d comparison:
      regex truncation of `.cpp`/`.tsx`/`.gdshader` paths; judge
      eligibility too narrow (prose only); depth-1 snapshot couldn't
      diff merge commits. All three fixed in commit `35c9597`.

## Forensic analysis of remaining R12c failures (2026-05-05)

Methodically broke down the 4 unsolved R12c verdicts across modes
(union: 5 distinct scenario failures, 3 of which fail in both modes).

### Failure taxonomy

| # | Scenario | Modes | Type | Root cause |
|---|---|---|---|---|
| 1 | cesium_camera_jumps | both | **scenario quality** | Agent diagnosed PR #13098 (Float32→Float64 fix); harness reference is PR #12983 (sync/buffer fix). Both PRs closed the same user issue. Mining picked one. |
| 2 | godot_4_2_world_environment | both | **reasoning depth** | Agent stopped at first plausible mechanism (luminance_multiplier in copy path); actual fix is a buffer-format change (UNORM → half-float). Hit 2/13 files. judge=partial. |
| 3 | godot_performance_on_android | both | **scenario quality** | Mining picked an Android Java/Kotlin lifecycle refactor PR; user report is a Vulkan Mali-G52 perf regression. Snapshot date predates regression. Files don't match bug class. |
| 4 | godot_weird_shadow | wg solved, co failed | **stochastic variance** | with_gla: debanding (correct). code_only: specular_occlusion (wrong rabbit hole). Same model, same materials — agent grepped different keywords. |
| 5 | godot_wrong_position | wg failed, co solved | **file-mismatch reasoning** | with_gla diagnosed correct root cause (XR multiview reprojection mismatch) but proposed fix in `scene_forward_clustered.glsl` (consumer side); maintainer fixed it in `sky.cpp`. judge=partial. |

### Distribution

- Scenario quality: 2/5 (40%) — mining picked wrong/incomplete fix
- Reasoning correct but file-mismatch: 1.5/5 (godot_4_2 partial, wrong_position full)
- Reasoning shallow: 1/5 — stopped at first plausible explanation
- Stochastic agent variance: 1/5 — same problem, different exploration → different outcome

### Token-spend signal

**Solved scenarios use half the tokens of failed ones** (avg 8k vs 16k
output tokens, 18 vs 33 tool calls). When an agent doesn't have the
right hypothesis it grinds — repeated greps, multi-file reads,
backtracking. Token spend is a real-time confidence indicator.

| Cohort | Solved avg | Failed avg | Ratio |
|---|---|---|---|
| with_gla | 8.1k tokens | 16.4k tokens | 2.0× |
| code_only | similar pattern | — | — |

Fast-solve regime: web-map scenarios (2-5k tokens, 9-16 tool calls).
Slow-solve regime: multi-file godot refactors (8-25k tokens, 20-64
tool calls). The size of the fix predicts the cost.

## Systematic improvement backlog

Ranked by expected solve-rate gain × inverse cost. The flywheel's
final step is choosing what ships next, not running another round.

### P0 — fix mining quality (addresses 40% of failures)

**Multi-PR detection**: cesium and android-perf show that one user
issue can be closed by multiple PRs. The mining pipeline currently
picks the first cited PR. Two changes:

1. **List ALL PRs that closed the issue.** When the issue body cites
   multiple PR numbers (`Closes #X`, `Fixes #Y`, `Closes #Z`), record
   them in `fix.fix_pr_url` as a list. The judge accepts agent
   diagnosis matching ANY listed fix.
2. **Mining-quality verifier**: post-mine check that the listed
   `fix.files` semantically relate to the user report. Heuristic: do
   the file paths share keywords with the issue title? If not, flag
   for review (probably mis-classified bug_class or wrong PR).

Cost: ~50 lines in `extract_draft.py` + verifier addendum.
Expected lift: closes the cesium + android-perf failures → +2/14.

### P1 — pre-flight scoping hint (addresses reasoning-shallow + file-mismatch)

When the agent starts, give it a **shortstat-only** hint from the fix
PR diff: "the canonical fix touches 13 files in `servers/rendering/`,
none in `editor/` or `core/`." This calibrates the agent's search
scope without leaking the actual answer:

- Tells them how big a fix to look for (1 file vs 13)
- Tells them what *area* of the codebase
- Doesn't reveal which files specifically

Implementation: extend the prompt to include `fix.shortstat_summary`
(generated at curation time from `git show --shortstat`). Or compute
on demand in `_select_prompt_for_scenario` from the snapshot's
`fix_sha`.

Cost: ~30 lines in scenario.yaml schema + curation pipeline + harness
prompt rendering.
Expected lift: closes godot_4_2_world_environment (agent would have
known to look for buffer-format changes, not just multiplier paths)
and godot_wrong_position (scope of fix points at sky.cpp not glsl).
+1.5/14.

### P2 — tool-call budget + checkpoint

Failure correlates with tool-call grind. Two complementary measures:

1. **Hard budget**: After 30 tool calls without a confident hypothesis,
   the harness injects a checkpoint message: "You've spent 30 tool
   calls; summarize what you know in 3 bullet points and what you'd
   investigate next." Forces synthesis; often surfaces the agent's
   own confusion.
2. **Soft signal**: Surface tool-call count to the agent so they can
   self-throttle. Currently they have no awareness of how much they've
   spent.

Cost: ~80 lines in cli_agent (tool-counter wrapper around each tool
invocation) + prompt update.
Expected lift: tightens the failure tax. Won't lift solves directly
but cuts ~30% of wasted tokens. Important for cohort scaling.

### P3 — ensemble agents (addresses stochastic variance)

For scenarios near the threshold (judge=partial OR file_score ∈
[0.2, 0.5]), run a second independent agent attempt. Take the union
of cited files; have the judge score the combined diagnosis. Cost
~$0.10/scenario × ~30% of scenarios = $0.03 net average increase.

godot_weird_shadow: code_only failed because of one wrong grep
choice. A second attempt would have likely landed on debanding too.

Cost: ~50 lines in cli_agent (re-run logic) + judge fallback path.
Expected lift: closes godot_weird_shadow co failure. +0.5/14.

### P4 — directory-aware file scoring

Agents that name 3 files all in the right *directory* of a 13-file
fix have made a stronger claim than naive recall=0.23 suggests.
Weight file-overlap by:

- 1.0 for exact-path hits
- 0.5 for same-immediate-directory hits
- 0.25 for same-package-prefix hits (e.g. `servers/rendering/`)

Cost: ~40 lines in `scorer_prose` + `scorer.py`.
Expected lift: marginal — judge already covers most of these. Worth
~+0.3/14 on godot multi-file cases.

### P5 — re-run R12d with the lighter prompt

R12d (heavy "READ FIRST" prompt) collapsed agent investigation 5×.
The lighter prompt is now in main (`35c9597`). Re-run those same 14
scenarios; expected to recover R12c-level numbers (10/14).

Cost: 1 hour wall time + ~$0.50 in claude-cli costs.
Validates that the prompt revert was the right call.

## Decision: ship P0 + P1 next

Largest expected lift × smallest implementation cost. P0 fixes
*scenario quality* (2/14 → 0/14 of that failure mode). P1 gives the
agent the search scope it currently lacks (1.5/14 → 0/14 of that
mode). Combined: 6.5/14 max ceiling lift, realistic 3/14.

P2-P5 wait for the next iteration; their effects compound only when
P0/P1 are in place.

## Open questions for next iteration

### 1. Reverse the R12d collapse

R12d (2026-05-05, with the heavy "READ FIRST" prompt) ran 5×
smaller agent responses than R12c (2k vs 10k tokens average) and
solved 2-4/14 vs R12c's 10/14. The heavy prompt prioritised JSON
emission over investigation. The lighter prompt (commit `35c9597`)
should restore investigation depth — re-run R13 with the new prompt
+ judge default and confirm it matches R12c's 10/14.

### 2. WebGL coverage

OpenGPA ties code_only on web-map at 71% (3/6 each in R12c with
judge). The shim still doesn't intercept browser WebGL — the
tier-mismatch warning prevents bad with_gla token spend, but real
*lift* on browser scenarios needs a WebGL backend. Two paths:

1. **Gate at the harness** (done in `d7bd4bb`) — at least prevents
   regressions and warns the user. Already shipped.
2. **Add a WebGL backend**: extend `src/shims/webgl/` to surface
   frame state via the same FrameProvider ABC. Real engineering;
   only worth it once we have hard evidence that WebGL frame state
   would close real diagnoses (R13 will test this).

### 3. Mining quality bar

R12c judges showed 4 scenarios where with_gla solved but code_only
didn't (or vice versa). When the judge says `none` for both modes,
the scenario may be **unsolvable from the materials we provide**
(the relevant context isn't in the snapshot or user report). Need a
"scenario-level difficulty" gate — if both modes get `judge=none`
across multiple model tiers, requalify the scenario or move it to
quarantine.

### 4. Cost of the judge

Sonnet judge runs at ~$0.005 per scenario × N modes. At 100-scenario
cohorts × 2 modes × 3 model tiers = $3 per round. Acceptable but
worth a daily-budget knob when we scale up.
