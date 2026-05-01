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

## Bottom line

The single-path mining pipeline is correct and ready to ship. `extract_draft` is reliable (100% on the candidates that reach it). The triage gates work but lean strict — a documented follow-up to the triage-side text source is the right next step, not a relaxation of the extractor.
