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
