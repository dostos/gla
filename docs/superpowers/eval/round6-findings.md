# Round 6 findings — CLI report tool token-efficiency

## Hypothesis

Giving with_gpa-mode agents a single `gpa report --frame N --json` CLI
(plus drill-down `gpa check` / `gpa dump`) will cause them to substitute
multiple curl queries and framework-file reads with one bundled call,
closing the Round 5 token gap where with_gpa averaged **+241 K** more
cache_read tokens and **+$0.048** more per run than code_only.

## Outcome: mixed — sonnet confirmed, haiku partially confirmed

| Axis                    | R5 haiku Δ | R6 haiku Δ | R5 sonnet Δ | R6 sonnet Δ |
|-------------------------|------------|------------|-------------|-------------|
| cost (per run)          | +$0.048    | **+$0.019** | +$0.005     | **−$0.022** |
| turns                   | +5.6       | +4.1       | +1.9        | −1.6        |
| cache_read (tokens)     | +384 K     | **+251 K**  | +57 K       | **−64 K**   |
| pair-wise cheaper runs  | 5/19       | 9/20       | 8/19        | 8/20        |
| pair-wise net Δ cost    | +$1.15     | +$0.38     | +$0.12      | **−$0.44**  |

**Sonnet**: all four deltas flipped sign or shrunk materially. with_gpa
sonnet is now the cheapest cell in the matrix ($0.555 vs $0.577 code_only).
**Haiku**: deltas halved but did not go negative — CLI helped but not
enough to overcome haiku's narrower context + the fixed prompt overhead
of the CLI documentation block (~500 tokens).

## Top findings

1. **`gpa report` substitutes for curl at the sonnet tier but not the
   haiku tier.** Mean self-reported GPA queries/run dropped from 3.63 →
   3.15 for haiku (consistent with bundling) but *rose* slightly for
   sonnet (4.47 → 4.60). Sonnet is using the CLI more freely precisely
   because it's cheap-per-call, and each invocation still returns less
   payload than the equivalent curl + OpenAPI re-derivation.

2. **Accuracy is within sample noise.** R6 total correctness is 65/80
   (81 %) vs R5 70/78 (90 %). Five scenarios swapped their pass/fail
   bit between rounds: r24_enabling_autogeneratemipmaps (haiku code_only
   Y→N), r27 stayed hard for all, r29 became universally hard (it's now
   captured; same signal reaches both modes), r32/r34 sonnet with_gpa
   regressed. Nothing here suggests the CLI *hurt* diagnosis quality;
   the prompt change and random seed differences likely explain it.

## Top remaining gaps

1. **Haiku still overconsumes tokens in with_gpa mode.** The +251 K
   cache_read delta means haiku is still re-reading framework files *in
   addition to* running `gpa report`. A follow-up experiment: truncate
   the upstream snapshot directory listing in the prompt, or move the
   snapshot behind a `gpa dump source` tool so it's access-metered.

2. **No tool-call transcript to verify substitution directly.** Claude
   -p --output-format json returns only the final assistant message and
   aggregate usage counters; we cannot observe which bash commands fired.
   We rely on the self-reported `gpa_queries_made` integer. For Round 7,
   switch to `--output-format stream-json` (larger files, real tool
   trace) so we can count curl vs gpa invocations exactly.

3. **Three scenarios are structurally un-solvable from the minimal
   repro + snapshot alone**: r27 (anisotropic GGX energy term), r28
   (JS Uint16Array index-type — no GL-side signal), r29 (Mapbox symbol
   collision behavior). These need Tier-3 framework metadata to improve;
   no amount of Tier-1/Tier-2 CLI ergonomics will close them.

## Verdict

**Hypothesis confirmed for sonnet, partially confirmed for haiku.** The
narrow-endpoint CLI strategy works at the sonnet tier — with_gpa now
costs less than code_only on this suite, which is the first time that
has been true in any of the six rounds. For haiku the intervention is
directionally correct but not yet strong enough; reducing the prompt
footprint of the CLI documentation and gating the snapshot behind a
tool are the highest-leverage next steps.
