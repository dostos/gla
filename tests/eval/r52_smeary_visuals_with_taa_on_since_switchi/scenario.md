# R52_SMEARY_VISUALS_WITH_TAA_ON_SINCE_SWITCHI: Fullscreen quad overwrites TAA motion vectors

## Bug
A post-processing fullscreen quad that samples `screen_texture` is left bound to the motion-vector MRT attachment. Its fragment shader writes zero (or any constant) to that attachment, wiping out the per-pixel scene motion vectors written by the geometry pass. TAA reprojection then samples a corrupt motion-vector buffer, producing the smear and ghosting reported in 4.4.

## Expected Correct Output
After both passes, motion-vector attachment 1 should still contain the per-pixel data emitted by the scene pass — varying across the screen (encoded here as `vec3(uv.x, uv.y, 0.5)`).

## Actual Broken Output
Attachment 1 is uniformly black: the fullscreen post quad's MRT-bound fragment shader overwrote every texel with `vec4(0)`.

## Ground Truth Diagnosis
The issue thread pinpoints exactly this overwrite:

> "I suspect the solution here is to allow disabling motion vectors for things like the full screen quad… In 4.3 the full screen quad trick wasn't an issue because we rejected all previous samples in motion anyway. But now it's possible to overwrite the motion vectors and truly break TAA."

> "transparent objects shouldn't be writing to the MV buffer. The bug here is that the full screen quad is getting added to the MV write pass despite reading from the screen texture."

The regression was bisected to commit `7f1863f83d` (PR #86809), which tuned TAA disocclusion so previous samples are no longer aggressively rejected — exposing the latent overwrite. PR #77523 (`motion_draw_disabled` render_mode) proposes the engine-side fix.

## Difficulty Rating
4/5

## Adversarial Principles
- mrt_attachment_overwrite
- post_pass_corrupting_intermediate_buffer
- latent_bug_unmasked_by_tuning_change

## How OpenGPA Helps
OpenGPA can sample the motion-vector color attachment after each draw call. After the scene draw the attachment contains varying per-pixel data; after the post draw it collapses to a single dominant color. That before/after comparison points directly at the offending draw call without requiring a TAA-aware visualizer.

## Source
- **URL**: https://github.com/godotengine/godot/issues/103629
- **Type**: issue
- **Date**: 2025-02-27
- **Commit SHA**: 7f1863f83d
- **Attribution**: Reported by @jijigri; root cause from @clayjohn

## Tier
core

## API
opengl

## Framework
none

## Bug Signature
```yaml
type: framebuffer_dominant_color
spec:
  attachment: 1
  after_draw_call_index: 1
  dominant_color_rgba: [0, 0, 0, 255]
  dominant_fraction_threshold: 0.95
  expected_varying: true
```

## Predicted OpenGPA Helpfulness
- **Verdict**: yes
- **Reasoning**: A per-draw-call read of color attachment 1 reveals that draw call 1 (scene) leaves it varying while draw call 2 (post) collapses it to uniform zero — the bug is one query away.

## Observed OpenGPA Helpfulness
- **Verdict**: ambiguous
- **Evidence**: validation skipped (--no-validate)
