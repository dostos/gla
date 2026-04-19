# Python Tests

pytest suite for OpenGPA's Python layer. All tests run without a live GPU; the native backend is replaced by a fixture that returns synthetic frame data.

## Coverage
- REST API endpoints (frame, draw call, pixel, scene routes)
- `NativeBackend` and `RenderDocBackend` contract
- Metadata store persistence and retrieval
- Correlation engine (framework object to draw call mapping)
- `FrameworkQueryEngine` query correctness
- Eval harness (scenario loading, scoring, report generation)

## See Also
- `src/python/gla/README.md` — package under test
- `tests/unit/core/README.md` — C++ unit tests for the engine layer
