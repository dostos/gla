# R10: WebGPURenderer + NodeMaterial — instance matrices not applied across multiple InstancedMesh

## User Report
When creating multiple InstancedMesh objects (each with its own geometry
and material), only one mesh is visible in the scene. It looks like the
instance matrices are not being applied when there is more than one
InstancedMesh.

If instead I create a single InstancedMesh with multiple instances, then
all instance matrices are applied correctly and both objects render.

Reproduction: the code below creates two separate InstancedMesh (meshA
at x=-3 and meshB at x=+3), each with count=1. Only one cube is visible.
If I instead create a single InstancedMesh with count=2 and call
setMatrixAt(0, mA) / setMatrixAt(1, mB), both cubes render as expected.

```js
const geometryA = new THREE.BoxGeometry(1, 1, 1);
const materialA = new THREE.MeshStandardNodeMaterial();
const mA = new THREE.Matrix4().makeTranslation(-3, 0, 0);

const geometryB = new THREE.BoxGeometry(1, 1, 1);
const materialB = new THREE.MeshStandardNodeMaterial();
const mB = new THREE.Matrix4().makeTranslation(3, 0, 0);

const meshA = new THREE.InstancedMesh(geometryA, materialA, 1);
meshA.setMatrixAt(0, mA);
scene.add(meshA);

const meshB = new THREE.InstancedMesh(geometryB, materialB, 1);
meshB.setMatrixAt(0, mB);
scene.add(meshB);
// Only one object is visible.
```

Live example: https://jsfiddle.net/puLy06hc/3/
three.js version: ^0.179.1, Chrome on Linux, WebGPURenderer.

## Expected Correct Output
Two lit cubes are visible, one translated to x=-3 and one to x=+3, each
drawn via its own InstancedMesh with count=1 and a per-instance matrix
set via `setMatrixAt(0, m)`.

## Actual Broken Output
Only a single cube appears. The second InstancedMesh's draw either does
not contribute any visible fragments or is drawn at the origin / on top
of the first such that only one cube is distinguishable. Collapsing the
two InstancedMesh objects into one InstancedMesh with count=2 restores
the expected output, which localizes the regression to the
per-InstancedMesh instance-matrix binding path rather than to geometry
or lighting.

## Ground Truth
The authoritative root cause is not established in the upstream thread.
The reporter's bisection — "one InstancedMesh with count=2 works, two
InstancedMesh with count=1 each does not" — isolates the fault to the
path that binds per-instance matrix data when more than one
InstancedMesh uses the MeshStandardNodeMaterial codepath under
WebGPURenderer. The most likely region is the NodeMaterial
instance-matrix uniform/storage binding and its cache key (a stale or
shared binding could cause the second mesh's instanceMatrix to alias
the first, which would draw the second mesh's single instance at the
first mesh's translation and make it overlap the first cube).

> "It looks like the instance matrices are not being applied when there
> is more than one InstancedMesh."
> — reporter, https://github.com/mrdoob/three.js/issues/31776

No maintainer diagnosis, fix PR, or fix commit had been posted at draft
time; the issue URL above is the sole authoritative source. An agent
scoring this scenario should treat a diagnosis as correct if it
identifies (a) the WebGPURenderer + NodeMaterial instance-matrix
binding path as the suspect subsystem and (b) the fact that the bug
depends on having more than one InstancedMesh sharing this codepath.

## Difficulty Rating
4/5

## Adversarial Principles
- Cross-backend specificity: bug only appears under WebGPURenderer + NodeMaterial, not WebGLRenderer or classic MeshStandardMaterial.
- Symptom-obscures-cause: "only one mesh visible" invites wrong hypotheses (culling, depth, material, lighting) that are all red herrings.
- Multi-object interaction: bug requires N>=2 InstancedMesh to manifest; single-mesh repros pass.

## How OpenGPA Helps
A per-draw-call overview with bound uniform/storage buffers exposes
whether each InstancedMesh draw sees a distinct instanceMatrix buffer
binding or aliases a shared one. Comparing draw call 0 and draw call 1
on the `instanceMatrix` binding (buffer handle + offset + size) reveals
the binding collision without needing to inspect the NodeMaterial cache
logic directly.

## Source
- **URL**: https://github.com/mrdoob/three.js/issues/31776
- **Type**: issue
- **Date**: 2026-04-20
- **Commit SHA**: (n/a)
- **Attribution**: Reported at mrdoob/three.js#31776

## Upstream Snapshot
- **Repo**: https://github.com/mrdoob/three.js
- **SHA**: (auto-resolve from commit HEAD of issue #31776 date)
- **Relevant Files**:
  - src/renderers/webgpu/WebGPURenderer.js
  - src/renderers/common/Renderer.js
  - src/renderers/common/Bindings.js
  - src/materials/nodes/MeshStandardNodeMaterial.js
  - src/nodes/accessors/InstancedMeshNode.js
  - src/objects/InstancedMesh.js

## Tier
snapshot

## API
opengl

## Framework
none

## Bug Signature
```yaml
type: missing_draw_call
spec:
  expected_visible_objects: 2
  observed_visible_objects: 1
  trigger_condition: multiple_instanced_mesh_with_nodematerial
  backend: webgpu
```

## Predicted OpenGPA Helpfulness
- **Verdict**: ambiguous
- **Reasoning**: OpenGPA's value for this scenario depends on whether capture can observe WebGPU-side resource bindings per draw. The Tier 1 GL shim does not intercept WebGPU, so a useful signal requires either the WebGPU capture backend or the framework-sidecar (Tier 3) route where three.js posts its per-draw binding metadata. With that plumbing, OpenGPA clearly localizes the faulty binding; without it, an agent gets no more than what the issue already states.

## Observed OpenGPA Helpfulness
- **Verdict**: ambiguous
- **Evidence**: validation skipped (--no-validate)
