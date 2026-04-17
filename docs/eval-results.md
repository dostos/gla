# GLA Eval Results

## Methodology

- 10 adversarial scenarios (E1-E10), each a minimal OpenGL app with an intentional bug
- Two modes: **Code-Only** (source code reading only) and **With GLA** (source + live REST API queries)
- Agent: Claude Sonnet, non-directive prompts ("use whatever approach you think is best")
- Tracked: accuracy, tool sequence, pixel queries vs state queries

## Accuracy

| Scenario | Bug Type | Code-Only | With GLA |
|----------|----------|-----------|----------|
| E1: State Leak | Missing glUniform4f | Correct | Correct |
| E2: NaN Propagation | Singular matrix -> Inf | Correct | Correct |
| E3: Index Buffer OBO | sizeof(ptr) vs sizeof(data) | Correct | Correct |
| E4: Double Negation Cull | GL_CW + negative scale | Correct | Correct |
| E5: Uniform Collision | Swapped program indices | Correct | Correct + found bug is silent at runtime |
| E6: Depth Precision | near/far ratio 1e8 | Correct | Correct + depth=0.998 confirms |
| E7: Shader Include | saturate() missing clamp | Correct | Correct + pixel (255,255,255) confirms |
| E8: Race Texture | 1x1 placeholder | Correct | Correct + tex API shows 1x1 |
| E9: Scissor Not Reset | Missing glDisable | Correct | Correct + scissor rect on DC1 visible |
| E10: Compensating VP | Negated fwd + negated proj | Correct | Correct + pixel position proves mirror |

**Both modes: 10/10 accuracy.** GLA provided additional runtime evidence on 6/10 scenarios.

## Tool Usage Pattern (With GLA mode)

Every scenario followed the same pattern:
```
read_source -> query_drawcalls -> inspect_drawcall -> query_pixel
```

- Pixel queries: 10/10 scenarios (100%)
- State queries (inspect_drawcall): 10/10 scenarios (100%)
- Texture queries: 1/10 (E8 only)
- Scene queries: 0/10

**Framebuffer trap observation**: The agent queried pixels in every scenario, even when
structured state (pipeline flags, shader params) was sufficient for diagnosis. However,
it also used inspect_drawcall in every case, suggesting pixels were used for CONFIRMATION
rather than as the primary diagnostic tool.

## Where GLA Added Unique Value

### E5: Silent Bug Detection
Code-only analysis reported the uniform cache as buggy (swapped indices). GLA pixel data
showed the output was actually CORRECT — the bug doesn't manifest because both programs
assign location 0 to their only uniform. Code-only would produce a false positive.

### E6: Quantitative Confirmation
GLA returned depth=0.998 at the z-fighting location, numerically proving that the depth
buffer precision is exhausted at z=-0.5 with near=0.001/far=100000.

### E9: Direct State Evidence
GLA showed scissor_enabled=true with rect=(100,100,200,100) on draw call 1 (the 3D pass),
directly proving the state leak from the UI pass without requiring mental simulation.

## Limitations of This Eval

1. **Scenarios too easy for code-only**: Bugs have visible markers (comments, commented-out
   correct code). Real-world bugs don't self-document. The eval needs harder scenarios where
   the bug is structurally hidden.

2. **Single model**: Only tested Claude Sonnet. Different models may show different
   code-only accuracy and GLA tool usage patterns.

3. **Small sample**: 10 scenarios is not statistically significant. A proper eval needs
   50+ scenarios across difficulty tiers.

4. **Synthetic bugs**: All bugs are intentionally placed. Real bugs arise from
   misunderstanding, not intentional omission.

## Conclusions

1. **GLA's primary value is runtime confirmation, not initial diagnosis.** For bugs
   visible in source code, both approaches work. GLA adds proof.

2. **GLA uniquely detects silent bugs** (E5) — cases where code looks wrong but runtime
   behavior is correct. This is impossible with code-only analysis.

3. **Agents default to pixel queries** even with structured state inspection available.
   Future work should investigate whether steering agents toward state inspection first
   improves token efficiency.

4. **Harder eval scenarios needed** — real-world graphics bugs from GitHub issues,
   Stack Overflow, and engine bug trackers where the root cause is not obvious from
   reading the code.
