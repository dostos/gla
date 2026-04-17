# R5_FEEDBACK_LOOP_ERROR_WITH_TRANSMISSION_AN: Transmission RT feedback loop when `samples == 0`

## Bug
A transmissive DoubleSide material's back-face pass samples from the
transmission render target's texture while that same texture is
attached as `COLOR_ATTACHMENT0` of the currently bound framebuffer.
When the renderer is created with `antialias: false` and
`WEBGL_multisampled_render_to_texture` is unavailable, three.js r182
builds the transmission RT with `samples: capabilities.samples`, which
evaluates to `0`, so no MSAA renderbuffer is allocated and the texture
is attached directly — producing a GPU read/write feedback loop on
every frame.

## Expected Correct Output
A refracted glass sphere rendered to the transmission RT without GL
errors, with the back-face pass reading from an MSAA-resolved copy of
the transmission target (as in r181 and earlier, which hardcoded
`samples: 4`).

## Actual Broken Output
Every frame emits hundreds of `GL_INVALID_OPERATION: Feedback loop
formed between Framebuffer and active Texture`. Draw calls in the
back-face pass are silently dropped by the driver; the resulting
frame shows partial/missing transmissive geometry and lost
antialiasing.

## Ground Truth Diagnosis
The regression was introduced in r182 by PR #32444, which parameterised
the transmission RT's sample count:

> PR #32444 changed the transmission render target in
> `renderTransmissionPass()` from `samples: 4` (hardcoded) to
> `samples: capabilities.samples` (dynamic). With `antialias: false`,
> `gl.getParameter(gl.SAMPLES)` returns `0`, so the transmission RT is
> created with `samples: 0`.

The `samples == 0` path attaches the texture directly instead of
resolving from a renderbuffer:

> ```
> samples >= 1:  Framebuffer → Renderbuffer (MSAA) → blitFramebuffer → Texture (safe)
> samples == 0:  Framebuffer → Texture (direct attachment, same object read + written)
> ```

The feedback loop fires inside the DoubleSide back-face block that
runs when the MSAA render-to-texture extension is missing:

> During `renderObject()`, the shader reads from
> `transmissionRenderTarget.texture` (the transmission map uniform)
> while the same texture is simultaneously the bound framebuffer's
> `COLOR_ATTACHMENT0`.

A maintainer confirmed the root fix in comment 1:

> The force of MSAA has hidden a feedback loop that is present in the
> current transmission implementation. […] How about we update the
> code to: `samples: Math.max( 4, capabilities.samples );`

## Difficulty Rating
4/5

## Adversarial Principles
- Platform-dependent extension gating hides the bug on the primary
  dev platform (macOS Chrome has `WEBGL_multisampled_render_to_texture`)
- Regression is triggered by a configuration combination
  (`antialias: false` + `DoubleSide` + transmission) rather than a
  single flag
- Rendering still produces a frame — the failure is a flood of GL
  errors plus silent draw-drops, not a crash or blank screen
- MSAA previously acted as an accidental guardrail; removing it
  exposed a pre-existing invariant violation

## How GLA Helps
At the offending `glDrawArrays`, GLA can inspect live GL state and
observe that the texture bound to sampler unit 0 is also the current
framebuffer's `COLOR_ATTACHMENT0` — the exact invariant the spec
forbids. A single state query at draw time pinpoints the feedback
loop without needing a full MSAA/no-MSAA behavioural diff.

## Source
- **URL**: https://github.com/mrdoob/three.js/issues/33060
- **Type**: issue
- **Date**: 2026-04-18
- **Commit SHA**: (n/a)
- **Attribution**: Reported upstream on mrdoob/three.js#33060; regression introduced by PR #32444

## Tier
core

## API
opengl

## Framework
none

## Bug Signature
```yaml
type: unexpected_state_in_draw
spec:
  condition: sampled_texture_is_current_color_attachment
  sampler_unit: 0
  framebuffer_attachment: GL_COLOR_ATTACHMENT0
  draw_call: glDrawArrays
  must_be_equal:
    - bound_texture(GL_TEXTURE0, GL_TEXTURE_2D)
    - framebuffer_attachment_object(GL_DRAW_FRAMEBUFFER, GL_COLOR_ATTACHMENT0)
```

## Predicted GLA Helpfulness
- **Verdict**: yes
- **Reasoning**: The failure mode is a single-draw state invariant
  (sampler texture name == current color attachment name). GLA's
  draw-time state inspection directly surfaces this equality, whereas
  purely visual diffs are fragile because the bug manifests as
  dropped draws plus an error flood rather than a deterministic
  pixel change.

## Observed GLA Helpfulness
- **Verdict**: ambiguous
- **Evidence**: validation skipped (--no-validate)
