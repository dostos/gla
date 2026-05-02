## User Report

Currently it seems XR is not supported, see related issue here: https://github.com/pmndrs/react-xr/issues/205

Are there plans to support XR in the future?

## Ground Truth

See fix at https://github.com/mrdoob/three.js/pull/26160.

## Fix

```yaml
fix_pr_url: https://github.com/mrdoob/three.js/pull/26160
fix_sha: afdfa33b357027b3ad545b179ee8b8bb698a4889
bug_class: framework-internal
files:
  - src/renderers/WebGLRenderer.js
  - src/renderers/webxr/WebXRManager.js
```
