# E24_REVERSED_Z_EXPECTED_BUT_PROJECTION_MATRIX_STILL_PRODUCES_0_1: Reversed-Z depth state paired with a standard [-1,1] NDC projection

## User Report
I draw two triangles back-to-back: a near red one at view z=-1 and a
farther blue one at z=-3. The near triangle is submitted first. Center
pixel comes out blue (~RGBA 51,51,230,255) instead of the expected red
(~230,51,51,255) — the far triangle wins the depth test. Depth test is
enabled, depth writes are on, the geometry is correct, both triangles
pass culling, and there are no GL errors. I've tried reversing draw order
and the result is the same.

## Expected Correct Output
Center pixel shows the near (red) triangle at approximately `RGBA (230, 51, 51, 255)` — the near triangle is drawn first and the later far (blue) triangle is rejected by the depth test.

## Actual Broken Output
Center pixel shows the far (blue) triangle at approximately `RGBA (51, 51, 230, 255)`. The near triangle is drawn first and *written*, but the far triangle (drawn afterward) has a numerically *larger* depth value under a standard projection, so `GL_GREATER` lets it overwrite everything.

## Ground Truth
The depth state is configured for reversed-Z rendering (`glClearDepth(0.0)`
+ `glDepthFunc(GL_GREATER)`) but the projection matrix fed to the shader
is a textbook OpenGL perspective that still produces NDC z in [-1,1] —
i.e. near→0, far→1 in the depth buffer. The two conventions disagree, so
depth ordering is silently inverted.

Reversed-Z rendering requires *both* a swapped depth state (clear=0, func
=GREATER) *and* a projection that maps near→1, far→0 in the depth buffer
(typically via `glClipControl(GL_LOWER_LEFT, GL_ZERO_TO_ONE)` plus a
matrix with `M[2][2]=n/(f−n)`, `M[2][3]=fn/(f−n)`, or simply swapping
near/far in the standard formula). Here only half of the contract is
kept: the depth state is reversed, but `perspective_std(...)` produces
the standard matrix with `M[2][2] ≈ −1.002`, `M[3][2] = −1`,
`M[2][3] ≈ −0.2002` — i.e. `(f+n)/(n−f)` and `2fn/(n−f)`, which give
near→−1 and far→+1 in NDC. After the viewport depth-range map to [0,1],
near fragments get depth ≈ 0.9 and far fragments ≈ 0.98; `GL_GREATER`
therefore prefers the *far* object, producing blue. Fix: either revert
the depth state to standard (`GL_LESS`/`clearDepth=1.0`) or replace
`perspective_std` with a reversed-Z projection.

## Difficulty Rating
**Expert (5/5)**

Every individual ingredient looks defensible: `glDepthFunc(GL_GREATER)` with `glClearDepth(0.0)` is the canonical reversed-Z snippet, and `perspective_std(...)` is a textbook perspective. The bug only exists in the *combination*, and the symptom (wrong triangle wins) is easily misread as a draw-order or culling bug. Reviewers searching for a single defective line find none.

## Adversarial Principles
- **Convention mismatch**: Two correct, well-known snippets (reversed-Z depth state, standard perspective) are individually valid but contractually incompatible. No single line is wrong.
- **Hidden assumption**: The code never states "this is reversed-Z" — the convention is implicit in the depth-state pair, and the projection author's assumption silently diverges from the depth-state author's.

## How OpenGPA Helps

OpenGPA captures the bound program's projection uniform alongside the
depth-state snapshot for each draw call, so the convention mismatch
between a reversed-Z depth pair and a forward-Z projection matrix is
visible in a single record.

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
