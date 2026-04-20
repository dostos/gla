# `gpa trace` — Native (C/C++) Reflection via DWARF

**Date:** 2026-04-20
**Status:** design; not yet implemented
**Motivation:** `gpa trace` (browser side shipped in Phases 1–3) reflects into JS globals to surface app-level fields that equal a captured GL value. Native OpenGL apps under `LD_PRELOAD` have no JS runtime. Without a native path, `gpa trace` only helps browser-hosted workloads — a large swath of graphics apps (Godot standalone, Unreal standalone, Blender, desktop CAD) stay uncovered. This spec pins the native side using DWARF debug info.

## Two phases

### Phase 1 — Globals + static variables (option #3 in our discussion)

Parse the shim-loaded process's DWARF once (at shim init, post-engine-connect), build `{name, address, type, size}` table for all globals/statics across all loaded modules. On each `glUniform*` / `glBindTexture` (gated mode), walk the table, hash values, POST to `/sources` — same payload shape as the JS scanner.

**Coverage:** anything addressable at a fixed location — globals, file-scoped statics, singletons, class-level static members. Not heap state, not stack locals, not HashMap entries.

**Engineering:** moderate. Ship target: 1–2 days.

### Phase 2 — Stack locals (option #2)

At each glUniform*/glBindTexture call, walk the stack with libunwind. For each frame, look up the function's DIE in DWARF, enumerate `DW_TAG_variable` + `DW_TAG_formal_parameter` children, evaluate their DWARF location expressions against the current register state + frame pointer to extract values. Hash + POST same payload.

**Coverage:** live local variables at each call site. Complements Phase 1 — globals answer "where is this value stored app-wide"; locals answer "what values existed in the code path that produced this GL call."

**Engineering:** larger. DWARF location-expression interpreter subset; libunwind integration; per-frame PC→DIE lookup. Ship target: 3–5 days.

## Goals

- **No user instrumentation required** (complement the `gpa_trace_mark()` SDK direction, which is opt-in).
- **Pay for debug info, but not for modified code.** App just needs to be compiled with `-g` (most projects do by default in dev builds).
- **Same POST shape + same query surface as JS scanner.** REST / CLI / MCP are unchanged.
- **Sub-2ms overhead per hooked call.** Otherwise agents see distorted telemetry.

## Non-goals

- Release-binary reflection without symbols. Stripped binaries → feature unavailable; log & move on.
- ASLR / PIE address resolution via ptrace. In-process `dl_iterate_phdr` is sufficient.
- Template instantiation enumeration beyond what DWARF describes.
- `gpa trace` coverage of Rust / Go — both produce DWARF but their type encodings differ; defer.
- Phase-2 concurrent stack walks on multiple threads. Single-threaded GL is the norm; log a warning if another thread's calling GL simultaneously and skip.

## Architecture

```
 at shim init                             per glUniform* / glBindTexture (gated)
+---------------------+                  +------------------------------------+
| dl_iterate_phdr     |                  |  libunwind → frame chain           |
| enumerate modules   |                  |  per frame:                        |
|                     |                  |    resolve PC → DIE                |
| for each module:    |                  |    walk DW_TAG_variable children   |
|   parse DWARF       |                  |    eval DW_AT_location → address   |
|   build globals tbl |                  |    read memory → value             |
+----------+----------+                  |    hash → value_index              |
           |                             +-----------------+------------------+
           v                                               |
   +--------------+                                        |
   | globals map  | <-- combine paths ---------------------+
   | {path:addr}  |                                        |
   +--------------+                                        v
                                           POST /frames/{id}/drawcalls/{dc}/sources
                                           (same shape as the JS scanner)
```

## Data model

Payload POSTed to the existing `TraceStore` endpoint is **identical** to the JS scanner's. The only new field is `"origin": "dwarf-globals" | "dwarf-locals" | "js-reflection"` so query-side can filter.

```json
{
  "frame_id": 2, "dc_id": 3,
  "sources": {
    "roots": ["globals", "locals@main+0x42"],
    "mode": "gated",
    "origin": "dwarf-globals",
    "value_index": {
      "<hash(16.58)>": [
        {"path": "g_config.brightness", "type": "double", "confidence": "high"}
      ]
    }
  }
}
```

## Dependency choices

Two paths for DWARF parsing. Pick ONE in Phase 1:

**A. `libdw` / `libdwfl` (elfutils).** Mature, battle-tested, handles all DWARF-5 features. Debian/Ubuntu: `apt install libdw-dev`. Bazel dep: `http_archive` elfutils or use a system-library rule.

**B. Hand-rolled minimal DWARF parser.** `.debug_info` + `.debug_abbrev` + `.debug_str` are enough for Phase 1 (no expression interpreter needed — globals have static addresses). ~500 lines of C. No new deps. Full control over performance.

Recommendation for Phase 1: **B** (hand-rolled). Ship velocity + deterministic bazel build matters more than DWARF-5 feature completeness for this use case. Accepts DWARF 3/4 only; reject 5 with a clear error. Phase 2 (locations need expression interpretation) → reconsider libdw.

Stack walking in Phase 2: **libunwind** (also `apt install libunwind-dev`). No hand-roll alternative worth the effort.

## Shim integration

### Init-time scan (Phase 1)

Add a `gpa_native_trace_init()` called at the end of `gpa_init()` in `src/shims/gl/gpa_init.c`:

1. Gated on env `GPA_TRACE_MODE` being set (`gated|lazy|eager`)
2. `dl_iterate_phdr()` → for each module: open, mmap, parse DWARF → accumulate globals
3. Filter by path: exclude system libs (`ld-linux`, `libc`, `libm`, `libgl`, etc.); exclude any paths matching the existing secret regex
4. Store `{path, address, size, dwarf_type_encoding}` in a shim-scoped global table (thread-safe read via `pthread_rwlock`)
5. Log stats to `engine.log`: `native trace: scanned 3 modules, 847 globals (6.2 MB of DWARF parsed in 43 ms)`

### Per-call scan (Phase 1)

In the gated GL wrappers (`glUniform*`, `glBindTexture`):

1. Grab current `frame_id`, `dc_id` from shim state
2. Walk the globals table, dereferencing each address
3. Extract value by `dwarf_type_encoding` (signed int, float, double, struct primitives)
4. Compute the same hash as the JS scanner uses (`djb2` of canonical string repr)
5. Accumulate `value_index`
6. POST to `http://127.0.0.1:<engine-port>/api/v1/frames/{frame_id}/drawcalls/{dc_id}/sources` using the existing shim HTTP client

Budget guards: 2 ms per call; truncate + `"truncated": true` flag if exceeded; shrink scan set for next call.

### Configuration

Extend existing env vars:

- `GPA_TRACE_MODE=gated|lazy|eager|off` (existing; `off` disables)
- `GPA_TRACE_NATIVE=1` — opt-in master switch (off by default for perf safety)
- `GPA_TRACE_NATIVE_ROOTS=module1.so,module2` — restrict scan to these modules
- `GPA_TRACE_NATIVE_EXCLUDE=/usr/lib/**` — glob paths to skip

## Query surface

**Unchanged.** CLI, REST, MCP all work against the same `TraceStore` regardless of origin. The only addition is filtering:

```
gpa trace value 16.58 --origin dwarf-globals     # filter to native globals
gpa trace value 16.58 --origin js-reflection     # browser-side only
gpa trace value 16.58                            # all origins (default)
```

## Phase 1 implementation plan

Files to create:

- `src/shims/gl/native_trace.h` — public API (`gpa_native_trace_init`, `gpa_native_trace_scan`, `gpa_native_trace_shutdown`)
- `src/shims/gl/native_trace.c` — `dl_iterate_phdr` + DWARF parser
- `src/shims/gl/dwarf_parser.c` — hand-rolled DWARF walker (if going option B)
- `src/shims/gl/dwarf_parser.h`
- `src/shims/gl/BUILD.bazel` — wire new files; `linkopts=["-ldl"]`
- `tests/unit/shims/test_native_trace.c` — unit tests against a fixture binary built with `-g`

Integration:
- `src/shims/gl/gl_wrappers.c` — on `glUniform*` + `glBindTexture` (gated path), call `gpa_native_trace_scan(frame_id, dc_id)` which does the scan + POST
- `src/shims/gl/gpa_init.c` — call `gpa_native_trace_init()` at end of `gpa_init()`

Tests to add:

- Fixture: `tests/unit/shims/fixtures/trace_fixture.c` — a tiny program with known globals (e.g. `static double g_test_val = 16.58;`)
- `test_dwarf_parser_reads_globals` — compile fixture with `-g`, parse, assert `g_test_val` present at correct address
- `test_dwarf_parser_rejects_dwarf5` — dwarf-5-encoded input → clear error
- `test_scan_hashes_values` — walk table, hash, compare to expected djb2 hash
- `test_scan_excludes_system_libs` — `libc.so.6` not scanned
- `test_scan_respects_budget` — force budget exhaustion → `truncated: true` flag set

## Phase 2 implementation plan (sketch)

Files to create:
- `src/shims/gl/stack_trace.h` / `.c` — libunwind wrapper
- `src/shims/gl/dwarf_locations.c` — DWARF expression interpreter (DW_OP_reg*, DW_OP_fbreg, DW_OP_addr, DW_OP_plus_uconst, DW_OP_piece; bail on unsupported)

Integration:
- `src/shims/gl/gl_wrappers.c` — on gated path, ALSO call `gpa_native_trace_scan_stack()` which walks frames and POSTs `origin: "dwarf-locals"` payload

Tests: fixture binary with function-local variables at known stack offsets; assert extraction works for each calling convention we care about (x86-64 System V primary target).

## Open questions

1. **Bazel builds shim with `-g` by default?** Need to check. If not, add `copts=["-g"]` for the shim itself + note that target binaries (`tests/eval/*`) need `-g` for native trace to work. Test targets built via `cc_binary` typically inherit `-g` in debug mode.
2. **Phase 1 ABI compat with Phase 2?** Phase 1's payload is a subset of Phase 2's. No breaking changes expected; Phase 2 just adds more entries.
3. **Thread safety.** Pthread rwlock for the globals table is enough for Phase 1. Phase 2's stack walk needs per-thread unwind contexts.
4. **Inlined functions.** Phase 2's stack walk may see logical frames the hardware has inlined away. DWARF has `DW_TAG_inlined_subroutine` — can we recover these? Nice-to-have; punt from Phase 2 MVP.
5. **Stripped binaries** — graceful degradation: log `[native-trace] no DWARF in /usr/bin/app — trace disabled for this module` rather than crashing.
6. **Static link vs dynamic link** — for statically-linked binaries, `dl_iterate_phdr` returns just the one module. DWARF is all in the main binary; simpler case. Handled same as multi-module.

## Success criteria

After Phase 1 ships:

- Running `gpa run -- bazel-bin/tests/eval/<scenario>` with `GPA_TRACE_NATIVE=1` produces `origin: "dwarf-globals"` entries in `TraceStore`
- `gpa trace value <literal>` returns candidates sourced from native globals
- Overhead on a typical frame ≤ 5% relative to trace disabled
- Full Python + C++ test suites stay green

After Phase 2 ships:

- Stack locals appear as `origin: "dwarf-locals"` entries
- Round 10 (or wherever) shows measurable solvability lift on source-logical C-repro scenarios (r21-native-port equivalent)
