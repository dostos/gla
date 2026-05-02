# R14_CANNOT_OVERRIDE_VERTEXNODE_OF_INSTANCED_: Overriding vertexNode on an InstancedMesh with morphTargets yields a blank draw

## User Report
I've had mixed luck in the past doing a custom vertexNode for instanced mesh like so:

```js
// insty is a shared instanced buffer attribute
const vOverride = Fn(() => {
  return mul(
    cameraProjectionMatrix,
    modelViewMatrix,
    insty.element(instanceIndex),
    vec4(mul(positionGeometry.xyz, noiseMix), 1)
  );
});
```

However when I go to try this with my instanced-mesh with morph-targets I get no errors but also nothing draws on screen.

Spent a day trying to figure this out and AFAIK it's impossible to do a VertexNode that properly replicates the original behavior of an instancedMesh material's vertexNode so it can be modified. Ideally I'd also be able to use the `InstanceMatrix` and other built-in attributes instead of rolling my own.

A maintainer suggested replacing `positionGeometry` with `positionLocal`, but that still draws nothing when the mesh has both instancing and morph targets. You can observe the instanced-mesh normally by commenting out the vertexNode override.

Live example: https://jsfiddle.net/q28ast3k/9/

Version: r176. Browsers: Firefox, Safari, Chrome. OS: MacOS, Windows, Linux.

Feels like when you replace the vertexNode it breaks things and/or doesn't expose GPU vars you'd want via TSL.

## Expected Correct Output
The instanced mesh renders with the overridden vertex transform applied on top of morph-target-deformed, per-instance-positioned geometry — i.e., each instance's morphed surface is transformed by the user-supplied node graph and is visible on screen.

## Actual Broken Output
Black screen. No GPU errors, no shader compile failures. The draw call executes but produces no visible output. Removing the `material.vertexNode` assignment restores normal instanced rendering.

## Ground Truth
The TSL node pipeline builds a material's vertex stage from a chain of default nodes that successively inject skinning, morph, instance, and batch transforms into the local position before projection. When a user assigns a custom `vertexNode`, three.js replaces the *final* position expression in the stage but the upstream injection hooks (morph deltas and instance-matrix multiplies) need a specific surface to write into — namely `positionLocal`, not the raw `positionGeometry` attribute. The maintainer confirmed this contract in the thread:

> `positionGeometry` represents the plain position attribute data. `positionLocal` instead honors vertex transformations that have been added via skinning or morphing as well as additional transformations via instancing and batching.

However, the reporter verified in the same thread that even with `positionLocal`, the combined instancing + morph case still produces a blank draw:

> Hey @Mugen87 very much appreciate the explanation, unfortunately no-dice w/ `positionLocal` for me. […] you can observe the instanced-mesh normally by commenting out the vertexNode override.

So the ground truth, as documented on the open issue (https://github.com/mrdoob/three.js/issues/31131), is twofold:

1. `positionGeometry` unconditionally bypasses the morph/instance injection stages — this is by design and is the primary reason the reporter's first snippet draws nothing.
2. When `vertexNode` is assigned (even reading `positionLocal`), the morph-target attribute setup and/or the per-instance matrix binding is not established on the WebGPURenderer pipeline for an `InstancedMesh` that also has morph targets, so the vertex positions collapse (likely to zero or off-screen NDC). The issue is unresolved upstream as of the most recent comment; no fix commit has landed, and no maintainer has posted a root-cause analysis beyond the `positionLocal` hint.

The scoring agent should recognise the `positionGeometry` vs `positionLocal` distinction as the partial fix surfaced in the thread, and should flag that the instancing+morph combination is an upstream-unresolved interaction — not claim a specific code-level root cause that the thread does not support.

## Difficulty Rating
5/5

## Adversarial Principles
- node-graph-opaque-to-gl-capture
- framework-contract-not-spec-compliance
- unresolved-upstream-bug

## How OpenGPA Helps
A Tier-1 GL capture shows the draw call executing with a shader program whose vertex output produces degenerate clip-space positions, but cannot name the TSL node at fault. A Tier-3 three.js sidecar that reports the compiled vertex shader string plus the list of nodes contributing to `positionLocal` would let the agent diff the node chain between the working (no override) and broken (override) cases and spot the missing morph/instance injection.

## Source
- **URL**: https://github.com/mrdoob/three.js/issues/31131
- **Type**: issue
- **Date**: 2026-04-20
- **Commit SHA**: (n/a)
- **Attribution**: Reported by @zalo; maintainer hint from @Mugen87

## Tier
snapshot

## API
opengl

## Framework
none

## Upstream Snapshot
- **Repo**: https://github.com/mrdoob/three.js
- **SHA**: (auto-resolve from commit HEAD-of-r176)
- **Relevant Files**:
  - src/nodes/accessors/PositionNode.js
  - src/nodes/accessors/MorphNode.js
  - src/nodes/accessors/InstanceNode.js
  - src/materials/nodes/NodeMaterial.js
  - src/renderers/webgpu/nodes/WGSLNodeBuilder.js
  - src/objects/InstancedMesh.js

## Bug Signature
```yaml
type: missing_draw_call
spec:
  description: >
    Instanced draw executes but produces no on-screen pixels because the
    overridden vertexNode collapses positions to a degenerate range; the
    framebuffer-dominant-colour check should show 100% background clear
    colour in the mesh's expected screen-space bounds.
  expected_visible_instances: 1
  observed_visible_instances: 0
```

## Predicted OpenGPA Helpfulness
- **Verdict**: ambiguous
- **Reasoning**: Tier-1 GL capture reveals that a draw ran and produced no visible fragments, which narrows suspicion to vertex-stage transform breakage but cannot distinguish `positionGeometry` vs `positionLocal` semantics — those live entirely above the GL boundary in the TSL node graph. Real help requires a Tier-3 three.js sidecar reporting the node chain and compiled shader source; without that, an agent will correctly localise the problem to "vertex transform dropped" but cannot produce the `positionLocal` fix guidance that the maintainer provided.

## Observed OpenGPA Helpfulness
- **Verdict**: ambiguous
- **Evidence**: validation skipped (--no-validate)
