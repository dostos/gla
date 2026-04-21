/* Phase 1 driver: DWARF-globals scanner for the OpenGL shim. */

#define _GNU_SOURCE
#include "native_trace.h"
#include "dwarf_parser.h"
#include "dwarf_locations.h"
#include "http_post.h"
#include "pc_to_die.h"
#include "stack_walker.h"

#include <ctype.h>
#include <dlfcn.h>
#include <link.h>
#include <pthread.h>
#include <setjmp.h>
#include <signal.h>
#include <unistd.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/time.h>

/* ---- configuration ---------------------------------------------------- */

#define BUDGET_MS         2
#define DEFAULT_ENDPOINT_HOST "127.0.0.1"
#define DEFAULT_ENDPOINT_PORT 18080

typedef struct {
    GpaDwarfGlobals globals;
    char*           module_path;   /* malloced */
    uintptr_t       load_bias;
    /* Phase 2: per-module subprogram + locals index. Populated iff the
     * stack scanner was enabled at init time; otherwise zero. */
    GpaDwarfSubprograms subs;
    int             subs_loaded;
} TracedModule;

static struct {
    int             enabled;           /* globals scanner */
    int             stack_enabled;     /* stack-local scanner */
    int             initialized;
    TracedModule*   modules;
    size_t          module_count;
    size_t          module_cap;
    size_t          total_globals;
    size_t          total_subprograms;
    pthread_rwlock_t lock;
    /* Endpoint */
    char            host[128];
    int             port;
    char            token[256];
    /* Test hooks */
    int             test_budget_overrun_ms;
    int             last_truncated;
    /* Budget-shrink state: max globals to walk this scan. */
    size_t          scan_limit;
    /* Phase 2: PC→subprogram index, built from every module's subs. */
    GpaPcIndex      pc_index;
} G = {
    .port = DEFAULT_ENDPOINT_PORT,
    .scan_limit = (size_t)-1,
};

/* ---- helpers ---------------------------------------------------------- */

static int env_flag(const char* name) {
    const char* v = getenv(name);
    return v && v[0] && strcmp(v, "0") != 0;
}

static const char* basename_of(const char* path) {
    const char* s = strrchr(path, '/');
    return s ? s + 1 : path;
}

int gpa_native_trace_is_system_module(const char* path) {
    if (!path || !*path) return 1;
    const char* base = basename_of(path);
    /* Hardcoded system-lib prefixes we don't want to scan. */
    static const char* const prefixes[] = {
        "libc.so", "libm.so", "libpthread.so", "libdl.so", "librt.so",
        "libstdc++.so", "libgcc_s.so", "ld-linux", "ld-2.", "libld-",
        "libX", "libxcb", "libGL.so", "libGLX", "libEGL", "libGLdispatch",
        "libnss", "libresolv", "libutil", "linux-vdso", "libcrypt",
        "libanl", "libbsd", "libffi", "libz.so",
    };
    for (size_t i = 0; i < sizeof(prefixes)/sizeof(prefixes[0]); i++) {
        size_t n = strlen(prefixes[i]);
        if (strncmp(base, prefixes[i], n) == 0) return 1;
    }
    /* /usr/lib**, /lib**, /lib64** — system. */
    if (strncmp(path, "/usr/lib", 8) == 0) return 1;
    if (strncmp(path, "/lib/",    5) == 0) return 1;
    if (strncmp(path, "/lib64/",  7) == 0) return 1;
    return 0;
}

/* ---- hashing (matches JS scanner's djb2 + toString(36)) --------------- */

static char* djb2_b36(const char* s) {
    uint32_t h = 5381;
    for (; *s; s++) {
        h = ((h << 5) + h) + (uint8_t)*s;
    }
    /* Base-36 encode h. JS `.toString(36)` uses 0-9 then a-z. */
    char buf[16];
    int n = 0;
    if (h == 0) { buf[n++] = '0'; }
    else { while (h) { uint32_t d = h % 36; buf[n++] = (char)(d < 10 ? '0' + d : 'a' + d - 10); h /= 36; } }
    char* out = (char*)malloc((size_t)n + 1);
    for (int i = 0; i < n; i++) out[i] = buf[n - 1 - i];
    out[n] = '\0';
    return out;
}

/* Canonical hash body for a double. Format (shared by C, JS, Python):
 *
 *   NaN                           -> "NaN"
 *   +Infinity                     -> "Inf"
 *   -Infinity                     -> "-Inf"
 *   zero / -0                     -> "0"
 *   finite integer, |v| < 2^53    -> signed decimal, e.g. "42", "-100"
 *   other finite double           -> "f:" + 16 lowercase hex chars of the
 *                                    IEEE-754 bit pattern (big-endian)
 *
 * The IEEE-754 fallback is the ONLY representation that's guaranteed to
 * agree byte-for-byte between the C shim and the JS extension (where
 * `Number.prototype.toString(36)` is implementation-defined for
 * fractional values). Integers stay in human-readable decimal for
 * debuggability and keep the existing integer wire format stable. */
static void number_to_js_base36(double v, char* out, size_t n) {
    /* NaN */
    if (v != v) { snprintf(out, n, "NaN"); return; }
    /* +/- infinity */
    if (v > 0 && v > 1.0e308 && v == v * 2.0) { snprintf(out, n, "Inf"); return; }
    if (v < 0 && v < -1.0e308 && v == v * 2.0) { snprintf(out, n, "-Inf"); return; }
    /* zero / -0 */
    if (v == 0.0) { snprintf(out, n, "0"); return; }
    double av = v < 0 ? -v : v;
    /* Finite integer fast path: exact representation in base 10. */
    if (av < 9007199254740992.0 /* 2^53 */ &&
        av == (double)(int64_t)av) {
        snprintf(out, n, "%lld", (long long)(int64_t)v);
        return;
    }
    /* Fractional: IEEE-754 bit pattern, lowercase hex. */
    uint64_t bits;
    memcpy(&bits, &v, sizeof(bits));
    snprintf(out, n, "f:%016llx", (unsigned long long)bits);
}

char* gpa_trace_hash_double(double v) {
    char s[64]; number_to_js_base36(v, s, sizeof(s));
    /* "n:" prefix matches hashValue() in gpa-trace.js. */
    size_t sl = strlen(s);
    char* with_prefix = (char*)malloc(sl + 3);
    with_prefix[0] = 'n'; with_prefix[1] = ':';
    memcpy(with_prefix + 2, s, sl + 1);
    return with_prefix;
}

char* gpa_trace_hash_int64(int64_t v) {
    return gpa_trace_hash_double((double)v);
}
char* gpa_trace_hash_uint64(uint64_t v) {
    return gpa_trace_hash_double((double)v);
}

char* gpa_trace_hash_string(const char* s) {
    if (!s) return NULL;
    size_t n = strlen(s);
    char* lower = (char*)malloc(n + 1);
    for (size_t i = 0; i < n; i++) lower[i] = (char)tolower((unsigned char)s[i]);
    lower[n] = '\0';
    char* h = djb2_b36(lower);
    free(lower);
    size_t hl = strlen(h);
    char* out = (char*)malloc(hl + 3);
    out[0] = 's'; out[1] = ':';
    memcpy(out + 2, h, hl + 1);
    free(h);
    return out;
}

/* ---- dl_iterate_phdr callback ----------------------------------------- */

static int phdr_cb(struct dl_phdr_info* info, size_t sz, void* user) {
    (void)sz;
    int want_subs = user ? *(int*)user : 0;
    const char* path = info->dlpi_name ? info->dlpi_name : "";
    /* Main executable: dlpi_name is "" */
    char main_path[512];
    if (!*path) {
        ssize_t r = readlink("/proc/self/exe", main_path, sizeof(main_path) - 1);
        if (r <= 0) return 0;
        main_path[r] = '\0';
        path = main_path;
    }
    if (gpa_native_trace_is_system_module(path)) return 0;

    GpaDwarfGlobals gl = {0};
    int rc = gpa_dwarf_parse_module(path, (uintptr_t)info->dlpi_addr, &gl);
    if (rc != GPA_DWARF_OK) {
        fprintf(stderr,
                "[OpenGPA] native-trace: skipping %s (%s)\n",
                path, gpa_dwarf_strerror(rc));
        gpa_dwarf_globals_free(&gl);
        return 0;
    }

    /* Phase 2: opt-in subprogram index. Failures are non-fatal — we keep
     * the module's globals even if the subprogram walk bails. */
    GpaDwarfSubprograms subs = {0};
    int subs_ok = 0;
    if (want_subs) {
        int sub_rc = gpa_dwarf_parse_subprograms(path, (uintptr_t)info->dlpi_addr, &subs);
        if (sub_rc == GPA_DWARF_OK) subs_ok = 1;
        else {
            fprintf(stderr,
                    "[OpenGPA] native-trace: subprogram index failed for %s (%s)\n",
                    path, gpa_dwarf_strerror(sub_rc));
            gpa_dwarf_subprograms_free(&subs);
        }
    }

    if (gl.count == 0 && !subs_ok) {
        gpa_dwarf_globals_free(&gl);
        return 0;
    }

    if (G.module_count == G.module_cap) {
        size_t new_cap = G.module_cap ? G.module_cap * 2 : 4;
        TracedModule* tmp = (TracedModule*)realloc(
            G.modules, new_cap * sizeof(TracedModule));
        if (!tmp) {
            /* OOM: keep the old array + counts intact and drop this module.
             * Previously the unchecked assignment leaked the old pointer
             * AND wrote past the end on the next line. */
            fprintf(stderr,
                    "[OpenGPA] native-trace: OOM growing modules array; "
                    "skipping %s\n", path);
            gpa_dwarf_globals_free(&gl);
            if (subs_ok) gpa_dwarf_subprograms_free(&subs);
            return 0;
        }
        G.modules = tmp;
        G.module_cap = new_cap;
    }
    TracedModule* m = &G.modules[G.module_count++];
    m->globals = gl;
    m->subs = subs;
    m->subs_loaded = subs_ok;
    m->module_path = strdup(path);
    m->load_bias = (uintptr_t)info->dlpi_addr;
    G.total_globals += gl.count;
    if (subs_ok) G.total_subprograms += subs.count;
    return 0;
}

/* ---- lifecycle -------------------------------------------------------- */

void gpa_native_trace_init(void) {
    if (G.initialized) return;
    G.initialized = 1;
    pthread_rwlock_init(&G.lock, NULL);
    gpa_pc_index_init(&G.pc_index);

    int want_globals = env_flag("GPA_TRACE_NATIVE");
    int want_stack   = env_flag("GPA_TRACE_NATIVE_STACK");
    if (!want_globals && !want_stack) {
        return;  /* opt-in only */
    }

    /* Endpoint config: overrideable via env. Defaults mirror the JS
     * scanner (127.0.0.1:18080). */
    const char* host = getenv("GPA_TRACE_HOST");
    snprintf(G.host, sizeof(G.host), "%s", host && *host ? host : DEFAULT_ENDPOINT_HOST);
    const char* portstr = getenv("GPA_TRACE_PORT");
    G.port = portstr && *portstr ? atoi(portstr) : DEFAULT_ENDPOINT_PORT;
    const char* tok = getenv("GPA_TOKEN");
    if (tok && *tok) snprintf(G.token, sizeof(G.token), "%s", tok);

    struct timeval t0, t1;
    gettimeofday(&t0, NULL);
    dl_iterate_phdr(phdr_cb, &want_stack);
    gettimeofday(&t1, NULL);
    long ms = (t1.tv_sec - t0.tv_sec) * 1000 + (t1.tv_usec - t0.tv_usec) / 1000;

    /* Build the PC → subprogram index from all loaded modules. */
    if (want_stack) {
        for (size_t i = 0; i < G.module_count; i++) {
            if (G.modules[i].subs_loaded) {
                gpa_pc_index_add_module(&G.pc_index, &G.modules[i].subs);
            }
        }
        gpa_pc_index_sort(&G.pc_index);
    }

    G.enabled       = want_globals && (G.total_globals > 0);
    G.stack_enabled = want_stack   && (G.pc_index.count > 0);
    fprintf(stderr,
            "[OpenGPA] native-trace: %sscanned %zu modules, %zu globals, "
            "%zu subprograms (%ld ms)\n",
            (G.enabled || G.stack_enabled) ? "" : "(empty) ",
            G.module_count, G.total_globals, G.total_subprograms, ms);
}

int gpa_native_trace_is_enabled(void) { return G.enabled; }
int gpa_native_trace_stack_is_enabled(void) { return G.stack_enabled; }

/* ---- scan + POST ------------------------------------------------------ */

static long now_us(void) {
    struct timeval tv; gettimeofday(&tv, NULL);
    return (long)(tv.tv_sec * 1000000L + tv.tv_usec);
}

/* Append JSON-escaped string to buffer. Returns new length on success, or
 * `len` unchanged on OOM (caller is expected to abort the scan before
 * flushing). Note: on OOM we leave *buf / *cap alone; the original data
 * stays valid — previously an unchecked realloc would leak *buf and crash
 * on the next memcpy. */
static size_t json_append(char** buf, size_t* cap, size_t len, const char* s) {
    size_t n = strlen(s);
    if (len + n + 1 > *cap) {
        size_t new_cap = *cap;
        while (len + n + 1 > new_cap) new_cap = new_cap ? new_cap * 2 : 1024;
        char* tmp = (char*)realloc(*buf, new_cap);
        if (!tmp) return len;  /* OOM: drop this append. */
        *buf = tmp;
        *cap = new_cap;
    }
    memcpy(*buf + len, s, n);
    return len + n;
}
static size_t json_esc(char** buf, size_t* cap, size_t len, const char* s) {
    len = json_append(buf, cap, len, "\"");
    for (; *s; s++) {
        char c = *s;
        char esc[8];
        if (c == '"' || c == '\\') { snprintf(esc, sizeof(esc), "\\%c", c); len = json_append(buf, cap, len, esc); }
        else if ((unsigned char)c < 0x20) { snprintf(esc, sizeof(esc), "\\u%04x", c); len = json_append(buf, cap, len, esc); }
        else {
            if (len + 2 > *cap) {
                size_t new_cap = *cap ? *cap * 2 : 1024;
                char* tmp = (char*)realloc(*buf, new_cap);
                if (!tmp) continue;  /* OOM: drop the char. */
                *buf = tmp; *cap = new_cap;
            }
            (*buf)[len++] = c;
        }
    }
    return json_append(buf, cap, len, "\"");
}

/* ---- SIGSEGV-guarded global deref ------------------------------------- */
/* A traced module can unmap its .bss (e.g. via `dlclose`) while we hold a
 * pointer into the globals table. Without a guard, dereferencing that
 * address segfaults the host app. We install a per-deref SIGSEGV trampoline
 * using sigsetjmp/siglongjmp: on success we read the value, on crash we
 * skip the global, log once, and carry on with the next. SA_RESETHAND
 * ensures a second crash from inside the handler won't infinite-loop. */

static sigjmp_buf g_segv_jmp;
static volatile sig_atomic_t g_segv_armed = 0;
static volatile sig_atomic_t g_segv_skips = 0;

static void on_segv(int sig) {
    (void)sig;
    if (g_segv_armed) {
        g_segv_armed = 0;
        siglongjmp(g_segv_jmp, 1);
    }
    /* Not armed — let the default handler fire on return (SA_RESETHAND
     * was set, so the second crash inside our own handler exits the app
     * rather than looping). */
    _exit(139);
}

/* Safely dereference `src` of `nbytes` (1/2/4/8) into `dst`. Returns 1 on
 * success, 0 on SIGSEGV. Install + restore the handler around a single
 * read so concurrent threads don't share our trampoline. */
static int safe_read(void* dst, const void* src, size_t nbytes) {
    struct sigaction prev_sa, new_sa;
    memset(&new_sa, 0, sizeof(new_sa));
    new_sa.sa_handler = on_segv;
    sigemptyset(&new_sa.sa_mask);
    new_sa.sa_flags = SA_NODEFER | SA_RESETHAND;
    if (sigaction(SIGSEGV, &new_sa, &prev_sa) != 0) {
        /* Fallback: attempt unguarded read (same behaviour as before fix). */
        memcpy(dst, src, nbytes);
        return 1;
    }
    int ok = 1;
    if (sigsetjmp(g_segv_jmp, 1) == 0) {
        g_segv_armed = 1;
        memcpy(dst, src, nbytes);
        g_segv_armed = 0;
    } else {
        ok = 0;
        g_segv_skips++;
    }
    sigaction(SIGSEGV, &prev_sa, NULL);
    return ok;
}

/* Return the count of derefs that SIGSEGV'd since process start. Test hook. */
size_t gpa_native_trace_test_segv_skip_count(void) {
    return (size_t)g_segv_skips;
}

static const char* enc_name(uint32_t enc, uint64_t sz) {
    switch (enc) {
    case GPA_DW_ATE_FLOAT:         return sz == 8 ? "double" : "float";
    case GPA_DW_ATE_SIGNED:        return sz == 8 ? "int64" : sz == 4 ? "int32" : sz == 2 ? "int16" : "int";
    case GPA_DW_ATE_UNSIGNED:      return sz == 8 ? "uint64" : sz == 4 ? "uint32" : sz == 2 ? "uint16" : "uint";
    case GPA_DW_ATE_SIGNED_CHAR:   return "char";
    case GPA_DW_ATE_UNSIGNED_CHAR: return "uchar";
    case GPA_DW_ATE_BOOLEAN:       return "bool";
    default:                        return "unknown";
    }
}

void gpa_native_trace_scan(uint64_t frame_id, uint32_t dc_id) {
    if (!G.enabled) return;
    G.last_truncated = 0;

    long start_us = now_us();
    char* buf = NULL; size_t cap = 0, len = 0;

    len = json_append(&buf, &cap, len, "{\"frame_id\":");
    char num[32];
    snprintf(num, sizeof(num), "%lu", (unsigned long)frame_id); len = json_append(&buf, &cap, len, num);
    len = json_append(&buf, &cap, len, ",\"dc_id\":");
    snprintf(num, sizeof(num), "%u", dc_id); len = json_append(&buf, &cap, len, num);
    len = json_append(&buf, &cap, len,
        ",\"sources\":{\"mode\":\"gated\",\"origin\":\"dwarf-globals\",\"roots\":[\"globals\"],\"value_index\":{");

    pthread_rwlock_rdlock(&G.lock);
    size_t scanned = 0;
    size_t limit = G.scan_limit;
    int truncated = 0;
    int first_entry = 1;
    for (size_t mi = 0; mi < G.module_count && !truncated; mi++) {
        GpaDwarfGlobals* gl = &G.modules[mi].globals;
        for (size_t i = 0; i < gl->count; i++) {
            if (scanned >= limit) { truncated = 1; break; }
            /* Budget check every 64 items to avoid gettimeofday overhead. */
            if ((scanned & 63) == 0) {
                long elapsed = now_us() - start_us;
                if (elapsed > BUDGET_MS * 1000 ||
                    G.test_budget_overrun_ms > BUDGET_MS) {
                    truncated = 1; break;
                }
            }
            scanned++;
            const GpaDwarfGlobal* g = &gl->items[i];
            if (!g->address || !g->byte_size) continue;
            /* SIGSEGV-guarded deref: read the value into a stack buffer
             * first. If the deref crashes (unmapped .bss, dangling GOT,
             * etc.) we skip this global and continue with the next. */
            uint64_t raw64 = 0;
            if (!safe_read(&raw64, (const void*)(uintptr_t)g->address,
                           (size_t)g->byte_size)) {
                continue;
            }
            char* hash = NULL;
            switch (g->type_encoding) {
            case GPA_DW_ATE_FLOAT:
                if (g->byte_size == 8)      { double dv; memcpy(&dv, &raw64, 8); hash = gpa_trace_hash_double(dv); }
                else if (g->byte_size == 4) { float fv; memcpy(&fv, &raw64, 4); hash = gpa_trace_hash_double((double)fv); }
                break;
            case GPA_DW_ATE_SIGNED:
                if (g->byte_size == 8)      hash = gpa_trace_hash_int64((int64_t)raw64);
                else if (g->byte_size == 4) hash = gpa_trace_hash_int64((int64_t)(int32_t)(uint32_t)raw64);
                else if (g->byte_size == 2) hash = gpa_trace_hash_int64((int64_t)(int16_t)(uint16_t)raw64);
                else if (g->byte_size == 1) hash = gpa_trace_hash_int64((int64_t)(int8_t)(uint8_t)raw64);
                break;
            case GPA_DW_ATE_UNSIGNED:
                if (g->byte_size == 8)      hash = gpa_trace_hash_uint64(raw64);
                else if (g->byte_size == 4) hash = gpa_trace_hash_uint64((uint32_t)raw64);
                else if (g->byte_size == 2) hash = gpa_trace_hash_uint64((uint16_t)raw64);
                else if (g->byte_size == 1) hash = gpa_trace_hash_uint64((uint8_t)raw64);
                break;
            case GPA_DW_ATE_BOOLEAN:
                hash = gpa_trace_hash_uint64((uint8_t)raw64 ? 1 : 0);
                break;
            default: break;
            }
            if (!hash) continue;
            if (!first_entry) len = json_append(&buf, &cap, len, ",");
            first_entry = 0;
            len = json_esc(&buf, &cap, len, hash);
            len = json_append(&buf, &cap, len, ":[{\"path\":");
            len = json_esc(&buf, &cap, len, g->name);
            len = json_append(&buf, &cap, len, ",\"type\":");
            len = json_esc(&buf, &cap, len, enc_name(g->type_encoding, g->byte_size));
            len = json_append(&buf, &cap, len, ",\"confidence\":\"high\"}]");
            free(hash);
        }
    }
    pthread_rwlock_unlock(&G.lock);

    len = json_append(&buf, &cap, len, "}");
    len = json_append(&buf, &cap, len, truncated ? ",\"truncated\":true" : ",\"truncated\":false");
    long scan_ms_x1000 = (now_us() - start_us);
    char scan_ms_buf[48];
    snprintf(scan_ms_buf, sizeof(scan_ms_buf), ",\"scan_ms\":%ld.%03ld}}",
             scan_ms_x1000 / 1000, scan_ms_x1000 % 1000);
    len = json_append(&buf, &cap, len, scan_ms_buf);

    G.last_truncated = truncated;
    if (truncated) {
        /* Shrink next scan's budget. */
        if (G.scan_limit == (size_t)-1) G.scan_limit = scanned;
        else if (G.scan_limit > 64) G.scan_limit = G.scan_limit / 2;
    }

    char path[256];
    snprintf(path, sizeof(path),
             "/api/v1/frames/%lu/drawcalls/%u/sources",
             (unsigned long)frame_id, dc_id);
    gpa_http_post_json(G.host, G.port, path,
                       G.token[0] ? G.token : NULL,
                       buf, len);
    free(buf);
}

/* ---- Phase 2: stack-local scanner ------------------------------------ */

static void hash_from_bytes(uint32_t enc, uint64_t sz,
                            const uint8_t* bytes, char** out_hash) {
    *out_hash = NULL;
    if (!bytes) return;
    switch (enc) {
    case GPA_DW_ATE_FLOAT:
        if (sz == 8) { double d; memcpy(&d, bytes, 8); *out_hash = gpa_trace_hash_double(d); }
        else if (sz == 4) { float f; memcpy(&f, bytes, 4); *out_hash = gpa_trace_hash_double((double)f); }
        break;
    case GPA_DW_ATE_SIGNED: {
        int64_t v = 0;
        if      (sz == 8) { int64_t t; memcpy(&t, bytes, 8); v = t; }
        else if (sz == 4) { int32_t t; memcpy(&t, bytes, 4); v = t; }
        else if (sz == 2) { int16_t t; memcpy(&t, bytes, 2); v = t; }
        else if (sz == 1) { int8_t  t; memcpy(&t, bytes, 1); v = t; }
        else return;
        *out_hash = gpa_trace_hash_int64(v);
        break;
    }
    case GPA_DW_ATE_UNSIGNED: {
        uint64_t v = 0;
        if      (sz == 8) { uint64_t t; memcpy(&t, bytes, 8); v = t; }
        else if (sz == 4) { uint32_t t; memcpy(&t, bytes, 4); v = t; }
        else if (sz == 2) { uint16_t t; memcpy(&t, bytes, 2); v = t; }
        else if (sz == 1) { v = bytes[0]; }
        else return;
        *out_hash = gpa_trace_hash_uint64(v);
        break;
    }
    case GPA_DW_ATE_BOOLEAN:
        *out_hash = gpa_trace_hash_uint64(bytes[0] ? 1 : 0);
        break;
    default: break;
    }
}

void gpa_native_trace_scan_stack(uint64_t frame_id, uint32_t dc_id) {
    if (!G.stack_enabled) return;
    long start_us = now_us();

    GpaStackSnapshot snap;
    gpa_stack_walk_current(&snap);
    if (snap.frame_count == 0) { gpa_stack_snapshot_free(&snap); return; }

    char* buf = NULL; size_t cap = 0, len = 0;
    len = json_append(&buf, &cap, len, "{\"frame_id\":");
    char num[32];
    snprintf(num, sizeof(num), "%lu", (unsigned long)frame_id);
    len = json_append(&buf, &cap, len, num);
    len = json_append(&buf, &cap, len, ",\"dc_id\":");
    snprintf(num, sizeof(num), "%u", dc_id);
    len = json_append(&buf, &cap, len, num);
    len = json_append(&buf, &cap, len,
        ",\"sources\":{\"mode\":\"gated\",\"origin\":\"dwarf-locals\",\"roots\":[");

    int root_first = 1;
    /* value_index accumulated while iterating frames. We build the roots
     * array in the same pass, then emit value_index after. */
    char* vi_buf = NULL; size_t vi_cap = 0, vi_len = 0;
    int vi_first = 1;
    int truncated = 0;

    pthread_rwlock_rdlock(&G.lock);
    for (size_t fi = 0; fi < snap.frame_count && !truncated; fi++) {
        if ((fi & 3) == 0) {
            long elapsed = now_us() - start_us;
            if (elapsed > BUDGET_MS * 1000 ||
                G.test_budget_overrun_ms > BUDGET_MS) {
                truncated = 1; break;
            }
        }
        GpaStackFrame* f = &snap.frames[fi];
        const GpaDwarfSubprogram* sp = gpa_pc_index_lookup(&G.pc_index, f->pc);
        if (!sp || sp->local_count == 0) continue;

        char root[128];
        snprintf(root, sizeof(root), "locals@%s+0x%lx",
                 sp->name ? sp->name : "?",
                 (unsigned long)(f->pc - sp->low_pc));
        if (!root_first) len = json_append(&buf, &cap, len, ",");
        root_first = 0;
        len = json_esc(&buf, &cap, len, root);

        GpaLocCtx ctx = {
            .registers = f->registers,
            .reg_valid = f->reg_valid,
            .reg_count = GPA_STACK_REG_COUNT,
            .frame_base = f->cfa,
        };

        for (size_t li = 0; li < sp->local_count; li++) {
            const GpaDwarfLocal* L = &sp->locals[li];
            if (L->byte_size == 0 || L->byte_size > 8) continue; /* V1 primitive limit */
            GpaLocResult r;
            if (gpa_dwarf_eval_location(L->location_expr, L->location_len,
                                        &ctx, &r) != GPA_LOCEVAL_OK) {
                continue;
            }
            uint8_t bytes[16] = {0};
            if (gpa_dwarf_read_value(&r, (size_t)L->byte_size, &ctx,
                                     bytes, sizeof(bytes)) < 0) {
                continue;
            }
            char* hash = NULL;
            hash_from_bytes(L->type_encoding, L->byte_size, bytes, &hash);
            if (!hash) continue;
            if (!vi_first) vi_len = json_append(&vi_buf, &vi_cap, vi_len, ",");
            vi_first = 0;
            vi_len = json_esc(&vi_buf, &vi_cap, vi_len, hash);
            vi_len = json_append(&vi_buf, &vi_cap, vi_len, ":[{\"path\":");
            char path[256];
            snprintf(path, sizeof(path), "%s/%s",
                     sp->name ? sp->name : "?", L->name ? L->name : "?");
            vi_len = json_esc(&vi_buf, &vi_cap, vi_len, path);
            vi_len = json_append(&vi_buf, &vi_cap, vi_len, ",\"type\":");
            vi_len = json_esc(&vi_buf, &vi_cap, vi_len, enc_name(L->type_encoding, L->byte_size));
            vi_len = json_append(&vi_buf, &vi_cap, vi_len, ",\"confidence\":\"high\"}]");
            free(hash);
        }
    }
    pthread_rwlock_unlock(&G.lock);

    len = json_append(&buf, &cap, len, "],\"value_index\":{");
    if (vi_buf) {
        /* Append accumulated value_index. */
        if (len + vi_len + 1 > cap) {
            size_t new_cap = cap;
            while (len + vi_len + 1 > new_cap) new_cap = new_cap ? new_cap * 2 : 1024;
            char* tmp = (char*)realloc(buf, new_cap);
            if (tmp) { buf = tmp; cap = new_cap; }
            /* else: leave buf intact; the memcpy below would overrun, so
             * skip the append on OOM. */
        }
        if (len + vi_len + 1 <= cap) {
            memcpy(buf + len, vi_buf, vi_len);
            len += vi_len;
        }
        free(vi_buf);
    }
    len = json_append(&buf, &cap, len, "}");
    len = json_append(&buf, &cap, len, truncated ? ",\"truncated\":true" : ",\"truncated\":false");
    long scan_us = now_us() - start_us;
    char scan_ms_buf[48];
    snprintf(scan_ms_buf, sizeof(scan_ms_buf), ",\"scan_ms\":%ld.%03ld}}",
             scan_us / 1000, scan_us % 1000);
    len = json_append(&buf, &cap, len, scan_ms_buf);

    G.last_truncated = truncated;

    char path[256];
    snprintf(path, sizeof(path),
             "/api/v1/frames/%lu/drawcalls/%u/sources",
             (unsigned long)frame_id, dc_id);
    gpa_http_post_json(G.host, G.port, path,
                       G.token[0] ? G.token : NULL,
                       buf, len);
    free(buf);
    gpa_stack_snapshot_free(&snap);
}

void gpa_native_trace_shutdown(void) {
    if (!G.initialized) return;
    gpa_pc_index_free(&G.pc_index);
    for (size_t i = 0; i < G.module_count; i++) {
        gpa_dwarf_globals_free(&G.modules[i].globals);
        if (G.modules[i].subs_loaded) {
            gpa_dwarf_subprograms_free(&G.modules[i].subs);
        }
        free(G.modules[i].module_path);
    }
    free(G.modules);
    G.modules = NULL;
    G.module_count = G.module_cap = 0;
    G.total_globals = 0;
    G.total_subprograms = 0;
    G.enabled = 0;
    G.stack_enabled = 0;
    pthread_rwlock_destroy(&G.lock);
    G.initialized = 0;
}

void gpa_native_trace_test_set_budget_overrun(int fake_ms) {
    G.test_budget_overrun_ms = fake_ms;
}

int gpa_native_trace_test_was_truncated(void) {
    return G.last_truncated;
}

void gpa_native_trace_test_inject_global(const char* name, uintptr_t addr,
                                         uint64_t byte_size, uint32_t encoding) {
    if (!G.initialized) {
        pthread_rwlock_init(&G.lock, NULL);
        G.initialized = 1;
        /* Route POSTs to a black hole so the test doesn't depend on a
         * listening server. http_post fails open. */
        snprintf(G.host, sizeof(G.host), "127.0.0.1");
        G.port = 1;
    }
    /* Append a fresh module carrying the one injected global. */
    if (G.module_count == G.module_cap) {
        size_t nc = G.module_cap ? G.module_cap * 2 : 4;
        TracedModule* nb = (TracedModule*)realloc(G.modules,
                                                  nc * sizeof(TracedModule));
        if (!nb) return;
        G.modules = nb;
        G.module_cap = nc;
    }
    TracedModule* m = &G.modules[G.module_count++];
    memset(m, 0, sizeof(*m));
    m->module_path = strdup("<test-injected>");
    m->load_bias = 0;
    GpaDwarfGlobals* gl = &m->globals;
    gl->items = (GpaDwarfGlobal*)realloc(NULL, sizeof(GpaDwarfGlobal));
    gl->count = 1;
    gl->cap = 1;
    gl->strpool = strdup(name ? name : "inj");
    size_t nlen = strlen(gl->strpool);
    gl->strpool_len = nlen + 1;
    gl->strpool_cap = nlen + 1;
    gl->items[0].name = gl->strpool;
    gl->items[0].address = addr;
    gl->items[0].byte_size = byte_size;
    gl->items[0].type_encoding = encoding;
    G.total_globals += 1;
    G.enabled = 1;
}
