## User Report

## Your Environment

* Version used: current master branch

## Context

See upstream `3d-tiles-renderer` issue for context and reproduction https://github.com/NASA-AMMOS/3DTilesRendererJS/issues/1517.

## Steps to Reproduce
Reproduction in `3d-tiles-renderer`:
- https://nasa-ammos.github.io/3DTilesRendererJS/three/cesiumCompare.html?url=https://s3.eu-west-2.wasabisys.com/ems-sgct-photomaillage/ODACIT/EMS_PM2022/tileset.json
- https://nasa-ammos.github.io/3DTilesRendererJS/three/index.html#https://s3.eu-west-2.wasabisys.com/ems-sgct-photomaillage/ODACIT/EMS_PM2022/tileset.json

## Possible Cause/Fix/Solution
Possible fixes:
- Increase the size of the `3d-tiles-renderer` LRU caches to a reasonable size (would require some empirical testing) : https://github.com/iTowns/itowns/pull/2702#issuecomment-4074212177
- Preprocess the non-content tiles with children to set the `geometricError` matched their children for poorly structured datasets. In think, we shoul look to how Cesium handles such cases.

Note that this final fix could be a mix of those two fixes.

Closes #2755 (https://github.com/iTowns/itowns/pull/2755)

## Ground Truth

See fix at https://github.com/iTowns/itowns/pull/2702.

## Fix

```yaml
fix_pr_url: https://github.com/iTowns/itowns/pull/2702
fix_sha: c66b942f6363bd622b132fc168209269a1603fa2
bug_class: framework-internal
files:
  - config/prepare.mjs
  - package-lock.json
  - package.json
  - packages/Debug/package.json
  - packages/Debug/src/OGC3DTilesDebug.js
  - packages/Geographic/package.json
  - packages/Main/package.json
  - packages/Main/src/Layer/OGC3DTilesLayer.js
  - packages/Main/src/Parser/GeotiffParser.ts
  - packages/Main/src/Renderer/c3DEngine.js
  - webpack.config.cjs
```
