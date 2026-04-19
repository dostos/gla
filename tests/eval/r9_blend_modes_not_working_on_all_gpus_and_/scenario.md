# R9: BlendLayers uniform arrays exceed GL_MAX_FRAGMENT_UNIFORM_COMPONENTS

## User Report
**Pixelorama version:**
1.0

**OS/device including version:**
Multiple devices, will explain below

**Issue description:**
What the title says.

This is mostly intended as a reminder for me to fix these issues before 1.0 is ready, but any contributor is welcome to jump in if they want to.

### Issue 1
Layer blend modes, introduced in #911, are not working on all GPUs, and as the result the canvas appears blank (besides the transparency checker background) even if you draw on it. This is because of these uniforms in the BlendLayers shader:
```glsl
uniform float[1024] opacities;
uniform int[1024] blend_modes;
uniform vec2[1024] origins;
```
Since shaders cannot have uniform arrays with variable length, we have to specify a constant length. In my desktop GPU, NVIDIA GTX 1060 6GB, the 1024 limit is working as intended. However, on my Android device, Huawei P Smart (GPU: Mali-T830 MP2), this is not working. I didn't do extensive testing for multiple lengths, but lowering the length to 256 on all three uniforms is working.

### Potential solution 1
Instead of passing three uniform arrays, construct a Nx3 texture, where N is the current number of layers, and use each pixel for the information we want to store, and pass that as a uniform to the shader. This is the solution I am leaning towards. This should also remove the hard layer limit. My main worry is performance, we would have to construct or update the texture every time the user draws, which could be slow.

### Potential solution 2
Somehow check each device's shader uniform limits, and dynamically change the shader on runtime. Not sure if that's even possible to do correctly, so maybe instead we could set the limit to be quite low (maybe to something like 32), and let the user themselves set the number from the preferences. This isn't ideal, as we can't expect every user to troubleshoot which values work and which don't, and it feels like a very hacky solution overall.

### Issue 2
The way the layer image data are being passed into the shader, is by looping through all of the layers, getting all of the image data into an array, and using that to construct a Texture2DArray, every single time the user draws. On my computer and on low canvases, I do not notice a performance issue, but it is quite apparent on larger canvases. Even with Godot 4's GDScript performance increases, drawing in 1.x feels slower than in 0.11.x in large canvases.

### Solution
Construct the Texture2DArray once, and re-construct it only when the number of layers change, or if the project changes. When drawing, check which layers are being edited, and call `update_layer()` only on those layers. Even if there's just a single layer, this operation is cheaper than just re-constructing the whole thing over and over.

### Extra "solution" if performance issues insist
Worse case scenario, we can use the old layer drawing method when all layer blending modes are set to "Normal", and only use the shader-based version when at least one layer has a different blending mode.

### Potential solution for all of the above issues
Maybe using [Drawable Textures](https://github.com/godotengine/godot-proposals/issues/7379) instead could help, when they get implemented.

## Expected Correct Output
A full-screen quad tinted from the uniform arrays covers the window.

## Actual Broken Output
The window stays the clear color (dark blue ≈ RGB 0,0,102) — the draw call
is a no-op because the shader program failed to link.

## Ground Truth
A fragment shader declares three large uniform arrays (`float[]`, `int[]`,
`vec2[]`) whose combined component count exceeds
`GL_MAX_FRAGMENT_UNIFORM_COMPONENTS`. The program link silently fails and
subsequent draws produce nothing. The caller never inspects
`GL_LINK_STATUS` or the program info log, so the only symptom is a blank
frame.

Pixelorama #938 describes this exactly. The BlendLayers shader (introduced
in PR #911) declares:

> ```glsl
> uniform float[1024] opacities;
> uniform int[1024] blend_modes;
> uniform vec2[1024] origins;
> ```

On the reporter's desktop (GTX 1060) the GPU limit accommodates these
arrays, so blending renders correctly. On a mobile GPU it does not:

> "on my Android device, Huawei P Smart (GPU: Mali-T830 MP2), this is not
> working ... lowering the length to 256 on all three uniforms is working."

OpenGL ES 3.0 only guarantees `MAX_FRAGMENT_UNIFORM_COMPONENTS >= 896`,
and many mobile drivers expose close to that minimum. Declaring
1024 × float + 1024 × int + 1024 × vec2 = 4096 components overflows the
limit; the fragment program link fails, `glUseProgram` silently has no
effect, and the draw emits nothing. Because the Godot-level code in
`ShaderImageEffect.gd` never checks `get_link_status()` equivalent or the
info log, the failure surfaces only as a blank canvas. The reproducer
scales each array to 8192 elements so the same link-time overflow
triggers on desktop GPUs whose typical limit is 4096 components.

## Difficulty Rating
3/5

## Adversarial Principles
- silent-link-failure
- gpu-capability-divergence
- no-error-check-after-shader-build

## How OpenGPA Helps
Querying the active shader program exposes `GL_LINK_STATUS == GL_FALSE`
and the info log ("fragment shader uses too many uniform components")
immediately. Without that, the agent sees only a blank framebuffer and
must guess which stage of the pipeline dropped the geometry.

## Source
- **URL**: https://github.com/Orama-Interactive/Pixelorama/issues/938
- **Type**: issue
- **Date**: 2023-09-05
- **Commit SHA**: (n/a)
- **Attribution**: Reported by @OverloadedOrama (see linked PR #911)

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
  dominant_color_rgba: [0, 0, 102, 255]
  min_fraction: 0.95
```

## Upstream Snapshot
- **Repo**: https://github.com/Orama-Interactive/Pixelorama
- **SHA**: 88a2ef593eacc1859ee52570e2bfab223628bfe6
- **Relevant Files**:
  - src/Classes/ShaderImageEffect.gd  # parent of closing commit bc8a9de4d (BlendLayers uniform size reduction)
  - src/Shaders/BlendLayers.gdshader

## Predicted OpenGPA Helpfulness
- **Verdict**: yes
- **Reasoning**: OpenGPA's shader-program inspection surfaces
  `GL_LINK_STATUS` and the program info log directly; the root cause
  (uniform component overflow) is in that log line. Without OpenGPA, the
  agent only sees an empty frame and has to probe many candidate causes
  (clear-color mismatch, missing viewport, wrong VAO binding, etc.)
  before reaching the shader linker.

## Observed OpenGPA Helpfulness
- **Verdict**: ambiguous
- **Evidence**: validation skipped (--no-validate)
