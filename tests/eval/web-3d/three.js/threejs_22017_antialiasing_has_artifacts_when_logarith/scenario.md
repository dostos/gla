# R2_ANTIALIASING_HAS_ARTIFACTS_WHEN_LOGARITH: gl_FragDepth write disables MSAA at geometry intersections

## User Report
When the logarithmic depth buffer is enabled, antialiasing fails in areas
where geometry intersects or lines up. See screenshot below. It feels like
this would be a common issue, but I couldn't find any other post on it.

With logarithmic depth buffer enabled. Notice the jagged, aliased lines.

With logarithmic depth buffer disabled.

I've encountered this on desktop computers. I've seen it on both Linux Ubuntu
and Fedora, in the Chrome browser. I don't remember how it looks in Windows,
but it seems a bit strange if it would be different there?

Right now we're at version 0.129.0 of threejs, but it's always been like this
since we started using logarithmic depth (1-2 years ago), and it happens with
all geometry.

Is it like this for everyone else? Any idea how to fix it, or is it something
we just have to live with?

Thanks.

## Expected Correct Output
Two intersecting triangles (blue and yellow) sharing a horizontal depth-test boundary at `y = 0`. With 4x MSAA, the intersection line is rendered as a smooth, ~1-pixel-wide blended transition band where pixels straddling the boundary have colors interpolated between pure blue and pure yellow.

## Actual Broken Output
The intersection line is pixel-sharp. Pixels are either pure blue or pure yellow (within quantization tolerance); no blended transition pixels appear along the boundary. The `GL_SAMPLES=4` framebuffer is effectively rendering at 1 sample per pixel for coverage purposes.

## Ground Truth
Writing to `gl_FragDepth` opts the fragment shader out of per-sample invocation. The outerra blog passage linked from the thread explains:

> I presume that assigning to gl_FragDepth will break the logic of MSAA, where the fragment shader is executed once per pixel of the rasterized element. It means that in this case it outputs the same depth value for all MSAA pixel samples, which is not what we want - it disables the antialiasing.

The three.js maintainers confirmed this by toggling the extension path:

> Disabling `EXT_frag_depth` in WebGL1 or WebGL2 forces three.js to emulate logarithmic depth buffer in software, and the problem disappears.

And @Mugen87 confirmed: "Yes." Per @jbaicoianu, this is an inherent trade-off of the `gl_FragDepth`-based logarithmic depth approach:

> With the extension, you get per-pixel depth values which mostly resolves the issue with large triangles, but at the cost of disabling some z-test optimizations, and introduces these weird interactions with other parts of the fragment shader which might try to use the z-buffer value later on.

The fix discussed in the thread is to keep the software-emulation path available (gated by a new `logarithmicDepthBufferForceEmulation` flag) so users whose scenes need MSAA can avoid `gl_FragDepth`.

## Difficulty Rating
4/5

## Adversarial Principles
- silent-feature-downgrade — hardware quietly drops per-sample execution without any API error or warning
- cross-feature-interaction — MSAA, depth test, and fragment shader depth output interact via implicit GPU scheduling rules
- shader-write-has-pipeline-side-effect — a seemingly benign assignment (`gl_FragDepth = gl_FragCoord.z`) reconfigures upstream rasterization behavior

## How OpenGPA Helps
An agent diagnosing jagged edges on an MSAA framebuffer can query OpenGPA for the draw call's active shader source and the framebuffer's sample count. Seeing `GL_SAMPLES > 1` alongside a fragment shader that assigns `gl_FragDepth` is the diagnostic signature; without that correlation the agent would likely misattribute the aliasing to driver/GPU settings (as the thread's early comments did).

## Source
- **URL**: https://github.com/mrdoob/three.js/issues/22017
- **Type**: issue
- **Date**: 2021-06-22
- **Commit SHA**: (n/a)
- **Attribution**: Reported by @asbjornlystrup; diagnosis by @mrdoob and @Mugen87, with supporting context from @jbaicoianu

## Tier
core

## API
opengl

## Framework
none

## Bug Signature
```yaml
type: color_histogram_in_region
spec:
  # Horizontal strip centered on the triangle intersection line (y=0 in
  # clip space → y=128 in a 256-tall framebuffer). With working MSAA,
  # this strip contains many pixels whose color is a blend of the two
  # triangle colors. Without MSAA, the strip is a hard step between
  # pure blue and pure yellow.
  region: {x: 0, y: 120, width: 256, height: 16}
  reference_colors:
    blue:   [26, 51, 230]
    yellow: [230, 204, 26]
  tolerance: 8
  expected:
    # At least 5% of pixels in the strip should be blended (not within
    # tolerance of either reference color and not the clear color).
    blended_fraction_min: 0.05
  actual_when_buggy:
    blended_fraction_max: 0.005
```

## Upstream Snapshot
- **Repo**: https://github.com/mrdoob/three.js
- **SHA**: 5e5d2711f5826972e8215f86781ead3c254abedd
- **Relevant Files**:
  - src/renderers/shaders/ShaderChunk/logdepthbuf_pars_fragment.glsl.js  # base of fix PR #29445 (reverse-z EXT_clip_control)
  - src/renderers/shaders/ShaderChunk/logdepthbuf_fragment.glsl.js
  - src/renderers/WebGLRenderer.js

## Predicted OpenGPA Helpfulness
- **Verdict**: yes
- **Reasoning**: The diagnosis requires correlating two facts that live in different parts of the pipeline: the framebuffer sample count (GL state) and the presence of a `gl_FragDepth` write in the active fragment shader (program introspection). OpenGPA's Tier 1 capture exposes both raw facts, and its per-draw-call view lets an agent check them together. Without OpenGPA, an agent would have to either reason about GLSL from source (often unavailable in a running app) or guess at GPU-scheduling semantics from screenshots alone — which is exactly where the thread's reporters initially stalled ("Sounds like a Linux driver issue indeed. Unfortunately there's not much we can do about this.") before the shader-level cause was identified.

## Observed OpenGPA Helpfulness
- **Verdict**: ambiguous
- **Evidence**: validation skipped (--no-validate)
