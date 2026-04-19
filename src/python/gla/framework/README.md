# Framework Integration

Tier-3 framework integration layer for OpenGPA. Accepts scene graph metadata from engine-side plugins (Unity, Unreal, custom), builds a debug group tree, correlates high-level objects with raw draw calls, and exposes the result through `FrameworkQueryEngine`.

## Key Files
- `metadata_store.py` — persists per-frame metadata POSTed to `/frames/{id}/metadata`
- `tree_builder.py` — constructs the debug group hierarchy from metadata
- `correlation.py` — correlates framework objects to draw call indices
- `query_engine.py` — `FrameworkQueryEngine`: high-level queries over correlated data

## See Also
- `src/python/gla/api/README.md` — REST endpoint that accepts metadata
- `tests/unit/python/README.md` — tests covering this layer
