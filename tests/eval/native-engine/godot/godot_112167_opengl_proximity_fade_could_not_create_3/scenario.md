# R36_OPENGL_PROXIMITY_FADE_COULD_NOT_CREATE_3: Compat back-buffer depth/stencil texture has mismatched pixel `type`

## User Report
### Tested versions

4.5.1.stable

### System information

Linux Mint 21.3 - 4.5.1.stable - Open GL - GTX 1650

### Issue description

I made a shader based on Proximity Fade but it doesnt work if Scaling 3D is anything other than 100%. Proximity Fade itself doesnt work either but thats not my issue. Since i copy pasted it from the same code it gives the same error.

The Error

check_backbuffer: Could not create 3D back buffers, status: GL_FRAMEBUFFER_INCOMPLETE_ATTACHMENT
  <C++ Source>  drivers/gles3/storage/render_scene_buffers_gles3.cpp:540 @ check_backbuffer()

The Shader

```
shader_type spatial;
uniform sampler2D depth_texture : hint_depth_texture;

void fragment() {
  float depth = texture(depth_texture, SCREEN_UV).x;
  #if CURRENT_RENDERER == RENDERER_COMPATIBILITY
  vec3 ndc = vec3(SCREEN_UV, depth) * 2.0 - 1.0;
  #else
  vec3 ndc = vec3(SCREEN_UV * 2.0 - 1.0, depth);
  #endif
  vec4 view = INV_PROJECTION_MATRIX * vec4(ndc, 1.0);
  view.xyz /= view.w;
  ALPHA *= clamp(1.0 - smoothstep(view.z + 0.1, view.z, VERTEX.z), 0.0, 1.0);
}
```

### Steps to reproduce

Enable Proximity Fade and change Scaling 3D away from 100%

### Minimal reproduction project (MRP)

N/A

## Expected Correct Output
Binding the back-buffer FBO, clearing to green, and blitting to the default framebuffer produces a green frame (center pixel ≈ `(0, 255, 0, 255)`).

## Actual Broken Output
The back-buffer FBO is incomplete, so the clear and the blit are both no-ops. The default framebuffer retains its earlier black clear — center pixel is `(0, 0, 0, 255)`.

## Ground Truth
The GLES3 Compatibility renderer has two code paths for setting up the 3D back buffers — one for 3D-scaling == 100%, another for anything else. The scaling path allocates the depth/stencil back-buffer texture with a pixel `type` argument that does not form a valid combination with `internalformat=GL_DEPTH24_STENCIL8` / `format=GL_DEPTH_STENCIL`. `glTexImage2D` rejects the call with `GL_INVALID_OPERATION`, the texture has no storage, and the FBO it is attached to becomes `GL_FRAMEBUFFER_INCOMPLETE_ATTACHMENT`. Any subsequent rendering into the back buffer is silently discarded, which breaks effects (like Proximity Fade) that sample the depth texture.

Divergent initialization paths for the Compatibility back buffer use different `type` values for the depth/stencil texture, despite every other parameter matching. The scaling-path value isn't a legal combination with `GL_DEPTH_STENCIL`, so the FBO ends up incomplete.

From the linked PR #111234:

> Whether 3d scaling is on or off changes the code path for setting up the buffers... This pr just copies the same `type` value found in the other code path when using `GL_DEPTH_STENCIL`... Aside from this one value all of the others are already the same, so I am assuming that this was a mistake in the first place.

The issue reporter observed it surfacing as:

> `check_backbuffer: Could not create 3D back buffers, status: GL_FRAMEBUFFER_INCOMPLETE_ATTACHMENT`

and confirmed after the PR merged:

> #111234 fixed the issue.

## Difficulty Rating
4/5

## Adversarial Principles
- divergent-code-paths-with-drifted-parameters
- silent-gl-error-swallowed-by-caller
- fbo-completeness-depends-on-texture-storage-validity
- internalformat-format-type-combination-trap

## How OpenGPA Helps
An OpenGPA query that asks for the attachment state of each FBO — specifically the `internalformat` / `format` / `type` of the texture bound to `GL_DEPTH_STENCIL_ATTACHMENT` and the outcome of `glCheckFramebufferStatus` — immediately surfaces that the depth/stencil texture has no storage and that the FBO reports `GL_FRAMEBUFFER_INCOMPLETE_ATTACHMENT`. Cross-referencing the `glTexImage2D` call that produced `GL_INVALID_OPERATION` with the mismatched `type` argument pinpoints the root cause without the user having to read either code path.

## Source
- **URL**: https://github.com/godotengine/godot/issues/112167
- **Type**: issue
- **Date**: 2026-04-18
- **Commit SHA**: (n/a)
- **Attribution**: Reported by upstream Godot user; diagnosed in linked PR #111234

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
  region: center_pixel
  expected_dominant: "green (FBO clear blitted to default framebuffer)"
  actual_dominant: "black (FBO incomplete, clear+blit skipped, default fb untouched)"
  tolerance: "green channel > 128 ⇒ correct; green channel ~0 and all channels < 32 ⇒ bug"
```

## Upstream Snapshot
- **Repo**: https://github.com/godotengine/godot
- **SHA**: e72374a5da98f3c824974507dbdf3e8529940d95
- **Relevant Files**:
  - drivers/gles3/storage/texture_storage.cpp  # default-branch SHA at issue close; fix via PR #111234 (copy type value); (inferred)
  - drivers/gles3/storage/render_scene_buffers_gles3.cpp
  - drivers/gles3/rasterizer_scene_gles3.cpp

## Predicted OpenGPA Helpfulness
- **Verdict**: yes
- **Reasoning**: The failure is a direct, inspectable state anomaly — an FBO whose depth/stencil attachment texture has no storage because `glTexImage2D` was called with an illegal `type`/`internalformat` pairing. Both the GL error on the `glTexImage2D` call and the `GL_FRAMEBUFFER_INCOMPLETE_ATTACHMENT` status are exactly the kind of per-call and per-object facts OpenGPA exposes, so a single query about FBO completeness or recent GL errors will land on the root cause.

## Observed OpenGPA Helpfulness
- **Verdict**: ambiguous
- **Evidence**: validation skipped (--no-validate)
