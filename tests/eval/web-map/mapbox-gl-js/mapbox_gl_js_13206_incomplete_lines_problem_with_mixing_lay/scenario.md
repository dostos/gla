# R15_INCOMPLETE_LINES_PROBLEM_WITH_MIXING_LAY: Layer slot=top occluded by slot=middle when registered first

## User Report
**mapbox-gl-js version**: v3.4.0 / v3.5.0-beta.1

**browser**: All chromium & Firefox

### Steps to Trigger Behavior

 1. Use the standard mapbox style
 2. Create a line layer with slot: "top"
 3. Create a line layer with slot: "middle"

### Screenshots

On the left is the slot=middle feature and the problem occurs on the right
hand feature with slot=top.

### Link to Demonstration

https://jsfiddle.net/ArmandBahi/0afktyqv/5/

### Description

I've added two layers, the first with slot=top and the second with
slot=middle as below

```js
map.addLayer({
    id: 'line1',
    source: 'line1',
    type: 'line',
    slot: 'top',
    paint: {
        "line-color": "blue",
        "line-width": 2,
        "line-translate-anchor": "viewport",
        "line-emissive-strength": 1,
        "line-occlusion-opacity": 1
    }
});

map.addLayer({
    id: 'line2',
    source: 'line2',
    type: 'line',
    slot: 'middle',
    paint: {
        "line-color": "blue",
        "line-width": 2,
        "line-translate-anchor": "viewport",
        "line-emissive-strength": 1,
        "line-occlusion-opacity": 1
    }
});
```

When doing this the slot=top layer is messing up with buildings.

**I've also notice that if I add the slot=middle before slot=top then I do
not have the problem**

## Expected Correct Output
The blue line (slot=top) is fully visible across the entire viewport, drawn above the gray building shadow (slot=middle) wherever they overlap, regardless of which layer was added to the map first.

## Actual Broken Output
Where the top-slot line crosses the middle-slot building footprint, the building's shadow paints over the line, leaving a visible gap in the linestring. The line is only fully visible outside the building quad.

## Ground Truth
The maintainer explained the underlying mechanism in the issue thread:

> Just so you know, during 3D globe and terrain rendering, GL JS aims to batch multiple layers together for optimal performance. This process might lead to a rearrangement of layers. Layers draped over the globe and terrain, such as fill, line, background, hillshade, and raster, are rendered first. These layers are rendered underneath symbols, regardless of whether they are placed in the middle or top slots or without a designated slot.

In other words, line layers are drape-batched before the symbol/overlay pass, and within that drape batch they are emitted in registration order rather than by slot priority. When the top-slot line is registered before the middle-slot building, both end up in the same drape group, and the line is drawn first — then the building paints on top of it. The maintainer confirmed the fix had already shipped:

> This is fixed in the latest version

No fix PR or commit was cited in the thread, so the diagnosis rests on the batching explanation in Comment 1 plus the reporter's order-dependent reproduction evidence (swapping registration order removes the symptom, which is the signature of order-sensitive batch emission).

## Difficulty Rating
3/5

## Adversarial Principles
- registration_order_leak_through_batching
- slot_priority_contract_violation
- hidden_draw_order_from_performance_batching

## How OpenGPA Helps
`list_draw_calls` shows the two quads in registration order with no depth test — making the bug's mechanism (second draw paints over first) directly visible. `get_pixel` at the overlap region returns the middle-layer color instead of the top-layer color, confirming which draw won the overlap. An agent still needs external knowledge that the top layer was *supposed* to render above the middle layer; OpenGPA can expose order but not slot intent.

## Source
- **URL**: https://github.com/mapbox/mapbox-gl-js/issues/13206
- **Type**: issue
- **Date**: 2024-06-11
- **Commit SHA**: (n/a)
- **Attribution**: Reported by @ArmandBahi; batching behavior explained by Mapbox maintainer

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
    x: 200
    y: 200
    width: 1
    height: 1
  expected_color:
    r_range: [0.05, 0.20]
    g_range: [0.15, 0.30]
    b_range: [0.85, 1.00]
  rationale: >
    At the center pixel, the slot=top blue line crosses the slot=middle
    gray building. The slot contract requires the top layer to win the
    overlap (pixel ≈ blue). With the bug, the middle layer is drawn
    after the top layer in the same drape batch and paints over it,
    yielding a gray pixel instead.
```

## Upstream Snapshot
- **Repo**: https://github.com/mapbox/mapbox-gl-js
- **SHA**: ff7842c94a34acb54240c1d55c59a0034e6ca24f
- **Relevant Files**:
  - src/style/style.ts  # default-branch SHA at issue close (drape batching; no public fix PR); (inferred)
  - src/render/draw_line.ts
  - src/render/painter.ts

## Predicted OpenGPA Helpfulness
- **Verdict**: ambiguous
- **Reasoning**: OpenGPA exposes the raw draw order (top quad issued before middle quad, no depth test, identical blend state) and a color probe showing gray where blue is expected — both are necessary evidence. But the diagnosis "this is a slot-priority inversion caused by batching" requires the agent to know the Mapbox slot contract; OpenGPA cannot surface that intent. An agent that only sees "two quads drawn in this order" may just call it a straightforward overdraw, not a slot violation. Helpfulness depends on the querying agent bringing slot semantics to the table.

## Observed OpenGPA Helpfulness
- **Verdict**: ambiguous
- **Evidence**: validation skipped (--no-validate)
