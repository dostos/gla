# R21_TILE_ID_5BIT_STENCIL_OVERFLOW: mapbox tile-id overflow at high zoom

## Metadata

- **Tier:** browser
- **API:** webgl
- **Framework:** mapbox-gl-js
- **Upstream:** https://github.com/mapbox/mapbox-gl-js/issues (pre-fix SHA pinned in Phase 2)
- **Phase 1 MVP:** pipeline-stub only. The real mapbox bundle lands in Phase 2.

## User Report

At very high zoom levels on a mapbox-gl-js map (roughly `zoom >= 24` at
the equator), tile outlines and per-tile masking go wrong — rendered
geometry from one tile leaks into another, and on some hardware entire
tiles are stenciled out. The map looks fine at moderate zoom. No console
errors; the problem only appears visually after zooming in past a
threshold. Reproduces on both Chrome and Firefox, both macOS and Linux.

## Ground Truth

mapbox-gl-js packs `(z, x, y)` tile identifiers into a 5-bit stencil
value. At very large zoom (`z > 2^5 - 1 = 31`), the `z` field wraps and
collides with lower-zoom tile IDs, so stencil masking mis-identifies
which tile owns which fragment. The practical cap is lower because the
stencil reference also encodes tile sub-ids.

The fix in mapbox is to widen the stencil packing (or cap render zoom
below the wrap point) and to assert at source time that the packed
value fits.

The query that a graphics debugger should enable:

> "What is the value of `map._transform._maxZoom` (and any stencil
> reference written via `glStencilFunc`) at the moment the symptom
> first appears?" — reverse-lookup via `gpa trace` maps the captured
> stencil reference back to `map._transform._maxZoom` in app state.

## How GPA Helps

`gpa trace value 31` (or whatever `stencilRef` the capture shows) should
return `map._transform._maxZoom`, confirming the bug site without
manual grepping through the minified mapbox bundle.

## Phase 1 vs Phase 2

Phase 1 (this scenario) validates the **pipeline end-to-end**: a browser
page POSTs a synthetic `sources` payload + sets `window.__gpa_done`, and
the `gpa run-browser` runner detects completion and tears down.

Phase 2 ships the real mapbox-gl-js bundle (pinned at a pre-fix SHA),
has the page zoom past 31, and lets the WebGL extension scanner produce
real sources. The ground-truth query above becomes resolvable live.

## Difficulty Rating

**Hard (4/5)**

The bug involves packed bits in a stencil buffer — a place almost no
framework user looks. Code review is no help; the cap lives deep in
library internals. The symptom (tile tearing at high zoom) is visually
obvious but the root cause is invisible without per-draw stencil state.
