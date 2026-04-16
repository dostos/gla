# E8: Race Condition Texture Upload

## Bug

The application intends to display a 64×64 checkerboard texture on a quad.
The texture object is seeded with a 1×1 white placeholder at creation time
(a common pattern to keep the texture object valid while real data is loaded
asynchronously). The real upload is guarded by a flag `upload_complete` that
is never set to `1`, simulating a background loader thread that stalls or
crashes before signalling completion.

```c
int upload_complete = 0; /* BUG: never set */
if (upload_complete) {
    glTexImage2D(..., 64, 64, ...);
}
```

## Expected Output

A quad covered in a black-and-white 8×8-tile checkerboard pattern (64×64
texture, 8-pixel tiles).

## Actual Output

A uniformly white quad. The 1×1 placeholder is used for all rendering.

## Ground Truth Diagnosis

The 64×64 texture upload never executes. The texture object remains 1×1.
**Fix**: ensure `upload_complete` is set to `1` after the data is ready, or
upload synchronously before the render loop.

## Difficulty

**Hard.** The quad renders without error. The white colour is a plausible
background or material colour. Without knowing the intended texture, a
developer might not notice anything wrong. Checking `glGetTexLevelParameteriv`
for `GL_TEXTURE_WIDTH` at the right time requires knowing to look.

## Adversarial Principles

- **Simulated race condition**: in production the bug is a missing thread
  synchronisation; here it is a never-set flag, making the code path
  mechanically equivalent.
- **Silent failure**: no GL error is generated; the texture is valid.
- **Visually benign placeholder**: a 1×1 white texture looks like an
  intentional design choice.

## GLA Advantage

`inspect_drawcall(textures)` directly reports the bound texture dimensions as
`1×1` instead of `64×64`, pinpointing that the real upload never occurred
without requiring the developer to add probe code or inspect raw GL state
manually.
