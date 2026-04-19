# Round 4 Capture Capability Gaps

*Written: 2026-04-19, after Round 4 eval run (`docs/eval-results.md`).*

Gaps discovered by running the eval harness against real upstream
snapshots for the first time. Each row is a missing OpenGPA capability
that would convert a currently-unreachable bug into a diagnosable one,
ranked by leverage (high = would change a per-scenario accuracy cell
from N to Y without any additional model intelligence).

| # | Gap | Scenario surfacing it | Leverage | Fix shape |
|---|-----|-----------------------|----------|-----------|
| 1 | No framework-level (Tier 3) metadata plugin for any JS framework | r27 mapbox-gl-js fractional maxZoom | High — currently 0/4 across all models and modes | Ship a mapbox-gl-js plugin that POSTs `SourceCache.maxzoom`, tile-bounds, and proxy-source config to the sidecar API. The bug lives in JS state upstream of any GL call, so a GL shim alone will never see it. |
| 2 | No derived "texture also attached to current FBO" field on per-draw-call queries | r10 three.js feedback loop | Medium — turns a multi-call cross-reference into a single field | Add `collides_with_fbo_attachment: true` to each entry in `/frames/<id>/drawcalls/<dc>/textures`; alternatively expose a new `/frames/<id>/drawcalls/<dc>/feedback-loops` endpoint that returns offending texture IDs by name. |
| 3 | No Tier 3 plugin for three.js | r6, r10 three.js | Medium — would let the agent attribute bare GL names to framework symbols (e.g. "texture 1 = transmissionRenderTarget.texture") without having to grep | Same plugin shape as (1) but for three.js: POST per-frame scene-graph metadata (active render target, material uniform bindings, geometry→object-name map). |
| 4 | No Metal capture backend | r15 godot mobile macOS | Out of scope (platform) | Metal shim would require a CoreGraphics / Metal Performance Shaders capture path. Not planned for the current OpenGPA roadmap; the r15 pattern would be re-diagnosable on any Vulkan/OpenGL Godot build. |

## Notes on evidence quality

- Gap (1) is the single largest accuracy delta in Round 4: every agent
  went down a sophisticated-but-wrong rabbit hole in `transform.ts` /
  `source_cache.ts` when the fix is a one-line `Math.ceil` in
  `terrain.ts`. No amount of model capability closed this gap.
- Gap (2) is where OpenGPA demonstrably helped the smaller model:
  Haiku+GPA caught r10's feedback loop in 38 turns; Haiku+code_only
  missed it in 29 turns, producing a confident but wrong diagnosis.
  A derived collision field would compress this further.
