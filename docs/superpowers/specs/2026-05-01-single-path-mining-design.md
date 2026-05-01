# Single-Path Mining — Design Notes

_Status: living. Confirmed principles below; open points decided iteratively
during implementation, with smoke-test or empirical evidence where flagged._

## Goal

Replace the four overlapping mining CLIs (`mine_hard_cases`,
`mine_taxonomy`, `pipeline`, `measure_yield`) with one unified entry
point that runs the whole curation DAG end-to-end with no human gate,
records every candidate's journey to a queryable JSONL, and uses LLMs
only for the parts that genuinely require judgement.

## Confirmed principles

### P1 — One CLI, one DAG, three public phases

```
SELECT   — discover · dedup · fetch_thread · classify_score · stratified_select
PRODUCE  — extract_draft · validate
JUDGE    — evaluate · classify_helps · commit
```

CLI: `python -m gpa.eval.curation.run`. Phase boundary is the
user-facing surface (`--max-phase`); finer sub-steps remain in
`IssueWorkdir` for replay.

### P2 — No human gate; cost-control is programmatic

`stratified_select` caps candidates by `top_k` and `per_cell_cap` from
the rules file. Nothing waits for human review. To run cheaply, set
`--max-phase select` (no LLM cost). Budget enforcement is implicit:
`stratified_select` caps candidate count, and the only LLM step is
`evaluate`, which is opt-in via `--evaluate`.

### P3 — LLMs only for judging and query generation; CLI/rules for everything else

Mining (querying, filtering, extracting) is deterministic. Two
LLM-using paths exist, both narrowly scoped and opt-in:

- `evaluate` (the agent eval) — opt-in via `--evaluate` flag on
  `gpa.eval.curation.run`. Default off.
- `gen_queries` (the query proposer) — its own CLI
  `gpa.eval.curation.gen_queries`. Takes a free-form instruction +
  the cross-run scope log, asks an LLM to propose new GitHub Search
  queries probing unexplored scope, and deterministically dedupes
  the result against `scope-log.jsonl` before writing the YAML.

Today's `triage` is folded into stricter rules in `classify_score`;
today's `draft` is replaced with `extract_draft` (deterministic field
extraction from issue body + fix PR diff, template fill).

`classify_helps` is a deterministic function of `with_gla_score
- code_only_score`, not an LLM call.

### P4 — Per-run output dir; queryable journey JSONL is the source of truth

```
.eval-pipeline/
  scope-log.jsonl                         # cross-run, append-only
  runs/<run_id>/
    config.yaml                           # frozen copy of queries + rules used
    journey.jsonl                         # one row per discovered candidate
    issues/<id>/                          # per-sub-step IO cache (replay)
    summary.md                            # human rollup
```

Journey row schema (skipped phases are `null`):

```json
{
  "url": "...",
  "run_id": "...",
  "discovered_at": "...",
  "discovery_query": "...",
  "select":  {"deduped": true, "fetched": true, "taxonomy_cell": "...",
              "score": 7, "score_reasons": [...], "selected": true},
  "produce": {"extracted": true, "validated": true},
  "judge":   {"with_gla_score": 1.0, "code_only_score": 0.0,
              "helps_verdict": "yes", "committed_as": "r20_..."},
  "tokens":  {"triage": 0, "draft": 0, "evaluate": 12500, "total": 12500},
  "cache_hit": false,
  "terminal_phase": "judge",
  "terminal_reason": "committed"
}
```

Cross-run queries: `cat runs/*/journey.jsonl | jq ...`.

### P5 — Hard cut, not soft

Delete the four old CLIs in the same change. Update docs and tests in
the same PR. Anything depending on the old commands gets fixed up
explicitly.

### P6 — Failures-as-steering

`extract_draft` failures (and any dropped candidate at any phase) are
recorded in `journey.jsonl` with a specific `terminal_reason`. The
expected loop: run the pipeline → query failures → add rules to
`mining_rules.yaml` → re-run. The journey is the only feedback channel
we maintain — if information about a failure isn't in `journey.jsonl`,
it's not steering data.

### P7 — Cross-run scope tracking; new queries dedupe against history

Each run aggregates its journey rows by `discovery_query` and appends
one row per unique query to `<workdir>/scope-log.jsonl` — a persistent
cross-run record of which queries have been mined, with which yield.

`gen_queries` is the only mining-side LLM caller besides `evaluate`.
It reads scope-log, sends the existing queries + repo histogram to the
LLM as context with the user's free-form instruction, and the LLM is
asked to propose queries probing scope NOT already covered. After the
LLM responds, `gen_queries` deterministically filters the proposals
against the scope log so duplicates never reach the YAML output.

The expected loop:
```
gen_queries --instruction "X" --scope-log .eval-pipeline/scope-log.jsonl
            --out new_queries.yaml
                       ↓
gpa.eval.curation.run --queries new_queries.yaml ...
                       ↓
new rows append to scope-log.jsonl
                       ↓
next gen_queries call sees them and biases away from re-mined repos
```

## Open points (decide iteratively)

### O1 — Strict-CLI vs hybrid-LLM extraction

`extract_draft` v1 is **strict CLI**: rules-based field extraction
only, no LLM fallback.

**Smoke test gate:** run v1 against the 22 URLs in
`queries/framework_app_dev_hard_cases.yaml` plus a sampled chunk of
the existing coverage log. Measure extraction success rate.

- ≥ 70% success → keep strict, log failures as steering input for
  rule improvement.
- < 70% success → reopen the question; consider a bounded LLM fallback
  with a stratified-select cap.

Decision lives in this doc, not committed to the code, until smoke
test runs.

### O2 — `triage` rules: how strict?

Today's LLM triage gates a lot of bad candidates. Replacing it with
hard rules in `classify_score` risks either too lenient (LLM cost in
`evaluate` wasted on garbage) or too strict (miss real bugs).

**Initial rule set proposal** (revise after smoke test):
- Required: `fix_pr_linked && closed_resolved && visual_keyword_present`
- Reject: `feature_request || documentation_only || installation_issue`
- Score weights from existing `mining_rules.yaml` carry over.

Tune on smoke test results.

### O3 — `run_id` format

Default proposal: `YYYY-MM-DD-HHMMSS-<short-hash-of-config>`. Open to
shorter forms (e.g. `r20-mine-001`) if the team prefers human-readable
labels. Decide when first run dir is created.

### O4 — Whether `summary.md` is auto-generated or hand-written

Auto-generated rollup of `journey.jsonl` (counts per terminal phase,
reject-reason histogram, cell distribution, token spend). Could be
hand-written if the auto version turns out to be too noisy. Default
auto.

### O5 — Cache hit policy across runs

`IssueWorkdir` keys stages by `input_hash`. Two cross-run options:

- **Per-run isolated cache** (default): each run dir has its own
  `issues/`. Re-running discovers from scratch; only sub-step within a
  run is cached.
- **Shared cache pool**: a top-level `.eval-pipeline/cache/` keyed by
  URL+content-hash, with run dirs symlinking. Maximizes reuse across
  runs (saves fetch + classify + extract on unchanged threads).

Defer the choice — start with isolated; add shared pool if re-fetches
become a real cost.

### O6 — How `evaluate` interacts with existing eval harness

`evaluate` shells out to today's agent-eval invocation. Open: do we
embed the eval invocation into the curation pipeline, or do we leave
it as a separate CLI and have `run.py` shell out via `subprocess.run`?
Latter is less coupling but adds a process boundary; former is
tighter. Decide based on how messy the eval module's import surface
is.

### O7 — What the deletion of `pipeline.py` actually means

The 794-line `pipeline.py` already orchestrates `triage → draft →
validate → run_eval → commit`. The new `run.py` will reuse most of
that logic — the deletion is more a rewrite-in-place. Open: do we
preserve `pipeline.py` as the file name and rewrite contents, or
introduce `run.py` and delete `pipeline.py`? Latter is clearer in git
history; former is more conservative. Decide when implementing.

## Non-goals

- Not building a query subcommand. JSONL + `jq` is the surface.
  Reconsider only if `jq` queries become repetitive across rounds.
- Not building a REST/MCP query interface. The journey JSONL is for
  humans + post-hoc analysis, not live agent steering.
- Not changing the rules-file format (`mining_rules.yaml`) or the
  query-pack format. Those are stable inputs.
- Not changing the eval scoring contract (`with_gla_score`,
  `code_only_score`, `helps_verdict`).

## What this doc isn't yet

A spec. It's principles + open points. The implementation plan
(written via `superpowers:writing-plans`) will turn each `O*` open
point into a concrete sub-task with acceptance criteria. Some `O*`
points only get answered after the smoke test runs — that's expected.
