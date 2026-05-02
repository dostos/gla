# E16_UNIFORM_LIFECYCLE_GLGETUNIFORMLOCATION_CACHED_ACROSS_GLLINKP: Stale uniform location used after re-link

## User Report
My fullscreen quad is supposed to render solid red — I'm calling
`glUniform4f(locColor, 1, 0, 0, 1)` every frame on a uniform `uColor` in
my fragment shader. Instead the quad renders black (RGBA 0,0,0,255). I
verified that `locColor` is non-negative (came from a successful
`glGetUniformLocation` call), the program links without info-log errors,
and the uniform is declared in the active fragment shader. The shaders
get hot-swapped at startup (I detach one fragment shader and attach a
slimmer variant before linking again) but I cache the uniform location
once and reuse it across frames.

## Expected Correct Output
Center pixel is red, RGBA approximately (255, 0, 0, 255). The fullscreen quad should pick up the color supplied by `glUniform4f(locColor, 1, 0, 0, 1)` on every frame.

## Actual Broken Output
Center pixel is black, RGBA (0, 0, 0, 255). The quad renders black because `uColor` keeps its post-link default value of (0, 0, 0, 0); the driver raises `GL_INVALID_OPERATION` for the stale-location `glUniform4f` but the program carries on without any visible sign of failure.

## Ground Truth
A uniform location returned by `glGetUniformLocation` is cached after the
first link, then the program is re-linked with a different fragment
shader. The cached location is stale under the new link, so every
subsequent `glUniform4f` call silently fails to set the intended uniform.

The GL spec is explicit: uniform locations returned by
`glGetUniformLocation` are valid only for the specific linked program
state at the time of the call, and are invalidated by any subsequent
`glLinkProgram`. Here, `locColor` is queried after the first link, where
the fragment shader declares two uniforms (`uTint`, `uColor`) — drivers
like Mesa assign `uColor` to location 1 in that layout. The code then
detaches the first fragment shader, attaches a slimmer one that declares
only `uColor`, and re-links. In the new program `uColor` sits at location
0; location 1 no longer corresponds to any active uniform. The subsequent
`glUniform4f(locColor=1, ...)` is rejected with `GL_INVALID_OPERATION`
(silently), leaving `uColor` at its default-zero value. The fragment
shader writes `vec4(uColor.rgb, 1.0)` = black to every pixel. Fix:
re-query the location after every `glLinkProgram`.

## Difficulty Rating
**Hard (4/5)**

The two fragment shaders look nearly identical, the location query and the re-link are separated by several unrelated setup statements, and `glUniform4f` is a call that readers assume just works. Nothing in the draw or in the shader output hints at uniform-plumbing failure, and there is no GL error check in the code to flush the silent `INVALID_OPERATION`.

## Adversarial Principles
- **Caching across invalidation**: A handle (uniform location) captured from the resource's old state (first link) is reused after the resource is invalidated (re-link). The cache is a local integer that silently drifts out of sync with the GL object it once referred to.
- **Silent no-op**: `glUniform4f` on a stale location raises `GL_INVALID_OPERATION` and does nothing. No crash, no exception, no divergent control flow — just a uniform stuck at its default and a draw that quietly produces the wrong color.

## How OpenGPA Helps

OpenGPA's per-frame capture surfaces each draw's bound program, the
program's current uniform reflection (active names ↔ locations), and the
set of `glUniform*` writes during the frame. Comparing "what location did
the code write" to "what location does the active uniform actually live
at" is a one-shot lookup.

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
