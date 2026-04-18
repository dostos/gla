# OpenGPA Eval Results

## Methodology

- 18 scenarios: 10 synthetic (e1-e10) + 8 real-world (r-prefix, from Three.js/Godot GitHub issues)
- Two modes: **Code-Only** (source + description) and **With OpenGPA** (source + description + live REST API)
- Agent: Claude Sonnet, non-directive prompts ("use whatever approach you think is best")
- Tracked: accuracy, tool sequence, unique OpenGPA insights

## Round 1: Synthetic Scenarios (e1-e10) — WITH hint comments

Both modes: 10/10 correct, high confidence. The bug-revealing comments (`// BUG:`, `// should be`) made code-only trivially easy. **Result: eval was unfair.**

## Round 2: Real-World Scenarios (r-prefix) — WITH hint comments

Both modes: 7/7 correct, high confidence. Again, comments made it too easy.

## Round 3 (pending): All scenarios — AFTER hint stripping

Comments stripped. The bugs are structurally present but not self-documented. This is the fair comparison. **Not yet run.**

## OpenGPA Unique Insights (from Round 2)

Even when both modes get the right answer, OpenGPA provides **runtime evidence** that code-only cannot:

| Scenario | OpenGPA Signal | Why Code-Only Can't See It |
|----------|-----------|---------------------------|
| r16 shadow cull | cull_mode=GL_FRONT (1028) | Distinguishes from r14's GL_BACK — same visual symptom, different root cause |
| r20 neg scale | det(model_matrix)=-1 from captured mat4 | Need to compute 4x4 determinant mentally from code |
| r17 SVG z-fight | Both DCs have uniform uZ=0.0 | Need to trace uniform value through code |
| r5 feedback loop | texture_id=1 bound to sampler AND FBO simultaneously | Need to trace FBO allocation + texture binding |
| r1 UBO overflow | Draw issued but pixel=clear color | Need to know GL_MAX_UNIFORM_BLOCK_SIZE limit |
| r31 missing clear | 2 DCs per frame, no glClear between them | Need to trace render loop control flow |
| e5 uniform collision | Bug doesn't manifest (uniform locs identical) | Impossible without runtime data |

## Tool Usage Patterns

**With OpenGPA mode tool sequence (consistent across all scenarios):**
```
read_source → query_drawcalls → inspect_drawcall → query_pixel
```

- **Pixel queries**: Used in 100% of scenarios (framebuffer trap confirmed)
- **State queries** (inspect_drawcall): Also 100% — used alongside pixels, not instead of
- **Texture queries**: Used when textures relevant (r5, e8)
- **Scene queries**: 0% — not useful without Tier 3 metadata

## OpenGPA Capture Limitations Found

| Limitation | Impact | Fix Needed |
|-----------|--------|-----------|
| `explain_pixel` returns draw_call_id=null | Can't trace pixel → specific draw call | Implement draw call ID buffer |
| Vec3 uniform values garbled | Multi-component float uniforms serialize wrong | Fix serialization for vec2/vec3/vec4 types |
| Render pass auto-detection empty | `list_render_passes` returns nothing without metadata | Expected — Tier 2 debug markers needed |
| shader_id always 3 | All scenarios show same program ID | Expected — single program per scenario |

## Improvement Backlog (from eval findings)

### P0: Fix vec3 uniform serialization
Several scenarios (r17, e10) depend on reading vec3/vec4 uniform values. Currently garbled.

### P1: Implement draw call ID buffer for pixel attribution
`explain_pixel` is the most powerful query but currently can't map pixel → draw call.

### P2: Add glClear interception
r31 (missing clear) would be immediately diagnosable if OpenGPA tracked clear calls between draw calls.

### P3: Track FBO attachments in shadow state
r5 (feedback loop) requires knowing which texture is attached to the current FBO. Currently not captured.

## Conclusions

1. **OpenGPA's primary value is distinguishing bugs with identical symptoms.** r14 and r16 both produce black screens from culling. Code analysis can find both, but OpenGPA instantly distinguishes them via `cull_mode` (1028 vs 1029).

2. **OpenGPA detects silent/compensating bugs.** e5's uniform collision doesn't manifest at runtime. Only OpenGPA can confirm this (code-only reports a false positive).

3. **The eval scenarios need hint-stripped code** for a fair comparison. Round 3 (pending) will show the real accuracy gap.

4. **The improvement backlog is concrete** — each limitation was discovered by running the eval, not hypothesized. This validates the eval-driven development loop.
