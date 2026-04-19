# Core Unit Tests

Google Test suite for OpenGPA's C++ core engine. Tests are hermetic (no GPU required) and cover the full engine stack from IPC primitives to query results.

## Coverage
- Shared memory ring buffer (enqueue, wrap-around, concurrent producer/consumer)
- Control socket (command parsing, error paths)
- Frame store (insert, evict, lookup)
- Normalizer (format conversion, edge cases)
- Query engine (filter, aggregate, diff)
- Engine integration (start/stop, multi-frame round-trip)

## See Also
- `src/core/README.md` — code under test
- `tests/unit/shims/README.md` — separate C unit tests for the GL shim
