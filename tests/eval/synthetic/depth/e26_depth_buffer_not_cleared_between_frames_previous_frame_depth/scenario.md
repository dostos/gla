# E26_DEPTH_BUFFER_NOT_CLEARED_BETWEEN_FRAMES_PREVIOUS_FRAME_DEPTH: Stale depth buffer occludes new geometry

## User Report
On frame 1 I draw a single far full-viewport green quad. It should fill
the screen. Instead it shows up everywhere except for a rectangular hole
in the center — the hole is exactly where frame 0 had drawn a closer red
quad. The hole shows the clear color (~26,26,26,255), not the green I
expect. Frame 0 itself looks correct. There are no GL errors and the
draw is well-formed.

## Expected Correct Output
Frame 1 should show a solid green quad covering the viewport (the far quad at z=+0.5 is the only draw of that frame). Center pixel RGBA ≈ (51, 255, 51, 255).

## Actual Broken Output
Frame 1 shows the green quad with a rectangular clear-color (dark gray, ~26,26,26,255) hole in the center where frame 0's red quad had been drawn. `glReadPixels` at the center reads the clear color, not green: `center RGBA: 26 26 26 255`.

## Ground Truth
The render loop clears only `GL_COLOR_BUFFER_BIT` each frame, leaving the
depth buffer populated with frame 0's near-quad depth values. On frame 1,
a farther full-viewport quad fails the depth test in the region where
frame 0 drew, producing a clear-colored hole shaped like the previous
frame's geometry.

`glClear` is called each frame with only `GL_COLOR_BUFFER_BIT`;
`GL_DEPTH_BUFFER_BIT` is omitted. Depth test is enabled with `GL_LESS`.
Frame 0 writes depth ≈ 0.4 (for z=-0.2 in NDC after viewport depth range
mapping) into the center region. Frame 1 draws a quad at z=+0.5 whose
depth ≈ 0.75 fails `LESS` against the retained 0.4, so those fragments
are discarded. Fix: `glClear(GL_COLOR_BUFFER_BIT | GL_DEPTH_BUFFER_BIT)`.

## Difficulty Rating
**Medium (3/5)**

The render code looks correct in isolation — both draws are well-formed and the depth test configuration is standard. The defect is what's *missing* from `glClear`, a single bit-flag omission that only manifests cross-frame.

## Adversarial Principles
- **Missing clear**: The bug is an absent flag, not wrong code — inspection naturally focuses on what *is* there.
- **Accumulated state**: The symptom depends on depth values written by a prior frame, invisible when examining frame 1 in isolation.

## How OpenGPA Helps

OpenGPA can compare per-pixel depth values across frames, so depth values
in frame 1 that match frame 0's geometry rather than the cleared default
indicate the depth buffer was not actually reset between frames.

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
  expected_rgba: [0.1, 0.1, 0.1, 1.0]
  tolerance: 0.05
  region: center_pixel
  frame_index: 1
  note: "Frame 1 center pixel reads clear-color instead of green because stale depth from frame 0 rejects the far quad's fragments."
```
