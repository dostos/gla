# E22_DEPTH_TEST_GL_GREATER_SET_WITH_STANDARD_PERSPECTIVE_BACK_FAC: Back quad occludes front quad under leaked GL_GREATER

## Bug
A helper that configured a reversed-Z depth prepass sets `glDepthFunc(GL_GREATER)` and `glClearDepth(0.0)`, then returns. The main render path assumes defaults and never resets the depth function, so with standard perspective projection the farther quad wins the depth test against the nearer quad.

## Expected Correct Output
Center pixel red: RGBA ≈ `(255, 0, 0, 255)`. The near red quad at view z=-2 should cover the far blue quad at view z=-5.

## Actual Broken Output
Center pixel blue: RGBA ≈ `(0, 0, 255, 255)`. The far (back) quad paints and the near (front) quad is rejected by depth test.

## Ground Truth Diagnosis
`configure_depth_pipeline()` leaves `GL_DEPTH_FUNC=GL_GREATER` and `GL_DEPTH_CLEAR_VALUE=0.0` in the context. After the "reset" block in `main`, those two pieces of state are never overwritten. On frame clear the depth buffer fills with `0.0`; the back quad (window-depth ≈ 0.95) passes `0.95 > 0.0` and writes. The front quad (window-depth ≈ 0.75) then fails `0.75 > 0.95` and is discarded. The net effect is inverted occlusion: back occludes front.

## Difficulty Rating
**Moderate (3/5)**

The main render loop looks textbook — back-to-front painter's order with depth test enabled and depth mask on. The offending state is set three calls away inside an innocuously named helper, and the draw calls themselves contain no obvious mistake.

## Adversarial Principles
- **Inverted predicate**: `GL_GREATER` is a single token swap from the default `GL_LESS`, silently flipping who-wins-depth with no other symptom (no GL error, no log).
- **State pollution**: the depth function is set by a helper that is no longer responsible for the draw; the main path's "standard reset" misses it because comments suggest it was restored.

## How OpenGPA Helps

The specific query that reveals the bug:

```
inspect_drawcall(frame="current", draw_call_index=1)
```

The returned state snapshot for the second draw shows `depth_test=ENABLED`, `depth_func=GL_GREATER`, and `clear_depth=0.0`. Seeing `GL_GREATER` attached to a draw that uses a standard forward perspective matrix (near plane 0.1, far 100.0) immediately fingers the inverted predicate — no shader walk or projection math required.

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
  rule: "glDepthFunc must be GL_LESS (or GL_LEQUAL) for forward perspective with default clear depth 1.0; GL_GREATER belongs to a reversed-Z pipeline with clear depth 0.0"
  draw_call_index: 1
  state_key: "depth_func"
  observed: "GL_GREATER"
  expected: "GL_LESS"
```