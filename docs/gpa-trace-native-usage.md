# `gpa trace` — Native (OpenGL LD_PRELOAD) Usage

Phase 1 ships DWARF-based globals/statics reflection in the OpenGL shim.
Same `TraceStore` endpoint and same query surface as the browser JS
scanner; the only new field in the POST payload is `"origin":
"dwarf-globals"`.

## Prerequisites

- Target binary compiled with `-g` (DWARF 3 or 4). DWARF 5 is rejected at
  parse time with a clear log message.
- Engine running on `127.0.0.1:18080` (overridable via `GPA_TRACE_HOST` +
  `GPA_TRACE_PORT`).
- Bearer token set via `GPA_TOKEN` if the engine requires auth.

## Enable at runtime

```bash
# Build the shim.
bazel build //src/shims/gl:gpa_gl

# Build the scenario. As of `tests/eval/BUILD.bazel` every eval
# `cc_binary` carries `copts = ["-g", "-gdwarf-4",
# "-fno-omit-frame-pointer", "-O0"]`, so the object files always have
# DWARF 4. You MUST pass `--strip=never` on the build command so Bazel
# does not strip `.debug_info` out of the linked binary (fastbuild
# strips by default). `--compilation_mode=dbg` also works but is
# heavier; `--strip=never` is sufficient and is the recommended
# invocation for running native trace against eval targets.
bazel build --strip=never //tests/eval/e5_uniform_collision

# Run with native trace enabled.
GPA_TRACE_NATIVE=1 \
  LD_PRELOAD=bazel-bin/src/shims/gl/libgpa_gl.so \
  GPA_SOCKET_PATH=/tmp/gpa.sock GPA_SHM_NAME=/gpa \
  GPA_TOKEN=TOKEN \
  bazel-bin/tests/eval/e5_uniform_collision

# Query — same CLI surface as the browser path. `bin/gpa` autodetects the
# bazel-built Python 3.11 + _gpa_core.so; no manual PYTHONPATH/GPA_PYTHON
# setup required once you've run `bazel build //src/bindings:_gpa_core.so`.
bin/gpa trace value 100.0 --origin dwarf-globals
```

At shim init you'll see a stderr line such as:
```
[OpenGPA] native-trace: scanned 1 modules, 12 globals (4 ms)
```

## Tuning

| Env var             | Default         | Purpose                                 |
|---------------------|-----------------|-----------------------------------------|
| `GPA_TRACE_NATIVE`  | unset (off)     | Master switch — must be `1` to enable.  |
| `GPA_TRACE_HOST`    | `127.0.0.1`     | Engine REST host.                       |
| `GPA_TRACE_PORT`    | `18080`         | Engine REST port.                       |
| `GPA_TOKEN`         | unset           | Sent as `Authorization: Bearer <tok>`.  |

## Known limits (Phase 1)

- Globals and statics only. Stack locals land in Phase 2.
- DWARF 3 and 4 only. DWARF 5 modules are skipped with a log message.
- Budget guard: 2 ms wall-clock per scan. On overrun, `"truncated":
  true` is set and the scan set shrinks for the next call.
- System libraries (`libc`, `libm`, `libGL`, etc.) are excluded — their
  globals aren't interesting and DWARF for them is usually absent.
- Only DWARF base-types (int, float, double, char, bool). Aggregates
  and pointers are recorded with byte_size but not hashed in this
  phase.
- **Architecture:** the Phase 2 stack-local scanner
  (`GPA_TRACE_NATIVE_STACK=1`) is x86_64 System V only. On other
  architectures the walker is compiled as a no-op and logs
  `[OpenGPA] native-trace: stack trace unavailable on this architecture
  (x86_64 only)` once at the first scan. Globals-only (Phase 1) tracing
  is arch-neutral and still works.

## Smoke check

```bash
# Expect: a hash entry pointing at g_public_double whenever the app
# calls glUniform*(..., 100.0).
GPA_TRACE_NATIVE=1 gpa run -- bazel-bin/tests/eval/e5_uniform_collision
gpa trace value 100.0 --origin dwarf-globals
```
