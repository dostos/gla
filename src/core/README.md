# Core Engine

C++ core engine for OpenGPA. Receives frame captures from shims over shared memory and Unix sockets, stores and normalizes the data, and answers structured queries from the Python layer.

## Key Subdirectories
- `ipc/` — shared memory ring buffer and control socket server
- `store/` — frame and draw-call storage, keyed by frame ID
- `normalize/` — data normalization (unit conversion, format canonicalization)
- `query/` — query engine used by the Python bindings

## See Also
- `src/bindings/README.md` — pybind11 wrapper around this engine
- `schemas/README.md` — FlatBuffers IPC schema
- `tests/unit/core/README.md` — unit tests for this layer
