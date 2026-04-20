# r21_tile_id_overflow — Phase 1 MVP stub

This scenario exists to validate the `gpa run-browser` pipeline
end-to-end. The `index.html` posts a synthetic `sources` payload to the
engine and sets `window.__gpa_done = true`; it does **not** load the
real `mapbox-gl-js` bundle yet.

Phase 2 replaces `index.html` with a real mapbox render that trips the
5-bit stencil-tile-id overflow at high zoom, with the WebGL extension
scanner producing the `sources` payload automatically. See
`scenario.md` for the bug write-up and the target agent query.
