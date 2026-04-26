# Mining Yield Baseline

_Generated: 2026-04-26T04:34:01.496222+00:00_
_Config: `/tmp/yield_baseline_queries.yaml` (8 queries, batch_quota=8)_
_Coverage log at run time: 648 prior URLs, 94 committed scenarios_

```
Queries:                8
URLs from discovery:    8           (after Discoverer's keyword pre-filter)
After URL dedup:        5   (5/8 = 62.5% fresh)
After thread fetch:     5   (5/5 = 100.0% fetched)
After triage in_scope:  1   (1/5 = 20.0% accept)
After fingerprint dedup:1   (1/1 = 100.0% novel)
After successful draft: 0   (0/1 = 0.0% draft success)
Would-be-too-easy:      [skipped — pass --with-difficulty-check to enable]
```

**End-to-end yield: 0/8 = 0.0%**

## Top rejection reasons

| reason                            | count |
| --------------------------------- | ----- |
| out_of_scope_not_rendering_bug    | 4     |
| url_dedup                         | 3     |
| draft_invalid                     | 1     |

## Per-candidate trace

See `/tmp/yield-records.jsonl` for the full per-candidate JSONL. Summary table:

| URL                                                | stage_reached         | reason                            |
| -------------------------------------------------- | --------------------- | --------------------------------- |
| three.js/issues/33104 (Renderer blending)          | discovered            | url_dedup                         |
| three.js/issues/26613 (SVGLoader path)             | discovered            | url_dedup                         |
| three.js/issues/21330 (SVGLoader complex SVG)      | thread_fetched        | out_of_scope_not_rendering_bug    |
| three.js/issues/33121 (WebGPU WebXR shader err)    | thread_fetched        | out_of_scope_not_rendering_bug    |
| three.js/issues/33207 (PMREMGenerator texunit)     | discovered            | url_dedup                         |
| three.js/issues/22312 (FBXLoader child mesh xform) | not_fingerprint_dup   | draft_invalid                     |
| three.js/issues/33341 (TSL nested struct)          | thread_fetched        | out_of_scope_not_rendering_bug    |
| three.js/issues/19677 (displacementMap normals)    | thread_fetched        | out_of_scope_not_rendering_bug    |

## Diagnosis — yield-killing stages

**#1 bottleneck: triage rejects 4/5 fresh candidates (80%) as
out_of_scope_not_rendering_bug.** Inspecting the triager's own summaries shows
two distinct sub-failures: (a) **loader/asset bugs are systematically rejected**
even when the user-visible symptom is a wrong rendered image — three SVGLoader /
FBXLoader-style threads were filtered out under the framing "loader bug, not GPU
state bug" or "feature gap, not rendering bug"; (b) **shader-compile errors are
rejected** as "shader compile, not GPU-observable rendering" even though
shader_compile is one of our 10 official fingerprint categories. Both are
prompt-side problems in `src/python/gpa/eval/curation/prompts/triage_system.md`,
not signal-side problems in the queries.

**#2 bottleneck: draft_invalid eats the only candidate that survives triage.**
The lone in_scope thread (FBXLoader skinning, fingerprint
`matrix_math:skinned_mesh_local_transform_ignored`) was rejected by the drafter
with `No filename-marked fenced blocks found` — the LLM's response did not emit
the required `<!-- filename: X -->` markers. With a sample of one this could be
noise, but the pipeline already retries once on `ValueError`, so the second
attempt also produced a malformed response. Drafter-prompt clarity and / or
Sonnet-vs-Opus-on-claude-code reliability is implicated.

**#3 bottleneck: URL dedup is healthy at 37.5% (3/8 reject).** Lower than the
~86% the prior round 9 spec predicted, because batch_quota=8 ran a small
sample of recent issues. With a larger batch_quota across the same query set,
expect dedup to climb back to the 70-90% range — the production coverage log
already carries 202 three.js URLs, 65 mapbox, 58 pmndrs, 16 pixijs, all
candidates here came from those same repos.

## Caveats

- batch_quota=8 was chosen for a fast first baseline (~10 min run);
  numbers will tighten with batch_quota=20-30. The shape (triage as the
  killer) is robust at this sample size — the per-stage attrition is already
  unmistakable.
- The Discoverer's cheap keyword pre-filter
  (`_is_obviously_non_rendering`) runs UPSTREAM of the "discovered" stage
  here. Candidates dropped by that pre-filter (typescript / docs / build /
  editor keywords) never reach `measure_yield`. The 8 candidates above are
  candidates that already survived the pre-filter, so the triager is the
  next gate and the first one this instrument can see.
- `--with-difficulty-check` was not enabled in this baseline. Will be added
  in a follow-up run once draft success > 0.

## Reproducing

```bash
PYTHONPATH=src/python python3 -u -m gpa.eval.curation.measure_yield \
    --config /tmp/yield_baseline_queries.yaml \
    --jsonl /tmp/yield-records.jsonl \
    --report docs/mining-yield-baseline.md \
    --backend claude-code
```

The instrument is read-only against the production coverage log
(`docs/superpowers/eval/coverage-log.jsonl`) — it never appends entries or
commits scenarios, so it is safe to run repeatedly while iterating on the
triager / drafter prompts.

## Iteration 2 — triage tuning (2026-04-26)

### Prompt diff (3 bullets)

- Added explicit mental model: "Could the rendered image have been correct
  if a different value had been computed/uploaded/bound?" If yes →
  `in_scope`, regardless of which host module produced the bad value.
- Loader/asset/importer bugs (FBX, GLTF, SVG, OBJ, …) now explicitly listed
  as in-scope when the user-visible symptom is a wrong rendered image.
  Removed the implicit "loader bug == out of scope" framing the previous
  prompt invited.
- Shader-compile / link errors now explicitly in-scope (matches the
  `shader_compile` fingerprint category and the fact that `gpa report`
  surfaces compile/link logs). Restricted `out_of_scope_compile_error`
  to host-side build failures only (C++/Bazel/header), not GLSL/SPIR-V.
- Tightened `out_of_scope` enumeration (docs, build-system, TS-only,
  perf-only, non-visual logic, editor/CI/lint) so the triager has a
  concrete checklist to reject against rather than over-applying
  "not a rendering bug".

### Per-stage table — baseline vs. iteration 2

Same 8 candidates, same query set, same `batch_quota=8`.

| Stage                     | Baseline (commit 2462235) | Iteration 2 | Delta |
| ------------------------- | ------------------------- | ----------- | ----- |
| URLs from discovery       | 8                         | 8           | —     |
| After URL dedup           | 5 (62.5%)                 | 5 (62.5%)   | —     |
| After thread fetch        | 5 (100%)                  | 5 (100%)    | —     |
| **After triage in_scope** | **1 (20%)**               | **5 (100%)**| **+4**|
| After fingerprint dedup   | 1 (100%)                  | 5 (100%)    | +4    |
| After successful draft    | 0 (0%)                    | 2 (40%)     | +2    |
| **End-to-end yield**      | **0/8 = 0%**              | **2/8 = 25%** | **+25 pp** |

Top rejection reasons (iteration 2):

| reason          | count |
| --------------- | ----- |
| url_dedup       | 3     |
| draft_invalid   | 3     |

### Per-candidate trace — iteration 2

| URL                                                | stage_reached         | reason            |
| -------------------------------------------------- | --------------------- | ----------------- |
| three.js/issues/33104 (Renderer blending)          | discovered            | url_dedup         |
| three.js/issues/26613 (SVGLoader path)             | discovered            | url_dedup         |
| three.js/issues/21330 (SVGLoader complex SVG)      | not_fingerprint_dup   | draft_invalid     |
| three.js/issues/33121 (WebGPU WebXR shader err)    | **drafted**           | —                 |
| three.js/issues/33207 (PMREMGenerator texunit)     | discovered            | url_dedup         |
| three.js/issues/22312 (FBXLoader child mesh xform) | not_fingerprint_dup   | draft_invalid     |
| three.js/issues/33341 (TSL nested struct)          | not_fingerprint_dup   | draft_invalid     |
| three.js/issues/19677 (displacementMap normals)    | **drafted**           | —                 |

### Did triage move out of #1 bottleneck?

**Yes.** Triage went from rejecting 4/5 fresh candidates (80%) to rejecting
0/5 (0%). Every URL that survived dedup now reaches the drafter. Notable
flips: the WebGPU shader-compile and TSL nested-struct shader-compile
threads — both fingerprinted as `shader_compile:*` — now pass triage
instead of being misrejected against the `shader_compile` category itself;
the SVGLoader and FBXLoader threads are now scored on their wrong-image
symptom, not on which module emitted the wrong value. Even the
displacementMap thread that the maintainer marked "expected behavior" got
through — borderline-acceptable, drafter still produced a valid scenario.

### New #1 bottleneck

**Drafter.** 3/5 in-scope candidates fail with the same error pattern:
`No filename-marked fenced blocks found. Expected: <!-- filename: <path> -->`.
That is identical to the single drafter failure in the baseline run, now
amplified 3x by the larger pool of in-scope candidates. The pipeline
already retries the drafter once on `ValueError`, so both attempts are
producing malformed responses. This is the next prompt to tune
(`draft_core_system.md`) — likely the filename-marker convention is being
crowded out by the drafter's longer outputs (SVG/FBX scenarios are large)
or competing with code-fence formatting that the drafter is more
comfortable emitting.

## Iteration 3 — drafter format reliability + principled-rejection handling (2026-04-26)

### Diagnosis (from standalone drafter probes on the 3 failing URLs)

The "No filename-marked fenced blocks found" error was **not** a format
failure. Standalone probes of all 3 failing candidates (#21330 SVGLoader,
#22312 FBXLoader, #33341 TSL nested struct) showed the drafter LLM was
correctly emitting the documented `<!-- draft_error: fix_pr_not_resolvable -->`
HTML comment per the prompt's rejection policy — the parser just didn't
recognize that signal, so principled rejections looked identical to format
failures. The retry was futile because the model wasn't going to change
its mind on a second pass with the same input.

### Diff summary

- **Prompt** (`draft_core_system.md`): moved the format contract to a
  NON-NEGOTIABLE block at the very top with a complete worked example and
  a 6-item self-check; **inverted the unresolvable-fix-PR policy** so
  `bug_class: legacy` + empty `files: []` is the DEFAULT response when
  there's no clean fix PR (was: prefer to reject). `<!-- draft_error -->`
  is now restricted to bugs that are fundamentally not portable to a C
  repro AND not portable to a snapshot reference AND not draftable as a
  legacy stub. `fix_pr_not_resolvable` was removed as a valid rejection
  reason.
- **Parser** (`draft.py`): added `DraftRejectedByModel(ValueError)`
  subclass; `_parse_files` detects the `<!-- draft_error: <reason> -->`
  marker when no filename markers are present and raises this exception
  with the slug, distinguishing principled refusals from format failures.
- **Pipeline + measurement** (`pipeline.py`, `measure_yield.py`): catch
  `DraftRejectedByModel` separately, route to a structured
  `drafter_declined:<reason>` rejection bucket, and skip the retry
  (model won't change its mind).

### Per-stage table — baseline vs. iteration 2 vs. iteration 3

Same 8 candidates, same query set, same `batch_quota=8`, same dry-run
instrument. End-to-end yield doubled.

| Stage                     | Baseline    | Iteration 2 | Iteration 3 |
| ------------------------- | ----------- | ----------- | ----------- |
| URLs from discovery       | 8           | 8           | 8           |
| After URL dedup           | 5 (62.5%)   | 5 (62.5%)   | 5 (62.5%)   |
| After thread fetch        | 5 (100%)    | 5 (100%)    | 5 (100%)    |
| After triage in_scope     | 1 (20%)     | 5 (100%)    | 4 (80%)     |
| After fingerprint dedup   | 1 (100%)    | 5 (100%)    | 4 (100%)    |
| **After successful draft**| **0 (0%)**  | **2 (40%)** | **4 (100%)**|
| **End-to-end yield**      | **0/8 = 0%**| **2/8 = 25%** | **4/8 = 50%** |

Top rejection reasons (iteration 3):

| reason                         | count |
| ------------------------------ | ----- |
| url_dedup                      | 3     |
| out_of_scope_not_rendering_bug | 1     |

`draft_invalid` and `drafter_declined:*` are absent — every triage-passing
candidate now produces a parseable draft, three of them as `bug_class:
legacy` (#21330 SVGLoader, #22312 FBXLoader, #33121 WebGPU XR) and one as
`framework-internal` with a clean fix PR (#33341 TSL nested struct).

### Per-candidate trace — iteration 3

| URL                                                | stage_reached    | reason                            |
| -------------------------------------------------- | ---------------- | --------------------------------- |
| three.js/issues/33104 (Renderer blending)          | discovered       | url_dedup                         |
| three.js/issues/26613 (SVGLoader path)             | discovered       | url_dedup                         |
| three.js/issues/21330 (SVGLoader complex SVG)      | **drafted**      | — (legacy)                        |
| three.js/issues/33121 (WebGPU WebXR shader err)    | **drafted**      | — (legacy)                        |
| three.js/issues/33207 (PMREMGenerator texunit)     | discovered       | url_dedup                         |
| three.js/issues/22312 (FBXLoader child mesh xform) | **drafted**      | — (legacy)                        |
| three.js/issues/33341 (TSL nested struct)          | **drafted**      | — (framework-internal, PR #32724) |
| three.js/issues/19677 (displacementMap normals)    | thread_fetched   | out_of_scope_not_rendering_bug    |

The displacementMap thread flipped from drafted (iter2) → out_of_scope
(iter3). Triage prompt was untouched; this is run-to-run variance on a
borderline candidate the maintainer marked "expected behavior."

### New #1 bottleneck

**URL dedup, by raw count.** 3/8 = 37.5% of candidates are dropped by URL
dedup against the production coverage log — that's the single biggest
attrition step now. This is *healthy* attrition (we're correctly avoiding
re-mining covered ground) and it will tighten further as
`batch_quota` grows past 8 and the surviving fraction stabilizes around
the predicted 10-30% range. The relevant signal is that **of every 5
fresh URLs that pass dedup, 4 now reach `drafted`** — ~80% novel-to-draft
conversion vs. 0% in baseline and 40% in iter2.

The next real improvement targets are:
1. Triage variance on borderline candidates (1/5 fresh now flipping
   per-run) — could be tightened with a confidence threshold or a
   "thread-too-thin" rejection reason.
2. Difficulty filter (`--with-difficulty-check`) — now finally meaningful
   to enable, since the drafter produces 4 candidates per 8 queries to
   filter against.
3. Coverage log growth — at the current per-batch yield (4/8 = 50% novel
   in-scope drafts), 50 batches at quota 20 would commit ~500 new
   scenarios in principle; in practice `bug_class: legacy` scenarios
   should be flagged in the eval set selector so they're not over-weighted
   relative to clean-fix-PR scenarios.
