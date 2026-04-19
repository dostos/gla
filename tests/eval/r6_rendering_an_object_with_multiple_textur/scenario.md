# R6: copyTextureToTexture writes to wrong texture after multi-texture render

## User Report
### Description

When rendering objects with multiple textures (thus using several texture slots) and the `renderer.copyTextureToTexture` function, the target texture in the `copyTextureToTexture` call actually references *the last texture bound in slot0* from a previous render call.

In other words: It ignores the input texture, and targets a previous, wrong one.

This also causes some more errors later, as the wrong texture gets unbound after the copy.

### Reproduction steps

1. Render an object with two textures, texture1 and texture2
2. Then upload some more subparts into texture1 using copyTextureToTexture: `renderer.copyTextureToTexture(uv, someMoreData, texture1)`
3. The data from someMoreData actually goes to texture2 (!)
4. Subsequent calls to `renderer.copyTextureToTexture(uv, someMoreData, texture1)` complains that there is no texture bound.

### Code

```js
import * as THREE from 'three';

const scene = new THREE.Scene();
const camera = new THREE.PerspectiveCamera( 75, window.innerWidth / window.innerHeight, 0.1, 1000 );
camera.position.z = 2;
scene.add(camera);

scene.add(new THREE.AmbientLight(0xffffff));

const renderer = new THREE.WebGL1Renderer();
renderer.setSize( window.innerWidth, window.innerHeight );
document.body.appendChild( renderer.domElement );

function makeColoredTexture(color, width, height) {
  const canvas = document.createElement('canvas');
  canvas.width = width;
  canvas.height = height;
  const context = canvas.getContext( '2d' );
  context.fillStyle = color;
  context.fillRect( 0, 0, width, height );
  return new THREE.CanvasTexture(canvas);
}

const redTexture = makeColoredTexture('rgba(255, 0, 0, 1.0)', 1024, 1024);
const greenTexture = makeColoredTexture('rgba(0, 255, 0, 1.0)', 1024, 1024);
const blueTexture = makeColoredTexture('rgba(0, 0, 255, 1.0)', 128, 128);

const mesh = new THREE.Mesh(new THREE.BoxGeometry(), new THREE.ShaderMaterial({
  uniforms: {
    map1: { value: redTexture },
    map2: { value: greenTexture }, // Bug only happens with more than one texture
  },
  vertexShader: document.getElementById( 'vertexShader' ).textContent,
  fragmentShader: document.getElementById( 'fragmentShader' ).textContent
}));
mesh.material.uniformsNeedUpdate = true;
scene.add(mesh);

// After this render call, the currently active slot is slot1 and bound texture is `greenTexture`
renderer.render(scene, camera);
scene.remove(mesh);

// The first setTexture2d in this copy call sees that slot0 already has
// the required texture, so it chooses not to bind.
// But the active texture is slot 1 with `greenTexture`, so this uses the wrong texture...
renderer.copyTextureToTexture(new THREE.Vector2(448, 448), blueTexture, redTexture);

//... so `blueTexture` got written to `greenTexture`! Let's confirm:
// If the bug is present, there will be a blue square on the green cube
// instead of the red cube
const redMesh = new THREE.Mesh(new THREE.BoxGeometry(), new THREE.MeshBasicMaterial({map: redTexture}));
redMesh.position.y += 0.5;
scene.add(redMesh);

const greenMesh = new THREE.Mesh(new THREE.BoxGeometry(), new THREE.MeshBasicMaterial({map: greenTexture}));
greenMesh.position.y -= 0.5;
scene.add(greenMesh);
renderer.render(scene, camera);
```

### Debug notes
From what I can tell, this seems to be the part where it gets a bit confused (this is in `setTexture2D`, in  `copyTextureToTexture`):

It seems like it needs to call this activeTexture/bindTexture, but skips it because it sees slot0 had this texture in currentBoundTextures? Unclear to me if it should be fixed here, or if it's the render() call that should have been cleaning up something more.

### Live example
The blue square should have been uploaded to the red texture, but was clearly uploaded to the green texture:
* [jsfiddle-latest-release](https://jsfiddle.net/15znhrcy/)
* [jsfiddle-dev](https://jsfiddle.net/kLsohrb0/)

### Version

r146-r150

### Device

Desktop, Phone

### Browser

Chrome, Edge, Firefox, Safari

### OS

OS X, Windows, iOS

## Expected Correct Output
Left half of the framebuffer (the redTex preview): solid red with a 16x16
blue patch near the center.
Right half (the greenTex preview): solid green, no blue patch.

## Actual Broken Output
Left half: solid red, no blue patch.
Right half: solid green with a 16x16 blue patch near the center — the upload
went to the wrong texture.

## Ground Truth
After rendering a draw call that binds two textures (one per texture unit),
a follow-up `glTexSubImage2D` upload intended for the texture on unit 0
silently writes to the texture on unit 1 instead. The renderer's bind-cache
believes slot 0 already holds the target texture so it elides the
`glActiveTexture(GL_TEXTURE0)` + `glBindTexture` pair preceding the upload,
but the GL active-texture-unit cursor is still pointing at unit 1 from the
end of the previous render.

Three.js's `WebGLTextures.setTexture2D` short-circuits the bind sequence
when its `currentBoundTextures` cache reports that the requested texture is
already bound to the slot it last saw — but the cache is keyed per-slot
without re-asserting `glActiveTexture`, so any path that leaves the active
unit cursor pointing at a different slot than the one being cached will
upload through the wrong unit. The reporter pins this down precisely:

> The first setTexture2d in this copy call sees that slot0 already has
> the required texture, so it chooses not to bind. But the active texture
> is slot 1 with `greenTexture`, so this uses the wrong texture...

A later comment in the same thread observes that `WebGLRenderer.render()`
never tears down its texture bindings, which is what leaves the cache and
the active-unit cursor in an inconsistent state across the render →
copyTextureToTexture → render sequence:

> there are two textures still in it from the WebGLRenderer.render() call.
> I can't find any place in the code where the render() call cleans up
> bound textures

The fix landed in the project's WebGLTextures bind path (mrdoob/three.js
issue #25618); the minimal repro here ports the *pattern* — leave the
active unit at slot 1, then issue a `glTexSubImage2D` without first
re-asserting the bind on slot 0 — into raw GL.

## Difficulty Rating
4/5

## Adversarial Principles
- bind-cache vs. active-unit desync
- missing precondition (glActiveTexture not re-asserted before bind shortcut)
- side effect on adjacent state (upload silently retargets to a sibling
  texture object instead of erroring)

## How OpenGPA Helps
Querying the per-call snapshot for the `glTexSubImage2D` reveals the
bound `GL_TEXTURE_2D` object on the *active* texture unit at call time —
which is the greenTex name, not the redTex name the application thought
it was uploading to. A trace of `glActiveTexture` / `glBindTexture` across
the preceding draw makes the missing rebind self-evident.

## Source
- **URL**: https://github.com/mrdoob/three.js/issues/25618
- **Type**: issue
- **Date**: 2023-03-03
- **Commit SHA**: (n/a)
- **Attribution**: Reported by @ulrikdamm; root-cause diagnosis in the
  reporter's debug notes and corroborated by @epreston in the same thread.

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
    # Right half of the 512x256 framebuffer (the greenTex preview).
    # The blue 16x16 patch lands near the center because the texture
    # samples cover [0,1] and the patch was uploaded at (24,24)-(40,40)
    # of a 64x64 source.
    x: 320
    y: 80
    w: 64
    h: 64
  forbidden_color:
    r: 0
    g: 0
    b: 255
    tolerance: 32
  reason: >
    The blue patch must not appear in the right half of the framebuffer.
    Right half samples greenTex; if blue pixels are present there, the
    glTexSubImage2D upload was retargeted to greenTex instead of redTex.
```

## Predicted OpenGPA Helpfulness
- **Verdict**: yes
- **Reasoning**: The bug is invisible at the framework layer (the JS code
  passes the correct texture handle into copyTextureToTexture) but is
  trivially visible in the raw GL trace: there is no glBindTexture between
  the last per-unit bind of phase 1 and the glTexSubImage2D in phase 2,
  and the active unit at upload time is GL_TEXTURE1 rather than the
  expected GL_TEXTURE0. OpenGPA's per-draw snapshot of the active texture
  unit + bound texture name on each unit is exactly the signal needed to
  attribute the upload to the wrong object.

## Observed OpenGPA Helpfulness
- **Verdict**: ambiguous
- **Evidence**: validation skipped (--no-validate)
