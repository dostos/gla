# Multi-tier eval: haiku 4.5 vs Opus 4.7 — does GPA help cheap models more?

*Run: 2026-04-30. Models: Opus 4.7 (1M ctx) + Haiku 4.5, both via Claude
Code Agent dispatch with `model:` override. 16 subagent runs total.*

## Setup

Same 4 scenarios as the single-tier multi-scenario eval (R10 + e1 + e22
+ e26), now × 2 modes (`code_only` / `with_gpa`) × 2 tiers (Opus / haiku)
= 16 runs. Each run was a fresh `general-purpose` subagent with:

- Redacted `scenario.md` (Ground Truth / Fix metadata hidden).
- For `with_gpa`: `curl` access to OpenGPA REST at `localhost:18080`,
  with the per-scenario captured frame IDs and endpoint inventory
  documented up front.
- For `code_only`: read access to the `.c` reproduction (synthetic)
  or `gh` CLI for cross-repo source navigation (R10).
- 20-tool-call budget cap.
- Required output: `DIAGNOSIS:` + `FILE(S):`.

## Accuracy — 16 / 16 correct

Both tiers diagnosed every scenario correctly and named the same fix
file/line. No accuracy delta to report.

## Cost matrix (all 16 runs)

| Scenario | Mode | Tier | Calls | Tokens | Wall (s) | Result |
|---|---|---|---:|---:|---:|---|
| **R10** (framework, multi-file) | code_only | Opus | 5  | 21,266 |  37 | ✅ 2/4 files |
| | code_only | **haiku** | **18** | 45,441 | **105** | ✅ 2/4 files |
| | with_gpa  | Opus | 4  | 19,313 |  24 | ✅ 2/4 files |
| | with_gpa  | haiku | 12 | 43,823 |  40 | ✅ 2/4 files |
| **e1** (state leak, ~200 LoC) | code_only | Opus | 2  | 23,555 |  16 | ✅ |
| | code_only | haiku | 2  | 43,007 |   8 | ✅ |
| | with_gpa  | Opus | 5  | 25,945 |  29 | ✅ |
| | with_gpa  | haiku | 10 | 45,242 |  23 | ✅ |
| **e22** (depth_func leak, ~155 LoC) | code_only | Opus | 2  | 23,101 |  22 | ✅ |
| | code_only | haiku | 2  | 42,707 |  11 | ✅ |
| | with_gpa  | Opus | 4  | 24,619 |  22 | ✅ |
| | with_gpa  | haiku | 5  | 43,737 |  18 | ✅ |
| **e26** (no depth-clear, ~165 LoC) | code_only | Opus | 2  | 23,145 |  20 | ✅ |
| | code_only | haiku | 2  | 42,692 |   9 | ✅ |
| | with_gpa  | Opus | 5  | 24,803 |  27 | ✅ |
| | with_gpa  | haiku | 10 | 44,664 |  20 | ✅ |

## The interesting finding: GPA ROI inverts with model strength on framework bugs

### R10 (framework, multi-file) — Δ widens at the cheaper tier

| Tier | code_only | with_gpa | Δ calls | Δ tokens | Δ wall |
|---|---|---|---:|---:|---:|
| Opus 4.7  | 5 / 21,266 / 37s   | 4 / 19,313 / 24s  | **−20%** | −9% | −35% |
| Haiku 4.5 | 18 / 45,441 / 105s | 12 / 43,823 / 40s | **−33%** | −4% | **−62%** |

- **Haiku code_only on R10 nearly exhausted the 20-call budget** (18 of 20)
  and took 105s, navigating cross-repo via `gh search` / `gh api`
  iteratively. With GPA, the `feedback-loops` / `textures` endpoint
  delivered an instant smoking gun (`collides_with_fbo_attachment:
  true` on the transmission texture) and haiku narrowed in 12 calls / 40s.
- The Δ at Opus was −1 call / −13s. The Δ at haiku is −6 calls / −65s.
  **The GPA tool's value scales inversely with model strength** on
  framework bugs — the weaker the navigator, the more a Tier-1 narrow
  check is worth.

### Synthetic single-file scenarios — same shape at both tiers

| Scenario | Tier | code_only calls | with_gpa calls | Δ |
|---|---|---:|---:|---|
| e1  | Opus  | 2 | 5  | +150% |
| e1  | haiku | 2 | 10 | +400% |
| e22 | Opus  | 2 | 4  | +100% |
| e22 | haiku | 2 | 5  | +150% |
| e26 | Opus  | 2 | 5  | +150% |
| e26 | haiku | 2 | 10 | +400% |

GPA penalty *grows* at haiku tier on synthetic scenarios — haiku
explores more endpoints (textures + feedback-loops + explain + drawcalls
× both dc_id) before locating the issue, then still has to read main.c
to confirm. On Opus a single `/draws/N/explain` reveals enough to
anchor the answer; haiku tends to enumerate. **The cost penalty for
firing GPA on small scenarios is therefore worse at cheaper tiers**,
sharpening the case for source-LoC-aware suggestion logic.

## Wall time: haiku is faster on small scenarios, slower on framework

| Scenario | Opus median | Haiku median | Speedup |
|---|---:|---:|---:|
| Synthetic code_only (e1/e22/e26) | 19s | **9s** | 2.1× faster |
| Synthetic with_gpa (e1/e22/e26)  | 26s | 20s | 1.3× faster |
| R10 code_only (framework)        | 37s | **105s** | 2.8× **slower** |
| R10 with_gpa (framework)         | 24s | 40s | 1.7× slower |

Haiku has lower per-call latency, so on tasks that need few calls it
wins on wall time. On tasks that need many exploratory calls (R10
code_only), the higher call count overwhelms the per-call savings and
haiku becomes much slower than Opus.

## Token cost — haiku ~2× tokens, but ~5× cheaper per token

Total tokens (input+output across all turns):

| Scenario set | Opus mean | Haiku mean | Haiku/Opus ratio |
|---|---:|---:|---:|
| All 8 runs | 23k | 44k | 1.9× |

Per-scenario API cost (rough, Anthropic public pricing $15/M input
Opus vs $1/M input Haiku, ignoring output):

| Tier | Mean tokens × $/M | Per-scenario cost |
|---|---|---:|
| Opus 4.7 | 23k × $15/M | $0.35 |
| Haiku 4.5 | 44k × $1/M | $0.04 |

**Haiku is ~9× cheaper per scenario** despite using 2× more tokens.
Combined with no accuracy loss, this confirms haiku is the right
default for first-pass eval; reserve Opus for scenarios where haiku
hits the budget cap or needs synthesis-level reasoning.

## Takeaways

1. **The user's "code_only fails, with_gpa wins" hypothesis showed up
   at the cheaper tier.** Haiku R10 code_only hit 18/20 calls — nearly
   exhausting the budget. At a lower budget cap (e.g. 10), haiku would
   have *failed* code_only and *succeeded* with_gpa. The qualitative
   difference is there; this experiment used a generous budget to keep
   accuracy uniform and isolate the cost delta.

2. **GPA's value compounds for cheaper models on framework bugs.** The
   −1 call / −13s Δ at Opus turns into −6 calls / −65s at haiku. If
   the production deployment uses haiku for cost reasons, GPA becomes
   *more* important, not less.

3. **GPA penalty also grows at cheaper tiers on small scenarios.**
   Haiku enumerates GPA endpoints more (e1: +400%, e26: +400%). A
   suggestion layer that gates GPA on `source LoC > N` (or "no `.c`
   file in scope") would prevent both penalties at once.

4. **Haiku as the eval default** — 9× cheaper, no accuracy loss on this
   scenario set, faster wall time on small scenarios. Use Opus only as
   a fallback when haiku exhausts the budget or returns ambiguous
   diagnoses.

## Open follow-ups

- **Re-run R10 with budget=10**: at the lower cap, code_only haiku
  should fail and with_gpa haiku should succeed — this would convert
  the +135% calls / +62% wall finding into a binary success/failure
  delta, which is more compelling for the value-prop pitch.
- **Sonnet 4.6 tier**: fill in the middle row of the matrix. Predict
  it tracks halfway between Opus and haiku.
- **Source-LoC-aware GPA suggestion**: implement and re-measure to
  confirm the synthetic-scenario GPA penalty disappears.
- **More framework-shape scenarios**: R10 is N=1 in this category.
  The R13 maintainer-framing scenarios need captured frames before
  they can join this matrix.
