# Round 5 Capture Capability Gaps

*Written: 2026-04-19, after Round 5 eval run (`docs/eval-results.md`).*

This is the first statistically meaningful gap inventory (20 scenarios × 2
modes × 2 models = 78 runs). Round 4's sample of 4 scenarios was too small
to distinguish scenario difficulty from a GPA effect; Round 5 shows that
for the cleaned-prose, upstream-source-available setup the dominant driver
of accuracy is scenario description quality plus upstream access, not GPA.
The remaining gaps fall into three buckets: framework-level-only signal,
red-herring runtime evidence, and capture-time scenario bugs.

| # | Gap | Scenario(s) surfacing it | Leverage | Fix shape |
|---|-----|--------------------------|----------|-----------|
| 1 | `indexBufferType` not reported on draw calls | r28 mapbox GLB 65 k vertex limit | High — currently 0/3 with-GPA cells | Expose `index_type: "UNSIGNED_SHORT"|"UNSIGNED_INT"` (from `glDrawElements` `type` arg) and `max_index` in `/frames/<id>/drawcalls/<dc>`. Lets the agent detect index-type truncation without needing framework-internal state. |
| 2 | No invariant/NaN annotation on framebuffer pixels | r27 three.js anisotropic black squares | High — active source of confusion (GPA *regressed* accuracy vs code-only on both models) | Add `/frames/<id>/framebuffer/nan-mask` or `.../inf-mask` returning a bitmask image of pixels whose computed-vs-expected output diverged. Today the agent sees "patches of black" and correctly hypothesises NaN, but cannot distinguish `0/0` (D_GGX distribution) from `saturate()` removal (V_GGX visibility) — both would produce the same pixel pattern. Without a way to trace *which* instruction produced the NaN, GPA becomes a misleading signal. A related fix: shader-step debug with per-instruction value capture for a sample pixel. |
| 3 | Symbol/layer placement state never surfaces in the GL stream | r29 mapbox two-symbol-layers | Medium — only 1/2 code-only cells succeeded; GPA cannot run (scenario crashed) | Tier 3 metadata from a mapbox-gl-js plugin (POST `placement.placements` map and layer→source attribution per frame). Same fix-shape as R4 gap #1; now confirmed to recur in a second independent Mapbox scenario. |
| 4 | GBuffer attachment ↔ fragment output declaration mismatch not flagged | r32 three.js points-material MRT | Medium — sonnet code-only missed it (1/4 cell) | Add a derived field `fragment_outputs_mismatch_attachments: bool` (plus the diff list) to each draw call. Requires parsing shader GLSL `layout(location=X) out` declarations and comparing with `glDrawBuffers`. This gap would also catch many future G-Buffer/MRT regressions. |
| 5 | Scenario capture binary segfaults before first swap | r29_add_an_animated_icon_to_the_map_not_work | Low (scenario bug, not a product gap) — blocks with_gpa measurement | Fix the r29 `main.c` repro so it can initialize GL and issue at least one draw call. Orthogonal to OpenGPA's capabilities. |

## Notes on evidence quality

- Gap (1) is the clearest "add one field, close the cell" improvement in
  Round 5. The pattern (narrow integer type silently truncating at a
  CPU-side boundary) will generalise to future scenarios: anything with
  `GL_UNSIGNED_BYTE` indices, `short` vertex attributes, or 16-bit depth
  textures in contexts where higher precision is needed.
- Gap (2) is the first time live runtime data *hurt* diagnosis quality
  in the eval. Both `with_gpa` agents on r27 wrote confident, well-argued,
  and plausible-looking root-cause statements that nonetheless pointed at
  the wrong function. Code-only agents, forced to read the shader and
  reason about the semantic change in the diff, landed on the ground
  truth. This says the failure mode "LLM over-weights vivid runtime
  evidence" is real and needs to be mitigated either by (a) richer
  runtime evidence that actually distinguishes the two hypotheses
  (NaN-origin instruction traces) or (b) prompting that tells the agent
  to triangulate runtime + source.
- Gaps (3) and (4) are incremental; they each affect one scenario in the
  current batch but the underlying capability (Tier 3 metadata; shader
  output declaration parsing) has a broad surface.

## Not a product gap

- **Haiku+GPA outperformance from Round 4 did not replicate.** Round 4's
  finding on r10 looks like a sample-of-one artifact: at n=20 the
  force-multiplier effect washed out. Future rounds should either (a)
  deliberately select scenarios where the bug mechanism *requires*
  runtime data (pooled-resource aliasing, driver timing, feedback loops),
  or (b) accept that code+upstream is a very strong baseline for cleanly
  described real-world bugs and lean harder on Tier 3 metadata to find
  leverage.
