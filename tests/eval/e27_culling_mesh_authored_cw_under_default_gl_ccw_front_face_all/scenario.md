# E27_CULLING_MESH_AUTHORED_CW_UNDER_DEFAULT_GL_CCW_FRONT_FACE_ALL: Clockwise quad culled under default CCW front-face

## Bug
A quad authored with clockwise (CW) vertex winding is drawn with back-face
culling enabled and the default `GL_CCW` front-face convention. Every
triangle is classified as a back face and culled — nothing is rasterized.

## Expected Correct Output
A centered orange quad (RGBA ~ 255, 128, 51, 255) covering roughly 64% of
the viewport. Center pixel at (200,150) should sample inside the quad.

## Actual Broken Output
The framebuffer is the clear color (black) everywhere. Center pixel reads
RGBA = 0 0 0 255. The draw call completes without GL error but produces
zero visible fragments.

## Ground Truth Diagnosis
The mesh vertex order for both triangles (TL→BL→TR, TR→BL→BR) traverses
each triangle clockwise in window space. With `GL_CULL_FACE` enabled and
`glFrontFace(GL_CCW)` selecting counter-clockwise as front, CW triangles
are classified as back faces. `glCullFace(GL_BACK)` then discards them
before rasterization. The fix is either to reorder the indices to CCW,
flip `glFrontFace(GL_CW)`, or disable culling — but the code and shaders
themselves are correct; the defect is the mismatch between the asset's
winding convention and the render state.

## Difficulty Rating
**Low-Medium (2/5)**

The draw call issues without error and no warning appears. Reading the
vertex array to determine winding order by hand requires carefully
plotting six 2D points in signed area order — easy to miscount.

## Adversarial Principles
- **Winding convention**: CW vs CCW is invisible in the source; it only
  emerges from the geometric order of vertices in the buffer.
- **Invisible geometry**: Culled draws succeed silently — there is no GL
  error, no shader warning, no missing-draw-call indicator in vanilla GL.

## How OpenGPA Helps

The specific query that reveals the bug:

```
inspect_drawcall(frame=current, index=0)
```

`inspect_drawcall` returns the full pipeline state for the draw: it
reports `front_face=GL_CCW` and `cull_face=GL_BACK` alongside the raw
vertex attribute data. Cross-referencing the per-triangle winding of the
vertex stream against the active front-face convention immediately shows
that every primitive will be classified as a back face and culled.

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
  expected_rgba: [0.0, 0.0, 0.0, 1.0]
  tolerance: 0.05
```