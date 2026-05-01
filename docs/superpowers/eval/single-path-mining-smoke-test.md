# Single-Path Mining — Smoke Test Results

_Date: 2026-05-01_

## Setup

- Pipeline: `gpa.eval.curation.run` (commit `bf48744` on `feat/single-path-mining`)
- Corpora measured:
  - **`framework_app_dev_hard_cases.yaml`** — 22 declared queries, all `is:closed reason:not_planned` (closed without code-fix). Run dir: `/tmp/smoke-eval-pipeline/runs/2026-05-01-074525-33fff3b1/`.
  - **`generalization_queries.yaml`** — broader `is:closed` queries that historically have yielded fix PRs. Batch quota 40. Run dir: `/tmp/smoke-eval-pipeline-gen/runs/2026-05-01-075052-a21d3d81/`.
  - **15-URL committed-history sample** — `random.seed(42)` sample from `coverage-log.jsonl` (101 historically-committed scenarios). All 15 are confirmed-fix-PR scenarios per coverage log.

## Results — extraction success on selected

| Corpus | Discovered | Selected (post-triage) | Extracted | Validated |
|---|---|---|---|---|
| framework_app_dev_hard_cases | 20 | 1 | (skipped — `--max-phase select`) | — |
| generalization | 40 | 3 | **3 (100%)** | **3 (100%)** |

**O1 metric:** extraction success rate on candidates that pass SELECT = **3/3 = 100%**.

### O1 decision

- **Threshold:** ≥ 70% extraction success → ship strict (no LLM fallback).
- **Observed:** 100%.
- **Decision: ship strict.** `extract_draft.py` keeps no LLM fallback. Failures are recorded as `terminal_reason="extraction_failed"` in journey.jsonl (failures-as-steering, per design P6).

## Findings beyond O1

### Triage `fix_pr_linked` is over-restrictive (false-rejection problem)

The `triage_required.fix_pr_linked` regex looks for `closed by .*?#N`, `fixed (in|by) .*?#N`, or `pull/N` in body+comments. **This misses GitHub's sidebar-style closing-PR references.**

Evidence: 14 of 15 historically-committed scenarios — all confirmed to have fix PRs in `coverage-log.jsonl` — were rejected at triage with `missing_fix_pr_linked`. Inspection of one (`mrdoob/three.js#31776`) shows:
- Issue body has no closing-PR text. Comments: 0.
- `gh issue view ... --json closedByPullRequestsReferences` returns `[{"number":31783,"url":"https://github.com/mrdoob/three.js/pull/31783"}]`.

The link exists; it's only in the GraphQL sidebar metadata, not in REST body/comments.

**Failure breakdown across the two run dirs:**

| Reason | Count | Fraction |
|---|---|---|
| `missing_fix_pr_linked` | 48 | 80% of all rejections |
| `missing_visual_keyword_present` | 8 | 13% |
| reached `produce_done` | 3 | 5% |
| `select_done` (no produce phase run) | 1 | 2% |

### Follow-up landed in commit `64d1def`

`triage.py.fetch_issue_thread` now probes `closedByPullRequestsReferences`
via `gh api graphql` and appends "Closes #<n> (<url>)" to the body
before triage runs. Re-running the 15-URL sample after the fix:

| Sample | Pre-fix pass-through | Post-fix pass-through |
|---|---|---|
| 15 historically-committed URLs | 0/15 (0%) | 4/15 (27%) |

The remaining 11 rejections (8 `missing_fix_pr_linked`, 3
`missing_visual_keyword_present`) are scenarios the older LLM-triage
path accepted via signals the strict-CLI rules don't yet cover (e.g.
"fixes #N" / "addresses #N" / non-standard merge-without-keyword). The
sidebar-data gap (the original concern) is closed.

Orthogonal to O1: O1 gates `extract_draft`, not triage. The remaining
triage-tuning is its own future iteration.

## Reproducibility

```bash
# Generalization corpus (the one that yielded the 3/3 measurement):
PYTHONPATH=src/python python3 -m gpa.eval.curation.run \
  --queries src/python/gpa/eval/curation/queries/generalization_queries.yaml \
  --rules src/python/gpa/eval/curation/mining_rules.yaml \
  --workdir /tmp/smoke-eval-pipeline-gen \
  --batch-quota 40 \
  --max-phase produce

# Framework-app-dev hard-cases (the one with sparser yield by design):
PYTHONPATH=src/python python3 -m gpa.eval.curation.run \
  --queries src/python/gpa/eval/curation/queries/framework_app_dev_hard_cases.yaml \
  --rules src/python/gpa/eval/curation/mining_rules.yaml \
  --workdir /tmp/smoke-eval-pipeline \
  --max-phase select
```

Outputs:
- `runs/<id>/journey.jsonl` — one row per discovered candidate
- `runs/<id>/summary.md` — auto-generated rollup (terminal_reason histogram, taxonomy_cell histogram, total tokens)
- `scope-log.jsonl` — appended cross-run; one row per `(run_id, query)`
  pair with yielded/selected/extracted/committed counts

## Post-smoke additions

After the smoke-test landed, two pieces of tooling were added that
complete the mining loop:

- **`scope-log.jsonl`** — `<workdir>/scope-log.jsonl` is now appended
  at the end of every run. Each row carries `{run_id, ts, source,
  query, repos[], yielded, selected, extracted, committed}`.
  Cross-run analysis: `cat scope-log.jsonl | jq ...`.

- **`gpa.eval.curation.gen_queries`** — a small LLM-using CLI that
  takes a free-form instruction + the scope-log and proposes new
  GitHub Search queries probing unexplored scope. Deterministic
  dedup is applied AFTER the LLM responds. Verified end-to-end on
  2026-05-01: instruction "WebGPU compute shader bugs..." yielded
  8 net-new queries across 6 net-new repos (gfx-rs/wgpu, gpuweb,
  webgpu/webgpu-samples, tensorflow/tfjs, toji/webgpu-test); 0 of
  the 8 collided with scope-log.

## Bottom line

The single-path mining pipeline is correct and ready to ship.
`extract_draft` is reliable (100% on the candidates that reach it).
The triage gates work but lean strict — partly mitigated by the
sidebar-PR fix in `64d1def`, with the remaining gap a triage-tuning
question for a future round.

## Rejection-rate analysis & fixes (2026-05-01, post-Godot mining)

After running mining against `godotengine/godot` we sampled the 80%
triage-rejection rate observed across 4 mining runs (100 candidates).
Four structural fixes landed:

| Fix | File | Before | After |
|---|---|---|---|
| Visual-keyword regex expanded | `mining_rules.yaml` | 4/6 sampled rejections were false (deck.gl, maplibre, pixijs, playcanvas — used "incorrect"/"regression"/"breaks"/"failing") | covers `incorrect`, `broken`, `fails`, `regression`, `crash`, `corrupted`, `garbled`, `distortion` |
| PR URL auto-passes `fix_pr_linked` | `rules.py` | A merged PR was rejected if its body had no closing-PR ref to itself (~25% of `fix_pr_linked` rejections in 8-URL sample) | `_run_triage_gates` now includes `cand.url`, so `.../pull/<n>` URLs satisfy the regex |
| Godot-style issue headers + structured-body fallback | `extract_draft.py` | Long bodies without explicit Expected/Actual sections raised `ExtractionFailure` (Godot uses `### Issue description`) | accepted `Issue description`, `Description`, `Steps to reproduce`, `What happened`, `Bug description`; long bodies with any `## ...` markdown header are now accepted as user_report |
| PR-as-candidate metadata extraction | `run.py:_fetch_fix_pr_metadata` | When cand was a PR, the function searched the body for another PR ref and 404'd on `pulls/<issue-num>` | when cand URL is `.../pull/<n>`, use the PR itself directly |

Re-running the same Godot query pack with all four fixes:

| Metric | Before | After |
|---|---|---|
| Triage rejection rate | 58% (14/24) | 30% (6/20) |
| `extraction_failed` | 12.5% (3/24) | 0% (0/20) |
| `produce_done` (reaches extract+validate) | 4% (1/24) | 20% (4/20) |
| Pipeline errors logged to stderr | 1 | 0 |

The remaining 6 triage-rejected are now mostly correct rejections:
true non-graphics PRs (e.g. `Fix acceleration structure barriers in
Vulkan pipelines` is a maintenance-internal change with no visible
user symptom). Closer to the design intent of the gates.

Tests added to lock in each fix:
- `test_visual_keyword_accepts_expanded_terms`
- `test_pr_url_auto_satisfies_fix_pr_linked` /
  `test_issue_url_does_not_auto_satisfy_fix_pr_linked`
- `test_extract_godot_style_issue_body`
- `test_fetch_fix_pr_metadata_uses_pr_self_for_pr_candidates`
