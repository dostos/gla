# E4: Double-Negation Culling

## User Report

I added a horizontal mirror to one of my cube instances by negating the X
scale in the model matrix. The result looks "almost right" — it's clearly
recognisable as a cube — but some faces appear missing or inside-out
depending on the viewing angle. There's no GL error, no shader warning,
and the same code path renders the non-mirrored cubes correctly. I've
tried adjusting the matrix construction and the cull state independently
and neither change makes things look fully correct.

## Expected Correct Output

A solid-coloured cube where each of the six faces is a distinct flat colour;
back-faces are correctly culled; no inside-out faces are visible.

## Actual Broken Output

Some faces that should be visible are culled; some faces that should be
hidden (back-faces of the mirrored geometry) are shown. The cube appears
to have missing or reversed faces depending on viewing angle. The scene
does not look completely wrong — it superficially resembles a cube — which
makes the partial-cancellation hard to spot.

## Ground Truth

Two independent errors interact and partially cancel each other.

**Error 1** — model matrix has a negative X scale (`mvp[0] = -mvp[0]`) to
mirror the mesh horizontally. A negative determinant in the model matrix
flips the winding order of every triangle from CCW to CW in clip space.

**Error 2** — `glFrontFace(GL_CW)` is set with a misleading comment
("GL_CW because right-handed coords"), ostensibly to compensate for the
mirrored winding. However this makes CW triangles *front-facing*, which
means the *original* CCW faces (now appearing as CW after the mirror) are
treated as front-facing and survive culling — so they do render.
Simultaneously, the faces that should be back-facing in the mirrored object
are now CCW, which GL_CW declares as back-facing, so they get culled.

The double-negation means neither error by itself would cause the visual
artifact. Removing only `GL_CW` (while keeping the negative scale) would
make all front-facing surfaces disappear. Removing only the negative scale
(while keeping `GL_CW`) would render a correct but non-mirrored cube with
inverted culling. The correct fix is:

1. Keep negative X scale for the intended mirroring.
2. Revert `glFrontFace` to the default `GL_CCW`.

The negative determinant in the model matrix naturally flips the winding in
clip space; no `glFrontFace` change is needed to compensate.

## Difficulty Rating

**Very Hard (5/5)**

Partial cancellation means the visual output is "almost right" which
discourages deep investigation. Finding the root cause requires:

1. Recognising that cull artifacts can stem from winding, not missing
   geometry.
2. Knowing that a negative-scale matrix changes the sign of the
   determinant and therefore flips winding.
3. Reasoning that two opposite-sign errors can produce a plausible but
   incorrect outcome.
4. Not being misled by the (wrong) explanatory comment.

## Adversarial Principles

- **Compensating errors**: Two bugs cancel enough to produce an output that
  superficially passes a visual sanity check.
- **Misleading comment**: `"// GL_CW because right-handed coords"` provides
  a plausible but incorrect justification that discourages further scrutiny.
- **Domain-specific knowledge gap**: The interaction between negative matrix
  determinants and `glFrontFace` is non-obvious and under-documented.
- **Symptom ambiguity**: Missing or inside-out faces can result from many
  different bugs (wrong normals, wrong depth test, wrong indices, wrong
  matrices).

## How OpenGPA Helps

OpenGPA surfaces the complete pipeline state and active matrices at draw
time, so the combination of front-face mode and the model matrix
determinant is observable in a single snapshot. A code-only agent must
mentally trace winding-affecting state across multiple functions and files.
