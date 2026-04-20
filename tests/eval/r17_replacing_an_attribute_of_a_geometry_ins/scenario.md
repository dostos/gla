# R17: Replacing a geometry's instanced attribute with a new buffer breaks the renderer

## User Report
On previous versions of Three.JS (r162, haven't tested between then and now), we were able to replace an entire instancedgeometry attribute with a new length and set the instanceCount to a superior value.

This is a valuable feature for performance if you play with huge dynamic instanced geometry that increments count over time and allows to first allocate a smaller buffer then grow with a safe multiple to limit the size of the buffer. But this also limits flexibility of building geometries by a lot.

In both WebGL and WebGPU back ends it now breaks the renderer. Look at the `switchArray` function in the attached fiddle — we replace `geometry.attributes.offset` with a freshly allocated `InstancedBufferAttribute`, bump `instanceCount`, and mark `needsUpdate = true`, but the frame no longer renders the new positions.

```js
function switchArray(){
    const newMax = 8
    const attribute = instancedGeometry.attributes.offset
    const newArray = new attribute.array.constructor(newMax * attribute.itemSize);
    newArray.set(attribute.array);
    const newAttribute = new THREE.InstancedBufferAttribute(
        newArray, attribute.itemSize, attribute.normalized
    );
    for (let i = 0; i < newAttribute.array.length; i++) newAttribute.array[i] = Math.random();
    newAttribute.setUsage(THREE.DynamicDrawUsage);
    instancedGeometry.attributes.offset = newAttribute;
    instancedGeometry.attributes.offset.needsUpdate = true;
    instancedGeometry.instanceCount = newMax
}
```

Setting `material.needsUpdate = true` does not help. Adaptive buffer sizing is a blocker for us — we start small (1 particle per character) and grow strategically as more characters join; deciding for a "large enough buffer" upfront is not feasible when the upper bound can be thousands of instances. The legacy `WebGLRenderer` handled this pattern fine for years without memory leaks in our production apps.

## Expected Correct Output
Eight red quads arranged along the top row of the framebuffer at y ≈ +0.7 (NDC), one per instance of the newly assigned offset buffer.

## Actual Broken Output
Eight red quads rendered along the bottom row at y ≈ -0.7 — the positions from the previously assigned offset buffer. The replacement attribute is never consumed by the draw call; the VAO's vertex-attribute binding for location 1 still references the original VBO.

## Ground Truth
The bug is a state leak in `InstanceNode` and `NodeMaterialObserver` in the WebGPU renderer (and an analogous leak in the WebGL backend's attribute cache). When a material is first mounted, `InstanceNode.setup()` captures the `instanceMatrix` / instanced attribute reference and allocates a GPU buffer for it; subsequent frames check only `attribute.version` / `attribute.usage`, never the attribute's **identity**. If the user reassigns `geometry.attributes.offset = newInstancedBufferAttribute`, the cached buffer (keyed by the original attribute reference inside a `WeakMap` in `WebGLAttributes` / inside `InstanceNode`'s closure for WebGPU) is never invalidated, and the draw call re-uses the stale binding.

Upstream maintainer @RenaudRohlinger identified the two required fixes:

> In `InstanceNode`, probably something like: `if ( this.instanceMatrix.uuid !== this._uuidRef ) { this.buffer.copy( this.instanceMatrix.array ); }`
>
> And notify in the `NodeMaterialObserver` when an attribute change: `attributesData[ name ] = { version: attribute.version, uuid: attribute.uuid };`

@Samsy independently localised the defect to the InstanceNode construction path:

> I think the problem comes from here, as it will not rebuild the buffer if it was built the first time — https://github.com/mrdoob/three.js/blob/86c3bd390f623005f2fae07b3dca23f904102e05/src/nodes/accessors/InstanceNode.js#L117

Maintainer @Mugen87 corroborated that "the `RenderObject` is not being updated when the geometry is changed." Related history: PR #17063 (`BufferAttribute: Introduce dispose()`) had already hardened the policy that attribute arrays should be fixed-sized after creation, but left the caching layer unable to detect replacement — which is exactly the crack this bug slips through.

In the raw-GL port above, the pattern manifests as: a VAO that once called `glVertexAttribPointer(1, …)` while `GL_ARRAY_BUFFER = vboOffsetOld` is not rebound to `vboOffsetNew` even though the application now considers `vboOffsetNew` to be the live attribute buffer. OpenGL's VAO state *captures the VBO that was bound at the time of `glVertexAttribPointer`*, so the draw call silently reads the stale buffer.

## Difficulty Rating
3/5

## Adversarial Principles
- state_leak
- stale_cached_binding
- attribute_identity_not_tracked
- framework_layer_caches_below_user_visible_api

## How OpenGPA Helps
`list_draw_calls` followed by an inspection of the draw's VAO attribute bindings exposes the concrete VBO id bound to attribute location 1. An agent comparing that id to the most-recently-created VBO (visible in the shim's buffer-creation trace) can immediately see that the draw is consuming an older buffer — the exact symptom the three.js maintainers spent a dozen comments localizing. Without OpenGPA, the JS-side `geometry.attributes.offset === newAttribute` check passes and the bug looks like a shader or data problem.

## Source
- **URL**: https://github.com/mrdoob/three.js/issues/30168
- **Type**: issue
- **Date**: 2024-12-19
- **Commit SHA**: (n/a — issue, not fix commit; fix PR to be resolved from upstream)
- **Attribution**: Reported by @Samsy; root cause localized by @RenaudRohlinger and @Samsy; corroborated by @Mugen87

## Upstream Snapshot
- **Repo**: https://github.com/mrdoob/three.js
- **SHA**: 3af500e84bcb7d78ea3e9b611c1e0c0a12afd3c0
- **Relevant Files**:
  - src/nodes/accessors/InstanceNode.js
  - src/renderers/common/nodes/NodeMaterialObserver.js
  - src/renderers/webgl/WebGLAttributes.js
  - src/core/BufferAttribute.js
  - src/core/InstancedBufferAttribute.js

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
    x: 60
    y: 255
    width: 1
    height: 1
  expected_rgba: [229, 51, 51, 255]
  tolerance: 40
  note: |
    Top-row sample: the first instance of the newly-assigned offset buffer
    should place a red quad at (-0.7, +0.7) NDC, covering pixel (60, 255).
    The stale-binding bug leaves this pixel at clear-black instead, while
    the symmetric bottom-row pixel (60, 45) lights up red from the
    previous, cached offset buffer.
```

## Predicted OpenGPA Helpfulness
- **Verdict**: yes
- **Reasoning**: The bug is purely about which VBO is bound to a vertex attribute at draw time. OpenGPA's Tier 1 raw-GL capture records per-draw VAO attribute bindings (VBO id, stride, offset) and buffer-creation history. An agent can diff "VBO bound to attribute 1" against "most recent VBO allocated by the app" and immediately flag the mismatch — a diagnosis that took upstream maintainers ~20 comments and three-way coordination to land on by reading code.

## Observed OpenGPA Helpfulness
- **Verdict**: ambiguous
- **Evidence**: validation skipped (--no-validate)
