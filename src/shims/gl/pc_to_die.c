#define _GNU_SOURCE
#include "pc_to_die.h"

#include <stdlib.h>
#include <string.h>

void gpa_pc_index_init(GpaPcIndex* idx) {
    memset(idx, 0, sizeof(*idx));
}

void gpa_pc_index_add_module(GpaPcIndex* idx, const GpaDwarfSubprograms* subs) {
    if (!idx || !subs) return;
    size_t need = idx->count + subs->count;
    if (need > idx->cap) {
        size_t nc = idx->cap ? idx->cap : 64;
        while (nc < need) nc *= 2;
        GpaPcRange* nb = (GpaPcRange*)realloc(idx->ranges,
                                               nc * sizeof(GpaPcRange));
        if (!nb) return;
        idx->ranges = nb; idx->cap = nc;
    }
    for (size_t i = 0; i < subs->count; i++) {
        const GpaDwarfSubprogram* sp = &subs->items[i];
        /* Skip empty ranges (declaration-only or unresolved high_pc). */
        if (sp->high_pc <= sp->low_pc) continue;
        idx->ranges[idx->count++] = (GpaPcRange){
            .low_pc = sp->low_pc,
            .high_pc = sp->high_pc,
            .sub = sp,
        };
    }
}

static int cmp_range(const void* a, const void* b) {
    const GpaPcRange* ra = (const GpaPcRange*)a;
    const GpaPcRange* rb = (const GpaPcRange*)b;
    if (ra->low_pc < rb->low_pc) return -1;
    if (ra->low_pc > rb->low_pc) return  1;
    return 0;
}

void gpa_pc_index_sort(GpaPcIndex* idx) {
    if (!idx || idx->count < 2) return;
    qsort(idx->ranges, idx->count, sizeof(GpaPcRange), cmp_range);
}

const GpaDwarfSubprogram* gpa_pc_index_lookup(const GpaPcIndex* idx,
                                              uintptr_t pc) {
    if (!idx || idx->count == 0) return NULL;
    /* Binary search for the largest low_pc <= pc, then bounds check. Ranges
     * can overlap (inlined subroutines nested in parents) — we take the
     * first match for simplicity. */
    size_t lo = 0, hi = idx->count;
    while (lo < hi) {
        size_t mid = lo + (hi - lo) / 2;
        if (idx->ranges[mid].low_pc <= pc) lo = mid + 1;
        else hi = mid;
    }
    if (lo == 0) return NULL;
    size_t k = lo - 1;
    const GpaPcRange* r = &idx->ranges[k];
    if (pc >= r->low_pc && pc < r->high_pc) return r->sub;
    return NULL;
}

void gpa_pc_index_free(GpaPcIndex* idx) {
    if (!idx) return;
    free(idx->ranges);
    memset(idx, 0, sizeof(*idx));
}
