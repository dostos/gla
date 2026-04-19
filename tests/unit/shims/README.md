# Shim Unit Tests

C unit tests for OpenGPA's GL shadow state tracker. Uses `assert()` and a `main()` entry point rather than a test framework, keeping the tests buildable without any external dependencies.

## Coverage
- Texture binding / unbinding across units
- VAO bind state
- Program and uniform tracking
- FBO attachment state
- State isolation between `glPushAttrib` / `glPopAttrib` equivalents

## See Also
- `src/shims/gl/README.md` — shadow state implementation under test
- `tests/unit/core/README.md` — gtest-based tests for the engine layer
