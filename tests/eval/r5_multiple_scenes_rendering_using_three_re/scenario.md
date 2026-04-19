# R5: Multiple scenes via THREE.RenderPass — text overlay occluded by leftover terrain depth

## User Report
I have the following problem: Trying to render multiple scenes for postprocessing using RenderPass.

There are 2 scenes now:

1) terrain + clouds

2) text layer

Both scenes are rendering but the text layer gets blended into the terrain (normally if they would be rendered in the same scene it should act like this). What is strange: I can see the text through the clouds which are rendered much higher than the terrain (both terrain and clouds are in the same scene for testing)

You cann see the text above the clouds but it blends to the terrain

To render it i'm using the following code:

```
    @renderPass = new THREE.RenderPass( @scene, @camera )
    @renderPass.renderToScreen = true
    @renderPass.clear = false
    @renderPass.clearDepth = true

    @textPass = new THREE.RenderPass( @textScene, @camera )
    @textPass.renderToScreen = true
    @textPass.clear = false
    @textPass.clearDepth = true

@composer = new THREE.EffectComposer( @renderer );

        @composer.addPass( @renderPass )
        @composer.addPass( @textPass )

```

But when Im trying to render them normally using:

```
    @renderer.clear()
    @renderer.render @scene, @camera
    @renderer.clearDepth();
    @renderer.render @textScene, @camera

```

everything works as expected.

## Expected Correct Output
The bright text quad is fully visible, drawn on top of the terrain regardless
of its z value, because the depth buffer is cleared between passes.

## Actual Broken Output
The text overlay is invisible (or only partially visible) wherever the terrain
covers the same region. The pixel where text should appear shows the terrain
color instead.

## Ground Truth
A two-pass composition renders a "terrain" scene, then a "text overlay" scene
on top via a second `RenderPass`. The user sets `clearDepth = true` on the
overlay pass, expecting the depth buffer to be cleared between the passes so
that the text draws unconditionally over the terrain. Instead, the text
fragments fail the depth test against the depth values left behind by the
terrain pass, and the overlay either disappears or visibly blends into the
geometry below.

Pre-r83 `THREE.RenderPass.render()` did not honor a `clearDepth` flag — the
property could be set on the pass instance, but the render method never called
`renderer.clearDepth()`. So the second pass inherits the depth buffer from the
first pass; with `GL_LESS` (or three.js's default `LessEqualDepth`) and the
overlay geometry at greater depth than the underlying terrain, the overlay
fragments are discarded.

The accepted answer states it directly:

> RenderPass doesn't actually have a `clearDepth` option. I opened a pull
> request to add support for this, which should fix your problem:
> https://github.com/mrdoob/three.js/pull/10159
> Update: The pull request was merged and included in the r83 release, so your
> code as written should now work.

The pre-fix `RenderPass.js` source confirms this — its `render()` method
references `this.clear` but has no code path that consults `this.clearDepth`
or invokes `renderer.clearDepth()`. PR mrdoob/three.js#10159 added that call.

## Difficulty Rating
3/5

## Adversarial Principles
- state_leak_across_passes
- depth_buffer_lifecycle
- silent_property_ignored

## How OpenGPA Helps
Querying the per-draw-call state for the second (text) draw call reveals
`GL_DEPTH_TEST = GL_TRUE`, `GL_DEPTH_FUNC = GL_LESS`, and — crucially — that
no `glClear(GL_DEPTH_BUFFER_BIT)` was issued between the terrain draw and the
text draw. Comparing depth-buffer contents before and after the overlay draw
shows the overlay region's depth values unchanged from the terrain pass,
proving the overlay fragments were rejected by the depth test rather than
never submitted.

## Source
- **URL**: https://stackoverflow.com/questions/40548144/multiple-scenes-rendering-using-three-renderpass
- **Type**: stackoverflow
- **Date**: 2016-11-11
- **Commit SHA**: (n/a)
- **Attribution**: Reported by StackOverflow user; fix in mrdoob/three.js PR #10159

## Tier
core

## API
opengl

## Framework
none

## Bug Signature
```yaml
type: unexpected_color
spec:
  region:
    x_min: 180
    x_max: 220
    y_min: 140
    y_max: 160
  expected_color:
    r_min: 0.15
    r_max: 0.30
    g_min: 0.85
    g_max: 1.00
    b_min: 0.20
    b_max: 0.45
  description: >
    Center pixel should be the bright-green text overlay color. In the buggy
    output it is the red-brown terrain color (~0.8, 0.3, 0.2) because the text
    fragments failed the depth test against leftover terrain depth.
```

## Predicted OpenGPA Helpfulness
- **Verdict**: yes
- **Reasoning**: The diagnosis is a classic "what state was active when this
  draw call executed, and what cleared/didn't clear before it" question.
  OpenGPA's per-draw-call state snapshot plus the command stream between
  draws (showing the absence of any depth-clear) makes the missing
  `glClear(GL_DEPTH_BUFFER_BIT)` immediately visible — far more directly
  than reading three.js's RenderPass source to discover the property is
  silently ignored.

## Observed OpenGPA Helpfulness
- **Verdict**: ambiguous
- **Evidence**: validation skipped (--no-validate)
