# R25: Translucent material rendered without GL_BLEND ("disparition")

## User Report
I'm new to threejs and I'm trying to make a simple 3d model.

Nevertheless, I've got some transparency / disparition issue since I've
started to play with opacity.

The important part of my code is here:

```js
var cylJaun = new THREE.MeshNormalMaterial({color: 0xFFFF00, opacity: 1});
var cylBleu = new THREE.MeshNormalMaterial({color: 0x0000FF, opacity: 0.5 });

var cylJaun1 = new THREE.Mesh(new THREE.CylinderGeometry(50,50,50,100,1,false),cylJaun);
var cylJaun2 = new THREE.Mesh(new THREE.CylinderGeometry(50,50,50,100,1,false),cylJaun);
var cylJaun3 = new THREE.Mesh(new THREE.CylinderGeometry(50,50,50,100,1,false),cylJaun);

var cylBleu1 = new THREE.Mesh(new THREE.CylinderGeometry(70,70,200,100,1,false),cylBleu);

cylJaun1.position.y -= 60;
cylJaun3.position.y += 60;

group.add(cylBleu1);
group.add(cylJaun1);
group.add(cylJaun2);
group.add(cylJaun3);

scene.add(group);
```

As you can see, I try to put 3 cylinders into a fourth. The problem is that
some of those 3 cylinders disappear when my object is rotated within a
specific range.

## Expected Correct Output
The blue outer quad should be partially see-through. Where it overlaps the
yellow inner quad we should see a blended greenish color
(roughly `(0.5, 0.5, 0.5, 1)` for `srcAlpha, 1-srcAlpha` blend over
yellow), not solid blue.

## Actual Broken Output
The blue outer quad is solid opaque blue. The yellow quad behind it is
entirely occluded inside the overlap region — it "disappears."

## Ground Truth
The accepted answer on the SO thread states the cause directly:

> You need to set `transparent: true` in the material for the larger cylinder.
> `var cylBleu = new THREE.MeshNormalMaterial( { transparent: true, opacity: 0.5 } );`

In three.js (and most engines that follow the same pattern), setting
`opacity` does not by itself enable alpha blending; the renderer only
toggles `GL_BLEND` for objects whose material is marked `transparent`.
Without that flag, the draw is sorted into the opaque pass and submitted
with blending disabled, so the fragment alpha of 0.5 is silently
discarded and the fragment writes opaquely (also writing depth, which
then occludes anything drawn after it that is farther away — or, as in
the user's scene, anything drawn before it that the depth test hides).

## Difficulty Rating
2/5

## Adversarial Principles
- silent-state-mismatch (uniform alpha < 1 while GL_BLEND disabled)
- two-flag-coupling (one of two related flags set, the other not)
- intent-vs-state-divergence (author intent: translucent; GL state: opaque)

## How OpenGPA Helps
A draw-call inspection on the outer quad surfaces both the per-fragment
color (`uColor.a = 0.5`) and the pipeline state at draw time
(`GL_BLEND = GL_FALSE`). Pairing those two facts immediately flags the
mismatch — the agent can answer "the material wanted alpha but the draw
was submitted opaque" without needing to interpret framework code.

## Source
- **URL**: https://stackoverflow.com/questions/13888561/three-js-transparency-disparition
- **Type**: stackoverflow
- **Date**: 2012-12-15
- **Commit SHA**: (n/a)
- **Attribution**: Asked by SO user; answer by WestLangley (three.js maintainer)

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
  draw_call_selector:
    uniform_name: uColor
    uniform_component: a
    uniform_value_lt: 1.0
  required_state:
    GL_BLEND: GL_TRUE
  violation: "Draw call writes a fragment color with alpha < 1.0 while GL_BLEND is disabled; the alpha is silently dropped and the fragment occludes geometry behind it."
```

## Predicted OpenGPA Helpfulness
- **Verdict**: yes
- **Reasoning**: This is exactly the kind of bug Tier-1 raw capture is built
  to surface. Both halves of the contradiction — the uniform value and the
  per-draw blend state — are first-class fields in `NormalizedDrawCall`,
  so a single `get_draw_call` query exposes the inconsistency without any
  framework knowledge. An agent without OpenGPA must either reason about
  three.js's internal pass-sorting rules or guess from screenshots.

## Observed OpenGPA Helpfulness
- **Verdict**: ambiguous
- **Evidence**: validation skipped (--no-validate)
