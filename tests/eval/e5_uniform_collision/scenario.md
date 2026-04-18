# E5: Uniform Location Collision

## Bug

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
program. The `glUniform4f` call uploads red into the wrong program's uniform,
and blue into the red program's uniform.

**Location:** `e5_uniform_collision.c`, uniform cache initialisation block.

## Expected Correct Output

- Left quad: solid red (MAT_RED material)
- Right quad: solid blue (MAT_BLUE material)

## Actual Broken Output

Both quads render with swapped or identical colors. In the specific
simulation: left quad renders blue, right quad renders red (or both render
the color of whichever was set last, depending on GL program state).

## Ground Truth Diagnosis

The uniform-location cache must be invalidated (or re-queried) whenever
the enum-to-program mapping changes. A safer design queries locations once
per program at link time and stores them *per program object*, not in a
global array keyed by an enum. The fix for this specific bug:

```c
// Re-query after any enum reorder:
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

```
inspect_drawcall(draw_id=1, query="shader")
inspect_drawcall(draw_id=2, query="shader")
```

OpenGPA captures the active program and all uniform values at each draw call:

```json
// Draw 1 (left quad, intended MAT_RED)
{
  "program_id": 1,
  "uniforms": {
    "uColor": [0.0, 0.0, 1.0, 1.0]   // blue! code intended [1,0,0,1]
  }
}

// Draw 2 (right quad, intended MAT_BLUE)
{
  "program_id": 2,
  "uniforms": {
    "uColor": [1.0, 0.0, 0.0, 1.0]   // red! code intended [0,0,1,1]
  }
}
```

Seeing that draw 1's `uColor` is blue when the code called
`glUniform4f(..., 1,0,0,1)` immediately signals a location mismatch. A
code-only agent must trace the enum value through the cache, understand
the reorder history, and correlate the location integer with the right
program — all without seeing the actual runtime values.
