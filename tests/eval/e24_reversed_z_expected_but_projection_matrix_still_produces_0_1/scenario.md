# E24_REVERSED_Z_EXPECTED_BUT_PROJECTION_MATRIX_STILL_PRODUCES_0_1: Reversed-Z depth state paired with a standard [-1,1] NDC projection

## Bug
The depth state is configured for reversed-Z rendering (`glClearDepth(0.0)` + `glDepthFunc(GL_GREATER)`) but the projection matrix fed to the shader is a textbook OpenGL perspective that still produces NDC z in [-1,1] — i.e. near→0, far→1 in the depth buffer. The two conventions disagree, so depth ordering is silently inverted.

## Expected Correct Output
Center pixel shows the near (red) triangle at approximately `RGBA (230, 51, 51, 255)` — the near triangle is drawn first and the later far (blue) triangle is rejected by the depth test.

## Actual Broken Output
Center pixel shows the far (blue) triangle at approximately `RGBA (51, 51, 230, 255)`. The near triangle is drawn first and *written*, but the far triangle (drawn afterward) has a numerically *larger* depth value under a standard projection, so `GL_GREATER` lets it overwrite everything.

## Ground Truth Diagnosis
Reversed-Z rendering requires *both* a swapped depth state (clear=0, func=GREATER) *and* a projection that maps near→1, far→0 in the depth buffer (typically via `glClipControl(GL_LOWER_LEFT, GL_ZERO_TO_ONE)` plus a matrix with `M[2][2]=n/(f−n)`, `M[2][3]=fn/(f−n)`, or simply swapping near/far in the standard formula). Here only half of the contract is kept: the depth state is reversed, but `perspective_std(...)` produces the standard matrix with `M[2][2] ≈ −1.002`, `M[3][2] = −1`, `M[2][3] ≈ −0.2002` — i.e. `(f+n)/(n−f)` and `2fn/(n−f)`, which give near→−1 and far→+1 in NDC. After the viewport depth-range map to [0,1], near fragments get depth ≈ 0.9 and far fragments ≈ 0.98; `GL_GREATER` therefore prefers the *far* object, producing blue.

## Difficulty Rating
**Expert (5/5)**

Every individual ingredient looks defensible: `glDepthFunc(GL_GREATER)` with `glClearDepth(0.0)` is the canonical reversed-Z snippet, and `perspective_std(...)` is a textbook perspective. The bug only exists in the *combination*, and the symptom (wrong triangle wins) is easily misread as a draw-order or culling bug. Reviewers searching for a single defective line find none.

## Adversarial Principles
- **Convention mismatch**: Two correct, well-known snippets (reversed-Z depth state, standard perspective) are individually valid but contractually incompatible. No single line is wrong.
- **Hidden assumption**: The code never states "this is reversed-Z" — the convention is implicit in the depth-state pair, and the projection author's assumption silently diverges from the depth-state author's.

## How OpenGPA Helps

The specific query that reveals the bug:

```
inspect_drawcall(frame="current", index=0)
```

The returned record carries the bound program's uniforms (including `uProj`) alongside the capture's depth-state snapshot (`depth_func=GL_GREATER`, `depth_clear_value=0.0`, `clip_control=default`). Reading `uProj` exposes `M[2][2] ≈ −1.002`, `M[3][2] = −1.0`, `M[2][3] ≈ −0.2002`, `M[3][3] = 0` — unambiguously the classical `(f+n)/(n−f)`/`2fn/(n−f)` pattern that produces NDC z in [-1,1]. Cross-referencing that against `GL_GREATER` + `clearDepth=0` in the same record makes the convention mismatch (reversed-Z state, forward-Z projection) immediately visible; neither artifact alone is a bug, but the combination is.

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
  expected_rgba: [0.2, 0.2, 0.9, 1.0]
  tolerance: 0.08
  region: center
  note: >
    Broken output shows the far (blue) triangle winning the depth test because
    the projection matrix produces standard [-1,1] NDC z (near→0, far→1 in the
    depth buffer) while the depth state (clearDepth=0, GL_GREATER) assumes a
    reversed-Z projection (near→1, far→0). Correct output would be red
    (~[0.9, 0.2, 0.2, 1.0]).
```