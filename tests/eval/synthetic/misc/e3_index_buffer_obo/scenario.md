# E3: Index Buffer Off-by-One (sizeof Pointer Bug)

## User Report

My indexed cube draw should render 12 triangles (36 indices) but only one
face/triangle ever appears on screen. The remaining geometry is either
missing or shows up as garbled fragments depending on the GPU/driver. The
vertex buffer looks correct (the visible triangle has the right colors),
the shader compiles, `glGetError` returns `GL_NO_ERROR`, and the same code
runs without warning under `-Wall -Wextra`. The index data array is
declared with all 36 indices; I've printed it on the CPU side and the
contents are correct.

## Expected Correct Output

A complete solid-coloured cube (12 triangles / 36 indices visible from the
current viewpoint).

## Actual Broken Output

Only the first triangle (indices 0, 1, 2 → one face) renders correctly.
The remaining 33 draw indices reference uninitialised GPU memory, producing
undefined vertex fetches: missing triangles, garbage geometry, or driver-
specific visual corruption.

## Ground Truth

`glBufferData` is called with `sizeof(indices)` where `indices` is a
`const GLushort *` pointer, not an array. On a 64-bit system,
`sizeof(pointer) = 8`, so only 8 bytes (4 × uint16 = indices 0, 1, 2, 2)
are uploaded to the GPU instead of the required
`n_indices * sizeof(GLushort) = 36 * 2 = 72` bytes.

The pointer-vs-array `sizeof` mistake is a classic C footgun. The correct
call is:

```c
glBufferData(GL_ELEMENT_ARRAY_BUFFER,
             n_indices * sizeof(GLushort),
             indices, GL_STATIC_DRAW);
```

The compiler does not warn because `sizeof(T*)` is always valid. The bug
only manifests at runtime when `glDrawElements` fetches indices beyond the
uploaded range.

## Difficulty Rating

**Medium (3/5)**

The broken rendering (partial mesh) is visually obvious, but the cause is
not. An agent inspecting the C code must notice that `indices` is a pointer,
know the platform pointer size, and compute that `sizeof(pointer) < required
buffer size`. In a large mesh utility library this pointer can be many call
frames away from the original array declaration.

## Adversarial Principles

- **Type punning**: The C source looks correct at first glance; both
  `sizeof(arr)` and `sizeof(ptr)` are syntactically identical.
- **Platform dependence**: The bug is silent on 32-bit (pointer = 4 bytes,
  still wrong but by a different factor) and the magnitude of corruption
  varies.
- **Distance between declaration and use**: The original array
  `indices_data` is declared with the correct size, but a pointer alias
  `indices` is created before the buggy `sizeof`.

## How OpenGPA Helps

OpenGPA records the byte length of each bound buffer object at draw time,
so a mismatch between buffer size and the expected index-count footprint
is directly visible in a per-draw record. A code-only agent must trace the
`sizeof` argument through the source.
