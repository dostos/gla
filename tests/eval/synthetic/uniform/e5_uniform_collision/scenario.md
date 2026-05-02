# E5: Uniform Location Collision

## User Report

I have two materials, RED and BLUE, drawn as two quads — left should be red,
right should be blue. After a recent refactor (which involved reordering
some unrelated enum values in the materials header), the colors come out
wrong: the left quad renders blue and the right quad renders red, or both
end up the same color depending on order. There are no GL errors; both
shaders compile and link, both `glUniform4f` calls return without complaint,
and the upload values on the CPU side are exactly what they should be
(`(1,0,0,1)` for red, `(0,0,1,1)` for blue). It worked before the refactor.

## Expected Correct Output

- Left quad: solid red (MAT_RED material)
- Right quad: solid blue (MAT_BLUE material)

## Actual Broken Output

Both quads render with swapped or identical colors. In the specific
simulation: left quad renders blue, right quad renders red (or both render
the color of whichever was set last, depending on GL program state).

## Ground Truth

Two material objects share a uniform-location cache indexed by a `MaterialID`
enum. A developer reordered the enum values during a refactoring:

```c
// Before reorder:    MAT_RED = 0, MAT_BLUE = 1
// After reorder:     MAT_BLUE = 0, MAT_RED = 1
```

The cache array (`color_loc_cache[MAT_COUNT]`) was not invalidated after the
reorder. It was originally populated as:

```
cache[0] = glGetUniformLocation(prog_for_old_slot_0, "uColor")  // was RED
cache[1] = glGetUniformLocation(prog_for_old_slot_1, "uColor")  // was BLUE
```

After the reorder, code reads `cache[MAT_RED=1]` to set the red material's
color, but slot 1 now holds the location that was cached for the BLUE
program. The `glUniform4f` call uploads red into the wrong program's uniform.

The uniform-location cache must be invalidated (or re-queried) whenever
the enum-to-program mapping changes. A safer design queries locations once
per program at link time and stores them *per program object*, not in a
global array keyed by an enum. The fix:

```c
color_loc_cache[MAT_RED]  = glGetUniformLocation(prog[MAT_RED],  "uColor");
color_loc_cache[MAT_BLUE] = glGetUniformLocation(prog[MAT_BLUE], "uColor");
```

## Difficulty Rating

**Hard (4/5)**

The symptom (wrong colors) points to shader state, but there are many
possible causes: wrong uniform value, wrong `glUseProgram`, wrong location
lookup, or a shader source error. The actual cause — a stale enum-keyed
cache — requires understanding the mapping between the enum, the cache
array, and the program objects across a refactoring history that may not be
visible in the current diff.

## Adversarial Principles

- **Temporal causation**: The bug was introduced by a previous commit
  (enum reorder) that looks unrelated to the rendering code.
- **Indirect indexing**: The mismatch is in the *mapping* between enum
  values and cache slots, not in any single wrong value.
- **No error at the bug site**: `glGetUniformLocation` and `glUniform4f`
  both succeed; `glGetError` returns `GL_NO_ERROR`. The uniform value
  reaches the GPU correctly — it just reaches the wrong program.
- **Plausible alternative hypotheses**: An agent might instead blame
  `glUseProgram` ordering, shader compilation, or an off-by-one in the
  draw call's VAO binding.

## How OpenGPA Helps

OpenGPA captures the active program and resolved uniform values at each
draw call, so the actual color reaching the GPU per program is observable
without reasoning about the cache. A code-only agent must trace the enum
through the cache and correlate the location integer with the right program.
