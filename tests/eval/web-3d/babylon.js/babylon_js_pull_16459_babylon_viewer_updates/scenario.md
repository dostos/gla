## User Report

Updates planned with the new [Babylon Viewer](https://babylonjs.com/viewer/):

- [x] Add shadow support - ([PR](https://github.com/BabylonJS/Babylon.js/pull/16459))
- [ ] lazy Load
- [ ] XR (incl. WebXR and QuickLook)
- [ ] Interaction Hints
- [ ] Render Graph support

## Ground Truth

See fix at https://github.com/BabylonJS/Babylon.js/pull/16459.

## Fix

```yaml
fix_pr_url: https://github.com/BabylonJS/Babylon.js/pull/16459
fix_sha: 99f2f4f024ea8154739f401118cb63750dddb5c8
bug_class: framework-internal
files:
  - package-lock.json
  - packages/public/@babylonjs/viewer/rollup.config.dist.esm.mjs
  - packages/public/@babylonjs/viewer/rollup.config.lib.mjs
  - packages/tools/viewer-configurator/package.json
  - packages/tools/viewer-configurator/src/components/configurator/configurator.tsx
  - packages/tools/viewer-configurator/tsconfig.build.json
  - packages/tools/viewer-configurator/tsconfig.json
  - packages/tools/viewer-configurator/webpack.config.js
  - packages/tools/viewer/rollup.config.common.mjs
  - packages/tools/viewer/src/Shaders/envShadowGround.fragment.fx
  - packages/tools/viewer/src/Shaders/envShadowGround.vertex.fx
  - packages/tools/viewer/src/ShadersWGSL/envShadowGround.fragment.fx
  - packages/tools/viewer/src/ShadersWGSL/envShadowGround.vertex.fx
  - packages/tools/viewer/src/viewer.ts
  - packages/tools/viewer/src/viewerElement.ts
  - packages/tools/viewer/src/viewerFactory.ts
```
