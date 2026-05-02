# E23_DEPTH_WRITE_DISABLED_GL_FALSE_FOR_OPAQUE_GEOMETRY_LATER_DRAW: Depth writes disabled on opaque pass, far geometry stomps near

## User Report
I draw two opaque quads — a near red one at z=-0.5 and a far blue one at
z=+0.5 — with depth test enabled and `GL_LESS`. The center pixel should be
red (the near quad occluding the far one) but it comes out blue: the far
quad covers the whole framebuffer and the near red draw seems to vanish
even though `glDrawArrays` is called for it. There's a setup helper that
runs before the loop to "configure transparent pass" but I'm not in a
transparent pass here. No GL errors.

## Expected Correct Output
Center pixel RGBA ≈ `255 0 0 255` (the near red quad at z=-0.5 should
occlude the far blue quad at z=0.5).

## Actual Broken Output
Center pixel RGBA = `0 0 255 255`. The far blue quad covers the whole
framebuffer — the near red draw is visually gone even though it was
submitted and its fragments did pass the depth test.

## Ground Truth
`glDepthMask(GL_FALSE)` leaked from a previous transparent pass is still
in effect when two opaque quads are drawn. Depth testing is enabled so
each quad passes `GL_LESS` against the cleared buffer, but because
nothing ever writes to the depth buffer the far quad is never rejected
and overwrites the near one.

With `GL_DEPTH_TEST` enabled and `glDepthFunc(GL_LESS)`, the first draw's
fragments pass because the cleared depth is 1.0. But `glDepthMask(GL_FALSE)`
suppresses the write, so the depth buffer remains at 1.0 everywhere. The
second (farther) draw then also passes `GL_LESS` against 1.0 and its
fragments overwrite the color buffer. The root cause is a legacy state
leak: an earlier transparent pass disabled depth writes and the opaque
pass was not re-enabling them. Fix: call `glDepthMask(GL_TRUE)` before
the opaque pass.

## Difficulty Rating
**Medium (3/5)**

Depth test is enabled, depth clears happen every frame, and every draw is
"correct" in isolation. The culprit is one GL flag toggled far from the
draw site, and the symptom (far geometry overwriting near geometry) looks
like a vertex-ordering or z-fighting issue at first glance.

## Adversarial Principles
- **Mismatched flags**: `GL_DEPTH_TEST=true` and `GL_DEPTH_WRITEMASK=false`
  is a valid-but-dangerous combination — tests pass without updating the
  buffer, so draw order silently decides visibility.
- **Legacy state leak**: the offending `glDepthMask(GL_FALSE)` happens once
  at setup (standing in for a prior transparent pass) and is never visible
  in the render loop where the symptom appears.

## How OpenGPA Helps

OpenGPA exposes the full depth-related pipeline state per draw call,
including `depth_mask`, so a depth-test-on / depth-write-off combination
is directly visible in the per-draw record.

## Tier
core

## API
opengl

## Framework
none

## Bug Signature
```yaml
type: unexpected_state_in_draw
spec:
  rule: "opaque draw calls must have GL_DEPTH_WRITEMASK=GL_TRUE when GL_DEPTH_TEST is enabled"
  draw_call_index: 1
  expected:
    depth_test: GL_TRUE
    depth_mask: GL_TRUE
  actual:
    depth_test: GL_TRUE
    depth_mask: GL_FALSE
  consequence: "far geometry (z=0.5) overwrites near geometry (z=-0.5); center pixel is blue instead of red"
```
