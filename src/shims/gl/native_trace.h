#ifndef GPA_NATIVE_TRACE_H
#define GPA_NATIVE_TRACE_H

/* Phase 1 of `gpa trace` native side: DWARF-based globals scanner.
 *
 * Lifecycle:
 *   gpa_native_trace_init()     — called at end of gpa_init(). Checks
 *                                 GPA_TRACE_NATIVE env; iff "1", walks
 *                                 dl_iterate_phdr, parses DWARF from each
 *                                 non-system module, builds the globals
 *                                 table.
 *   gpa_native_trace_scan(f,d)  — called from the gated glUniform* /
 *                                 glBindTexture paths. No-op unless enabled.
 *                                 Walks the globals table, hashes values,
 *                                 POSTs to the engine REST API.
 *   gpa_native_trace_shutdown() — releases memory (optional; process exit
 *                                 reclaims anyway).
 *
 * Fail-open: every failure path just disables the feature for the rest of
 * the process and logs to stderr. Never crashes the host app. */

#include <stddef.h>
#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

/* Called once at shim init. Safe to call multiple times. */
void gpa_native_trace_init(void);

/* Returns non-zero if the feature is active (env on + at least one module
 * successfully scanned). */
int  gpa_native_trace_is_enabled(void);

/* Scan globals and POST a value_index for this (frame_id, dc_id).
 * No-op if !gpa_native_trace_is_enabled(). */
void gpa_native_trace_scan(uint64_t frame_id, uint32_t dc_id);

/* Phase 2: walk the current thread's stack and, for each frame whose PC
 * resolves to an indexed subprogram, read live primitive locals via the
 * DWARF location interpreter and POST them as `origin: "dwarf-locals"`.
 *
 * Gated by the separate env var GPA_TRACE_NATIVE_STACK=1. Independent of
 * the globals scanner — either can be enabled without the other. */
void gpa_native_trace_scan_stack(uint64_t frame_id, uint32_t dc_id);

/* Whether the stack-local scanner is active. */
int gpa_native_trace_stack_is_enabled(void);

/* Release all memory. */
void gpa_native_trace_shutdown(void);

/* -- Internals exposed for unit tests ----------------------------------- */

/* djb2-of-lowered-decimal-string hash, matching the JS scanner's
 * hashValue() output format ("n:<base36>"). The caller frees `out`. */
char* gpa_trace_hash_double(double v);
char* gpa_trace_hash_int64(int64_t v);
char* gpa_trace_hash_uint64(uint64_t v);
char* gpa_trace_hash_string(const char* s);

/* Check if a module basename (e.g. "libc.so.6") should be excluded from
 * scanning. Returns 1 if excluded, 0 otherwise. */
int   gpa_native_trace_is_system_module(const char* path);

/* Unit-test hook: pretend a scan consumed `fake_ms` milliseconds, forcing
 * the budget guard to set truncated=1 on the next call. Set to 0 to clear. */
void  gpa_native_trace_test_set_budget_overrun(int fake_ms);

/* Returns the value of the `truncated` flag from the last scan (for tests). */
int   gpa_native_trace_test_was_truncated(void);

/* Returns the running count of global derefs that were skipped because
 * their address triggered SIGSEGV (unmapped memory). Test hook. */
size_t gpa_native_trace_test_segv_skip_count(void);

/* Test hook: append a synthetic global pointing at `addr` with `byte_size`
 * + `encoding`. Used to verify the SIGSEGV guard against crafted unmapped
 * addresses without depending on a real DWARF module. Flips `G.enabled` to
 * 1 so gpa_native_trace_scan() will iterate. Caller must still provide an
 * endpoint; scan will POST to the configured host (or fail open). */
void gpa_native_trace_test_inject_global(const char* name, uintptr_t addr,
                                         uint64_t byte_size, uint32_t encoding);

#ifdef __cplusplus
}
#endif

#endif /* GPA_NATIVE_TRACE_H */
