# Eval Rounds

One file per round, mirroring `/data3/gla-eval-results/` (gitignored
data dirs). Each file has the same fixed shape so cross-round diffs
are easy to read:

```
# Round <name> (<date>)

## Ran
- Cohort: <N scenarios>
- Modes: with_gla, code_only
- Model: <agent model>
- Output: /data3/gla-eval-results/<round-dir>/

## Findings
- Bullet 1 (what we learned that we didn't know before)
- ...

## Added / modified

Split into **System** (OpenGPA itself: shims, engine, API, MCP,
backends, framework integration) and **Eval pipeline** (harness,
scorer, prompts, mining, scenarios). Attribution matters — a lift
from a new GL function intercept means something different than a
lift from a scoring fix.

### System (OpenGPA itself)
- Commit <sha>: <one-line>  — paths under `src/{shims,core,bindings}/` or `src/python/gpa/{api,backends,mcp,framework}/`
- ...

### Eval pipeline
- Commit <sha>: <one-line>  — paths under `src/python/gpa/eval/`, `tests/eval/`, prompts
- Backlog item P<n> — <one-line>
- Scenarios: +<N> mined this round
- ...

To enumerate commits between two round-tags:

```bash
scripts/round-changes.sh round-<prev> round-<this>
# or against HEAD if the round is in-flight
scripts/round-changes.sh round-<prev>
```

The helper prints System / Eval pipeline / Other sections ready to
paste into this round file.

## Removed / closed
- Backlog item P<n>: <how it was resolved>
- Scenarios quarantined: <N> (reason)
- ...

## Numbers

| Run | Solved | Tokens | vs prior |
|---|---|---|---|
| ... | ... | ... | ... |

## Open backlog

(carry forward unfinished items from prior round; add new ones here)
- P0 — ...
- P1 — ...
```

## Convention

- File name: `YYYY-MM-DD-<round>.md`
- Tag the round at launch: `git tag round-<name> <sha>`. That gives a
  reproducible boundary so `scripts/round-changes.sh` can enumerate
  commits between rounds.
- Append-only: don't rewrite history. If a finding turns out wrong in
  a later round, note it in *that* round's "Findings" with a
  back-reference, don't edit the original.
- Numbers must include a comparison row to the previous round so
  regressions are visible.
- Open backlog at the bottom is the running todo list. When an item
  ships, move it to "Removed / closed" *in the round that shipped it*.
- Always split Added/Modified into **System** vs **Eval pipeline** so
  lift attribution is clear.

## Index

| Round | Date | Headline |
|---|---|---|
| [R12c](2026-05-05-r12c.md) | 2026-05-05 | 1/14 → 10/14 from infra fixes (snapshot + scoring + judge) |
| [R12d](2026-05-05-r12d.md) | 2026-05-05 | Heavy "READ FIRST" prompt collapsed investigation 5×; reverted |

Older rounds (R1–R12b) predate this convention; their narrative lives
in `docs/eval-results.md` as legacy reference.
