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

## System-improvement audit (Musk 5-step)

Walked in this order — each round must produce at least one System
change. If audit yields none, the eval pipeline is saturating and
the flywheel is spinning without making the product better.

**1. Requirements less dumb.**
- <Requirement X> — owner: <person>; still load-bearing? <yes/no>; if no: deleted in <commit>
- ...

**2. Deletions.**
- <Thing> — removed because <specific failure mode that would have
  required it, or "no caller found / not invoked since <commit>">
- ...

**3. Simplifications.** (only after 1-2)
- <Component> — was <complexity>, now <simpler>; rationale: <data point>

**4. Cycle-time improvements.** (only after 1-3)
- <Process> — was <slow path>, now <fast path>

**5. Automation.** (only after 1-4)
- <Manual step> — replaced by <automated path>

If a section is empty, write "(none this round)" and explain why
in the next round's "Findings" — persistent emptiness flags a
process gap.

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
| [R13](2026-05-05-r13.md)   | 2026-05-05 | Scope-hint validated: file_solved 0→6, tokens −25% to −48%, +2 code_only |
| [R14](2026-05-05-r14.md)   | 2026-05-05 | Browser-tier gate closes web-map gap (+0); budget hint over-throttled (-6 solves); revert in R15 |
| [R15](2026-05-05-r15.md)   | 2026-05-05 | First system change in 4 rounds (`gpa upstream outline`); audit identifies 3 R16 deletions |
| [R16](2026-05-05-r16.md)   | 2026-05-05 | First deletion-shipping round: with_gla skip works perfectly; rate-limit invalidates code_only validation |

Older rounds (R1–R12b) predate this convention; their narrative lives
in `docs/eval-results.md` as legacy reference.
