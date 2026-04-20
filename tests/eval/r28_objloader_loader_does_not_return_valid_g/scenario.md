# R28: OBJLoader produces geometry with mismatched attribute counts

## User Report
If the OBJ file specifies face indices inconsistently then the loader will return geometry with mismatched attribute lengths. I ran into this issue while loading an OBJ file I'm working with and it causes the geometry to not render. Unfortunately I can't share the model but I'll try to give a rough example of what's happening.

The OBJ face list might be formed like so. Notice that one face does _not_ specify normals while the other faces do:

```
f 1050//4 1051//5 1049//6
f 185//7 183//8 179//9
f 500 505 1053
f 732//10 500//11 1053//12
f 153//13 144//14 137//15
```

This will result in a position attribute with a count of `15` and a normal array with a count of `12`, meaning the geometry will fail to render (and the normals and positions are now misaligned in their respective arrays). The problematic logic seems to be in [the `addFace` function](https://github.com/mrdoob/three.js/blob/dev/examples/js/loaders/OBJLoader.js#L279), which just ignores an empty normal value even if they're defined in sibling faces. You can see that this will also be a problem for UVs, as well.

The problem is not present in `OBJLoader2` and a mesh formed like this loads just fine in MeshLab, as well.

## Expected Correct Output
Five evenly spaced, consistently lit triangles across the horizontal centre of the viewport. With a +Z light and +Z face normals each sample at y=300 should report a fully-lit RGB near (240, 240, 240).

## Actual Broken Output
The first four triangles render at the expected lit colour. The fifth (rightmost) triangle reads its per-vertex normals from past the end of the bound normal buffer; depending on driver behaviour the resulting fragments are either dark/black (zeros fetched) or contain stale memory garbage with arbitrary shading.

## Ground Truth
The OBJ loader populates a `position` BufferAttribute and a `normal` BufferAttribute in lockstep per face vertex, but [the `addFace` function](https://github.com/mrdoob/three.js/blob/dev/examples/js/loaders/OBJLoader.js#L279) only appends to the normal buffer when the source face actually carries normal indices. Faces that omit `//n` after the position index leave the normal attribute short. The output `BufferGeometry` therefore has `position.count === 15` and `normal.count === 12`, which is structurally invalid: every vertex attribute in a non-indexed draw must have the same count, otherwise the GPU reads past the shorter buffer.

> This will result in a position attribute with a count of 15 and a normal array with a count of 12, meaning the geometry will fail to render (and the normals and positions are now misaligned in their respective arrays).

The fix discussed in the thread is to either synthesise per-face normals (matching the loader's existing behaviour for groups with no normals at all — see the `generate face normals` path linked from the comment thread) or default missing UVs to `(0, 0)`, so every attribute ends with the same vertex count as positions.

## Difficulty Rating
3/5

## Adversarial Principles
- Silent vertex-attribute buffer length mismatch (no GL error)
- Diagnosis requires cross-referencing two attribute bindings, not inspecting any single draw-call argument
- Driver-dependent symptom: undefined behaviour when fetching past the end of an attribute buffer

## How OpenGPA Helps
Inspecting the bound vertex attributes for the offending draw call exposes the position VBO at 180 bytes (15 vec3s) and the normal VBO at 144 bytes (12 vec3s). Cross-referencing buffer size against `glDrawArrays(count=15)` makes the off-by-3-vertex shortfall on the normal stream immediately visible — a comparison no single GL error path surfaces on its own.

## Source
- **URL**: https://github.com/mrdoob/three.js/issues/16211
- **Type**: issue
- **Date**: 2019-04-08
- **Commit SHA**: (n/a)
- **Attribution**: Reported by @gkjohnson

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
  draw_index: 0
  expectation: vertex_attribute_buffer_sizes_consistent
  attributes:
    - location: 0
      vertex_count: 15
    - location: 1
      vertex_count: 12
```

## Predicted OpenGPA Helpfulness
- **Verdict**: yes
- **Reasoning**: The root cause is purely a mismatch between two pieces of structured GL state (attribute buffer sizes vs draw count). OpenGPA's per-draw attribute/buffer dump surfaces both numbers side by side; without it, the agent must either reason about the OBJ source or notice the count discrepancy in the loader's output, neither of which is observable from rendered pixels alone.

## Observed OpenGPA Helpfulness
- **Verdict**: ambiguous
- **Evidence**: validation skipped (--no-validate)
