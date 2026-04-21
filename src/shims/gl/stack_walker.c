/* Stack-walker wrapper around libunwind for Phase 2 of `gpa trace`.
 *
 * Design:
 *   - We use the "local" libunwind backend (`unw_context_t` captured in-
 *     process; no remote ptrace). This keeps overhead low and avoids the
 *     complications of accessing a sibling's memory.
 *   - For each frame we copy the 17 GP registers we care about into a
 *     flat array + a CFA value. `DW_OP_fbreg` is relative to CFA on x86-64
 *     SysV for every mainstream compiler (gcc/clang). If the function uses
 *     a non-CFA frame base, the location eval will simply fail for that
 *     variable and we skip it — not fatal.
 *   - Proc names are cached into a per-snapshot string pool so callers can
 *     keep the pointers around without worrying about libunwind's own
 *     internal buffer lifetimes. */

#define _GNU_SOURCE
#include "stack_walker.h"

#include <stdlib.h>
#include <string.h>

#if defined(__x86_64__)
#include <libunwind.h>

/* Map DWARF register numbers (0..16) to libunwind's UNW_X86_64_*. */
static int dwarf_to_unw_reg(int dw) {
    switch (dw) {
    case GPA_REG_RAX: return UNW_X86_64_RAX;
    case GPA_REG_RDX: return UNW_X86_64_RDX;
    case GPA_REG_RCX: return UNW_X86_64_RCX;
    case GPA_REG_RBX: return UNW_X86_64_RBX;
    case GPA_REG_RSI: return UNW_X86_64_RSI;
    case GPA_REG_RDI: return UNW_X86_64_RDI;
    case GPA_REG_RBP: return UNW_X86_64_RBP;
    case GPA_REG_RSP: return UNW_X86_64_RSP;
    case GPA_REG_R8:  return UNW_X86_64_R8;
    case GPA_REG_R9:  return UNW_X86_64_R9;
    case GPA_REG_R10: return UNW_X86_64_R10;
    case GPA_REG_R11: return UNW_X86_64_R11;
    case GPA_REG_R12: return UNW_X86_64_R12;
    case GPA_REG_R13: return UNW_X86_64_R13;
    case GPA_REG_R14: return UNW_X86_64_R14;
    case GPA_REG_R15: return UNW_X86_64_R15;
    case GPA_REG_RIP: return UNW_X86_64_RIP;
    default:          return -1;
    }
}

static const char* strpool_dup(GpaStackSnapshot* s, const char* src, size_t n) {
    if (s->strpool_len + n + 1 > s->strpool_cap) {
        size_t nc = s->strpool_cap ? s->strpool_cap * 2 : 512;
        while (nc < s->strpool_len + n + 1) nc *= 2;
        char* nb = (char*)realloc(s->strpool, nc);
        if (!nb) return NULL;
        /* Rebase previously stored proc_name pointers if the pool moved. */
        if (nb != s->strpool && s->strpool) {
            ptrdiff_t delta = nb - s->strpool;
            for (size_t i = 0; i < s->frame_count; i++) {
                if (s->frames[i].proc_name) {
                    s->frames[i].proc_name += delta;
                }
            }
        }
        s->strpool = nb;
        s->strpool_cap = nc;
    }
    char* dst = s->strpool + s->strpool_len;
    memcpy(dst, src, n);
    dst[n] = '\0';
    s->strpool_len += n + 1;
    return dst;
}

int gpa_stack_walk_current(GpaStackSnapshot* out) {
    memset(out, 0, sizeof(*out));

    unw_context_t uc;
    if (unw_getcontext(&uc) != 0) return 0;
    unw_cursor_t cursor;
    if (unw_init_local(&cursor, &uc) != 0) return 0;

    while (out->frame_count < GPA_STACK_MAX_FRAMES) {
        GpaStackFrame* f = &out->frames[out->frame_count];

        unw_word_t pc = 0, cfa = 0;
        if (unw_get_reg(&cursor, UNW_REG_IP, &pc) != 0) break;
        if (pc == 0) break;
        f->pc = (uintptr_t)pc;

        /* CFA is exposed as UNW_X86_64_RSP *after* the prologue if libunwind
         * followed standard DWARF CFI; more reliably we use UNW_REG_SP on
         * the caller side. Use UNW_X86_64_RSP at this frame as an
         * approximation (DWARF CFA in most prologues equals RSP + offset
         * but compilers emit the correction in CFI, which libunwind has
         * already applied to yield the call-site RSP here). */
        if (unw_get_reg(&cursor, UNW_REG_SP, &cfa) == 0) {
            f->cfa = (uintptr_t)cfa;
        }

        /* Copy the GP register file. */
        for (int dw = 0; dw < GPA_STACK_REG_COUNT; dw++) {
            int uw = dwarf_to_unw_reg(dw);
            if (uw < 0) continue;
            unw_word_t v = 0;
            if (unw_get_reg(&cursor, uw, &v) == 0) {
                f->registers[dw] = (uintptr_t)v;
                f->reg_valid[dw] = 1;
            }
        }

        /* Proc name — best effort. */
        char namebuf[256];
        unw_word_t off = 0;
        int rc = unw_get_proc_name(&cursor, namebuf, sizeof(namebuf), &off);
        if (rc == 0 || rc == -UNW_ENOMEM) {
            /* -UNW_ENOMEM = name was truncated into namebuf but still valid. */
            namebuf[sizeof(namebuf) - 1] = '\0';
            size_t nl = strlen(namebuf);
            f->proc_name = strpool_dup(out, namebuf, nl);
            f->proc_offset = (uintptr_t)off;
        }

        out->frame_count++;

        int step = unw_step(&cursor);
        if (step <= 0) break;
    }
    return 0;
}

void gpa_stack_snapshot_free(GpaStackSnapshot* s) {
    if (!s) return;
    free(s->strpool);
    memset(s, 0, sizeof(*s));
}

#else  /* !__x86_64__ */

/* Non-x86_64 builds: the walker compiles as a no-op. The DWARF register-
 * number mapping we use, the CFA + GP-register snapshot, and all the
 * libunwind register enums are x86_64-specific. Rather than ifdef-ing
 * dozens of sites, we just fail the walk cleanly on other arches — the
 * driver already treats an empty snapshot as "stack trace unavailable".
 *
 * Documented in docs/gpa-trace-native-usage.md (stack-scan section). */

#include <stdio.h>

int gpa_stack_walk_current(GpaStackSnapshot* out) {
    memset(out, 0, sizeof(*out));
    static int warned = 0;
    if (!warned) {
        warned = 1;
        fprintf(stderr,
                "[OpenGPA] native-trace: stack trace unavailable on this "
                "architecture (x86_64 only)\n");
    }
    return 0;
}

void gpa_stack_snapshot_free(GpaStackSnapshot* s) {
    if (!s) return;
    free(s->strpool);
    memset(s, 0, sizeof(*s));
}

#endif  /* __x86_64__ */
