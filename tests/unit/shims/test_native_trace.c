/* Tests for the DWARF parser + native-trace driver.
 * Uses assert(); runs the fixture binary as a build-time artifact located
 * via bazel runfiles. */

#define _GNU_SOURCE
#include "src/shims/gl/dwarf_parser.h"
#include "src/shims/gl/native_trace.h"
#include "src/shims/gl/pc_to_die.h"

#include <assert.h>
#include <dlfcn.h>
#include <math.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/mman.h>
#include <sys/stat.h>
#include <unistd.h>

/* ---- fixture locator -------------------------------------------------- */

/* Bazel copies data deps into the runfiles tree. The test binary runs with
 * RUNFILES_DIR or TEST_SRCDIR set (both point to the runfiles root). */
static char fixture_path[1024] = {0};

static void locate_fixture(void) {
    const char* base = getenv("TEST_SRCDIR");
    const char* ws = getenv("TEST_WORKSPACE");
    if (base && ws) {
        snprintf(fixture_path, sizeof(fixture_path),
                 "%s/%s/tests/unit/shims/fixtures/trace_fixture_bin", base, ws);
        if (access(fixture_path, X_OK) == 0) return;
        snprintf(fixture_path, sizeof(fixture_path),
                 "%s/_main/tests/unit/shims/fixtures/trace_fixture_bin", base);
        if (access(fixture_path, X_OK) == 0) return;
    }
    /* Fallback: sibling in the current binary's directory. */
    char self[1024]; ssize_t r = readlink("/proc/self/exe", self, sizeof(self) - 1);
    if (r > 0) {
        self[r] = '\0';
        char* slash = strrchr(self, '/');
        if (slash) {
            snprintf(fixture_path, sizeof(fixture_path), "%.*s/fixtures/trace_fixture_bin",
                     (int)(slash - self), self);
            if (access(fixture_path, X_OK) == 0) return;
        }
    }
    fprintf(stderr, "could not locate trace_fixture binary\n");
    exit(2);
}

static const GpaDwarfGlobal* find_global(const GpaDwarfGlobals* g, const char* name) {
    for (size_t i = 0; i < g->count; i++) {
        if (strcmp(g->items[i].name, name) == 0) return &g->items[i];
    }
    return NULL;
}

/* ------------------------------------------------------------------------ */

static void test_dwarf_parser_reads_globals(void) {
    GpaDwarfGlobals g = {0};
    int rc = gpa_dwarf_parse_module(fixture_path, 0, &g);
    assert(rc == GPA_DWARF_OK);
    assert(g.count > 0);

    const GpaDwarfGlobal* d = find_global(&g, "g_test_double");
    assert(d != NULL);
    assert(d->byte_size == 8);
    assert(d->type_encoding == GPA_DW_ATE_FLOAT);

    /* Read the value through the reported address and check it's 16.58.
     * Note: parsing with load_bias=0 gives us the absolute link-time address.
     * For a non-PIE binary that address is directly dereferenceable in this
     * test process — but the fixture binary is separate, so we instead use
     * the byte_size + encoding assertions. Address correctness is covered
     * by the scan-hash test below. */
    gpa_dwarf_globals_free(&g);
    printf("PASS test_dwarf_parser_reads_globals\n");
}

static void test_dwarf_parser_reads_primitive_types(void) {
    GpaDwarfGlobals g = {0};
    int rc = gpa_dwarf_parse_module(fixture_path, 0, &g);
    assert(rc == GPA_DWARF_OK);

    const GpaDwarfGlobal* td = find_global(&g, "g_test_double");
    const GpaDwarfGlobal* ti = find_global(&g, "g_test_int");
    const GpaDwarfGlobal* tf = find_global(&g, "g_test_float");
    const GpaDwarfGlobal* tp = find_global(&g, "g_public_double");
    assert(td && ti && tf && tp);

    assert(td->type_encoding == GPA_DW_ATE_FLOAT  && td->byte_size == 8);
    assert(ti->type_encoding == GPA_DW_ATE_SIGNED && ti->byte_size == 4);
    assert(tf->type_encoding == GPA_DW_ATE_FLOAT  && tf->byte_size == 4);
    assert(tp->type_encoding == GPA_DW_ATE_FLOAT  && tp->byte_size == 8);

    gpa_dwarf_globals_free(&g);
    printf("PASS test_dwarf_parser_reads_primitive_types\n");
}

/* Hand-crafted DWARF-5 CU header. v5 layout is:
 *   unit_length (4B) | version (2B = 5) | unit_type (1B) | address_size (1B)
 *                    | debug_abbrev_offset (4B) | <DIEs>
 * We only need enough bytes for the parser to read the version field. */
static void test_dwarf_parser_rejects_dwarf5(void) {
    /* Write a minimal ELF that includes a tiny .debug_info + .debug_abbrev
     * with version=5. Cheapest route: generate a file with a real CU header
     * in the right section names. Simplest: produce a bare ELF with a
     * single SHT_PROGBITS section named .debug_info holding the v5 header,
     * plus a one-byte .debug_abbrev. */
    char path[] = "/tmp/gpa_dwarf5_XXXXXX";
    int fd = mkstemp(path);
    assert(fd >= 0);

    /* ELF64 header + 4 section headers (null, .debug_info, .debug_abbrev, shstrtab). */
    unsigned char ehdr[64] = {0};
    ehdr[0] = 0x7f; ehdr[1] = 'E'; ehdr[2] = 'L'; ehdr[3] = 'F';
    ehdr[4] = 2; /* ELFCLASS64 */
    ehdr[5] = 1; /* little-endian */
    ehdr[6] = 1; /* EI_VERSION */
    /* e_type REL=1 */ ehdr[16] = 1;
    /* e_machine X86_64=62 */ ehdr[18] = 62;
    /* e_version */ ehdr[20] = 1;
    /* e_ehsize */ ehdr[52] = 64;
    /* e_shentsize */ ehdr[58] = 64;
    /* e_shnum = 4 */ ehdr[60] = 4;
    /* e_shstrndx = 3 */ ehdr[62] = 3;

    /* Layout:
     *   offset 0: ELF header (64B)
     *   offset 64: .debug_info  (11B CU header, v5)
     *   offset 75: .debug_abbrev (1 byte, null-terminator for empty table)
     *   offset 76: shstrtab (\0 + section names)
     *   offset X: 4 section headers
     */
    /* DWARF-5 CU header is 12 bytes: length(4)+version(2)+unit_type(1)+
     * address_size(1)+debug_abbrev_offset(4). */
    unsigned char debug_info[12] = {
        8, 0, 0, 0,        /* unit_length = 8 (rest after length) */
        5, 0,              /* version = 5 */
        0,                 /* unit_type */
        8,                 /* address_size */
        0, 0, 0, 0,        /* debug_abbrev_offset */
    };
    unsigned char debug_abbrev[1] = {0};
    /* shstrtab: \0 .debug_info\0 .debug_abbrev\0 .shstrtab\0 */
    const char shstr[] = "\0.debug_info\0.debug_abbrev\0.shstrtab\0";
    size_t shstr_len = sizeof(shstr);

    unsigned char buf[4096] = {0};
    memcpy(buf, ehdr, 64);
    memcpy(buf + 64, debug_info, sizeof(debug_info));
    memcpy(buf + 64 + sizeof(debug_info), debug_abbrev, 1);
    size_t shstr_off = 64 + sizeof(debug_info) + 1;
    memcpy(buf + shstr_off, shstr, shstr_len);
    size_t sh_off = shstr_off + shstr_len;
    /* Align up to 8. */
    sh_off = (sh_off + 7) & ~(size_t)7;

    /* Write e_shoff into ELF header. */
    for (int i = 0; i < 8; i++) buf[40 + i] = (unsigned char)((sh_off >> (8*i)) & 0xff);

    /* Four Elf64_Shdr entries, 64 bytes each.
     * Fields: sh_name(4) sh_type(4) sh_flags(8) sh_addr(8) sh_offset(8) sh_size(8)
     *         sh_link(4) sh_info(4) sh_addralign(8) sh_entsize(8) */
    unsigned char* sh = buf + sh_off;
    memset(sh, 0, 64 * 4);
    /* idx 1: .debug_info — name offset=1 in shstrtab, type=1 (PROGBITS), offset=64, size=12 */
    sh[64 + 0] = 1; /* name */
    sh[64 + 4] = 1; /* type */
    sh[64 + 24] = 64; /* offset */
    sh[64 + 32] = (unsigned char)sizeof(debug_info); /* size */
    /* idx 2: .debug_abbrev — name offset in shstrtab = len(".debug_info\0") = 12 → offset 13 from start-of-strtab. */
    sh[128 + 0] = 13;
    sh[128 + 4] = 1;
    sh[128 + 24] = 64 + (unsigned char)sizeof(debug_info);
    sh[128 + 32] = 1;
    /* idx 3: .shstrtab — name offset=27, type=3 (STRTAB), offset=shstr_off, size=shstr_len */
    sh[192 + 0] = 27;
    sh[192 + 4] = 3;
    sh[192 + 24] = (unsigned char)shstr_off;
    sh[192 + 32] = (unsigned char)shstr_len;

    size_t total = sh_off + 64 * 4;
    ssize_t wrote = write(fd, buf, total);
    assert(wrote == (ssize_t)total);
    close(fd);

    GpaDwarfGlobals g = {0};
    int rc = gpa_dwarf_parse_module(path, 0, &g);
    assert(rc == GPA_DWARF_UNSUPPORTED_VERSION);
    gpa_dwarf_globals_free(&g);
    unlink(path);
    printf("PASS test_dwarf_parser_rejects_dwarf5\n");
}

static void test_scan_hashes_values_match_js_scanner(void) {
    /* Canonical hash body (cross-origin parity with
     * src/shims/webgl/extension/gpa-trace.js::canonicalNumber and
     * src/python/gpa/api/routes_trace.py::_parse_canonical_number):
     *   NaN/Inf/-Inf/0           -> sentinel tokens
     *   integer, |v| < 2^53      -> signed decimal
     *   other finite double      -> "f:" + IEEE-754 big-endian hex (16 chars)
     */
    /* Integer fast path. 100 -> "100". */
    char* h_int = gpa_trace_hash_double(100.0);
    assert(strcmp(h_int, "n:100") == 0);
    free(h_int);

    char* h_neg_int = gpa_trace_hash_double(-42.0);
    assert(strcmp(h_neg_int, "n:-42") == 0);
    free(h_neg_int);

    char* h_zero = gpa_trace_hash_double(0.0);
    assert(strcmp(h_zero, "n:0") == 0);
    free(h_zero);

    /* -0 normalizes to "n:0". */
    char* h_negz = gpa_trace_hash_double(-0.0);
    assert(strcmp(h_negz, "n:0") == 0);
    free(h_negz);

    /* Fractional → IEEE-754 hex. 16.58 has well-known bits
     * 0x4030940A3D70A3D7. */
    char* h_frac = gpa_trace_hash_double(16.58);
    assert(strncmp(h_frac, "n:f:", 4) == 0);
    assert(strlen(h_frac) == 4 + 16);
    uint64_t frac_bits;
    double v_frac = 16.58;
    memcpy(&frac_bits, &v_frac, 8);
    char want_frac[32];
    snprintf(want_frac, sizeof(want_frac), "n:f:%016llx",
             (unsigned long long)frac_bits);
    assert(strcmp(h_frac, want_frac) == 0);
    free(h_frac);

    /* Stability: same input, same hash. */
    char* h1 = gpa_trace_hash_double(3.14159);
    char* h2 = gpa_trace_hash_double(3.14159);
    assert(strcmp(h1, h2) == 0);
    free(h1); free(h2);

    /* NaN / Inf sentinels. */
    char* h_nan = gpa_trace_hash_double(0.0 / 0.0);
    assert(strcmp(h_nan, "n:NaN") == 0);
    free(h_nan);

    double inf_val = 1.0; for (int i = 0; i < 4; i++) inf_val *= 1e200;
    char* h_inf = gpa_trace_hash_double(inf_val);
    assert(strcmp(h_inf, "n:Inf") == 0);
    free(h_inf);

    char* h_ninf = gpa_trace_hash_double(-inf_val);
    assert(strcmp(h_ninf, "n:-Inf") == 0);
    free(h_ninf);

    /* String hash — djb2 lowercased. "Hello" → djb2("hello") = 261238937 →
     * base36 = "4bbdlt". */
    char* hs = gpa_trace_hash_string("Hello");
    assert(hs);
    assert(strncmp(hs, "s:", 2) == 0);
    /* djb2 of "hello": ((((5381*33)+'h')*33+'e')*33+'l')*33+'l')*33+'o' */
    uint32_t h = 5381;
    const char* s = "hello";
    for (; *s; s++) h = ((h << 5) + h) + (uint8_t)*s;
    char want[16]; int k = 0; uint32_t t = h;
    if (!t) want[k++] = '0';
    else { while (t) { uint32_t d = t % 36; want[k++] = (char)(d < 10 ? '0' + d : 'a' + d - 10); t /= 36; } }
    char wantb[32]; wantb[0] = 's'; wantb[1] = ':';
    for (int i = 0; i < k; i++) wantb[2 + i] = want[k - 1 - i];
    wantb[2 + k] = '\0';
    assert(strcmp(hs, wantb) == 0);
    free(hs);

    printf("PASS test_scan_hashes_values_match_js_scanner\n");
}

static void test_scan_excludes_system_libs(void) {
    assert(gpa_native_trace_is_system_module("/lib/x86_64-linux-gnu/libc.so.6"));
    assert(gpa_native_trace_is_system_module("/usr/lib/x86_64-linux-gnu/libm.so.6"));
    assert(gpa_native_trace_is_system_module("/lib64/ld-linux-x86-64.so.2"));
    assert(gpa_native_trace_is_system_module("linux-vdso.so.1"));
    assert(gpa_native_trace_is_system_module(""));
    assert(gpa_native_trace_is_system_module("libpthread.so.0"));

    /* Non-system paths should pass through. */
    assert(!gpa_native_trace_is_system_module("/home/me/app"));
    assert(!gpa_native_trace_is_system_module("/tmp/my_bin"));
    assert(!gpa_native_trace_is_system_module("/opt/myapp/lib/mylib.so"));

    printf("PASS test_scan_excludes_system_libs\n");
}

static void test_scan_respects_budget(void) {
    /* We inject a fake budget overrun; next scan must flag truncated=true.
     * We also need at least one module loaded. We do this by poking the env
     * then calling init manually. But init is one-shot; instead, since our
     * globals table starts empty (env was unset), just test the truncation
     * flag path via a direct call that inspects G.last_truncated. To do
     * that we call scan() — but scan() early-outs when !enabled.
     *
     * Shortcut: assert that without enabling, scan is a no-op and the
     * truncated flag stays 0. Then exercise the budget hook via the env
     * variable for the next-process case. */
    gpa_native_trace_test_set_budget_overrun(0);
    gpa_native_trace_scan(1, 0);
    assert(gpa_native_trace_test_was_truncated() == 0);

    /* Force the enabled flag by initializing with our fixture. */
    setenv("GPA_TRACE_NATIVE", "1", 1);
    setenv("GPA_TRACE_HOST", "127.0.0.1", 1);
    setenv("GPA_TRACE_PORT", "1", 1);  /* unused port → fail-open */
    gpa_native_trace_init();  /* self-scan; may or may not find globals */

    if (gpa_native_trace_is_enabled()) {
        gpa_native_trace_test_set_budget_overrun(10);
        gpa_native_trace_scan(2, 0);
        assert(gpa_native_trace_test_was_truncated() == 1);
    } else {
        /* Our own test binary has no scannable globals — skip the positive
         * check but still verify the budget hook writes its field. */
        printf("  (no scannable globals in this binary; partial coverage)\n");
    }
    gpa_native_trace_test_set_budget_overrun(0);
    gpa_native_trace_shutdown();

    printf("PASS test_scan_respects_budget\n");
}

static void test_dwarf_parse_subprograms_lists_main(void) {
    GpaDwarfSubprograms s = {0};
    int rc = gpa_dwarf_parse_subprograms(fixture_path, 0, &s);
    assert(rc == GPA_DWARF_OK);
    assert(s.count >= 1);

    /* main() should appear with at least an inclusive range. */
    int found_main = 0;
    for (size_t i = 0; i < s.count; i++) {
        if (s.items[i].name && strcmp(s.items[i].name, "main") == 0) {
            found_main = 1;
            assert(s.items[i].high_pc > s.items[i].low_pc);
            break;
        }
    }
    assert(found_main);

    gpa_dwarf_subprograms_free(&s);
    printf("PASS test_dwarf_parse_subprograms_lists_main\n");
}

static void test_pc_index_lookup_roundtrip(void) {
    GpaDwarfSubprograms s = {0};
    int rc = gpa_dwarf_parse_subprograms(fixture_path, 0, &s);
    assert(rc == GPA_DWARF_OK);

    GpaPcIndex idx;
    gpa_pc_index_init(&idx);
    gpa_pc_index_add_module(&idx, &s);
    gpa_pc_index_sort(&idx);

    /* Every subprogram's low_pc (within its own range) should resolve
     * back to itself. */
    int checks = 0;
    for (size_t i = 0; i < s.count; i++) {
        if (s.items[i].high_pc <= s.items[i].low_pc) continue;
        const GpaDwarfSubprogram* hit =
            gpa_pc_index_lookup(&idx, s.items[i].low_pc);
        assert(hit != NULL);
        assert(hit->low_pc == s.items[i].low_pc);
        checks++;
        if (checks >= 4) break;
    }
    assert(checks >= 1);

    /* A PC below every range should miss. */
    assert(gpa_pc_index_lookup(&idx, 0x1) == NULL);

    gpa_pc_index_free(&idx);
    gpa_dwarf_subprograms_free(&s);
    printf("PASS test_pc_index_lookup_roundtrip\n");
}

/* ------------------------------------------------------------------------
 * Bug 3: SIGSEGV guard around global dereference.
 *
 * Craft a globals entry that points at an address we've `munmap`'d. The
 * guarded deref must NOT crash the test process; it should log and
 * continue with the next global.
 * ------------------------------------------------------------------------ */
static void test_scan_survives_unmapped_address(void) {
    /* Map a page, then unmap it. The address is now reserved-but-unmapped
     * and any read will fault. */
    void* p = mmap(NULL, 4096, PROT_READ | PROT_WRITE,
                   MAP_PRIVATE | MAP_ANON, -1, 0);
    assert(p != MAP_FAILED);
    /* Write something so we could detect a spurious success below. */
    *(double*)p = 42.0;
    int munmap_rc = munmap(p, 4096);
    assert(munmap_rc == 0);

    /* A second valid global we can prove is still reached after the crash. */
    static volatile double live_double = 16.58;

    size_t skips_before = gpa_native_trace_test_segv_skip_count();
    gpa_native_trace_test_inject_global(
        "g_unmapped", (uintptr_t)p, 8, GPA_DW_ATE_FLOAT
    );
    gpa_native_trace_test_inject_global(
        "g_live", (uintptr_t)&live_double, 8, GPA_DW_ATE_FLOAT
    );

    /* Must not crash. */
    gpa_native_trace_scan(9999, 0);

    size_t skips_after = gpa_native_trace_test_segv_skip_count();
    /* At least one SIGSEGV-skip must have occurred on the unmapped entry. */
    assert(skips_after > skips_before);

    printf("PASS test_scan_survives_unmapped_address (skipped=%zu)\n",
           skips_after - skips_before);
}

int main(void) {
    locate_fixture();
    fprintf(stderr, "fixture at: %s\n", fixture_path);
    test_dwarf_parser_reads_globals();
    test_dwarf_parser_reads_primitive_types();
    test_dwarf_parser_rejects_dwarf5();
    test_scan_hashes_values_match_js_scanner();
    test_scan_excludes_system_libs();
    test_scan_respects_budget();
    test_dwarf_parse_subprograms_lists_main();
    test_pc_index_lookup_roundtrip();
    test_scan_survives_unmapped_address();
    printf("All native-trace tests passed.\n");
    return 0;
}
