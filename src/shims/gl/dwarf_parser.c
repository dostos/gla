/* Minimal hand-rolled DWARF parser — Phase 1 of OpenGPA native trace.
 *
 * Parses .debug_info + .debug_abbrev + .debug_str (and debug_str_offsets
 * for v4 with .debug_line_str; best-effort) just enough to extract:
 *   - DW_TAG_variable with DW_AT_location = DW_OP_addr <addr>  (globals/statics)
 *   - Type chain → DW_AT_encoding, DW_AT_byte_size
 *
 * DWARF v3 and v4. DWARF v5 is detected and rejected with
 * GPA_DWARF_UNSUPPORTED_VERSION so the caller can log and move on.
 *
 * Design choices:
 *  - We mmap the ELF file once, walk section headers, point to the three
 *    .debug_* sections. Everything else is pure pointer arithmetic.
 *  - Abbreviation table for each compilation unit is decoded into a small
 *    heap-allocated array keyed by abbrev code.
 *  - DIE tree walk is recursive descent, bounded by CU size; we only recurse
 *    as deep as needed to find base types referenced by variables.
 *  - We keep it intentionally small. If any DIE form we don't know shows up,
 *    we skip it (not error) — we only fail hard on truncated input or
 *    unsupported DWARF versions.
 */

#define _GNU_SOURCE
#include "dwarf_parser.h"

#include <elf.h>
#include <fcntl.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/mman.h>
#include <sys/stat.h>
#include <unistd.h>

/* ---- DWARF constants we actually use ----------------------------------- */

/* Tags */
#define DW_TAG_array_type         0x01
#define DW_TAG_class_type         0x02
#define DW_TAG_formal_parameter   0x05
#define DW_TAG_compile_unit       0x11
#define DW_TAG_structure_type     0x13
#define DW_TAG_typedef            0x16
#define DW_TAG_union_type         0x17
#define DW_TAG_base_type          0x24
#define DW_TAG_const_type         0x26
#define DW_TAG_subprogram         0x2e
#define DW_TAG_volatile_type      0x35
#define DW_TAG_variable           0x34
#define DW_TAG_namespace          0x39

/* Attribute names */
#define DW_AT_sibling             0x01
#define DW_AT_location            0x02
#define DW_AT_name                0x03
#define DW_AT_byte_size           0x0b
#define DW_AT_language            0x13
#define DW_AT_low_pc              0x11
#define DW_AT_high_pc             0x12
#define DW_AT_encoding            0x3e
#define DW_AT_type                0x49
#define DW_AT_declaration         0x3c
#define DW_AT_specification       0x47
#define DW_AT_linkage_name        0x6e
#define DW_AT_MIPS_linkage_name   0x2007

/* Forms */
#define DW_FORM_addr              0x01
#define DW_FORM_block2            0x03
#define DW_FORM_block4            0x04
#define DW_FORM_data2             0x05
#define DW_FORM_data4             0x06
#define DW_FORM_data8             0x07
#define DW_FORM_string            0x08
#define DW_FORM_block             0x09
#define DW_FORM_block1            0x0a
#define DW_FORM_data1             0x0b
#define DW_FORM_flag              0x0c
#define DW_FORM_sdata             0x0d
#define DW_FORM_strp              0x0e
#define DW_FORM_udata             0x0f
#define DW_FORM_ref_addr          0x10
#define DW_FORM_ref1              0x11
#define DW_FORM_ref2              0x12
#define DW_FORM_ref4              0x13
#define DW_FORM_ref8              0x14
#define DW_FORM_ref_udata         0x15
#define DW_FORM_indirect          0x16
#define DW_FORM_sec_offset        0x17   /* DWARF 4 */
#define DW_FORM_exprloc           0x18   /* DWARF 4 */
#define DW_FORM_flag_present      0x19   /* DWARF 4 */
#define DW_FORM_ref_sig8          0x20   /* DWARF 4 */

/* Location ops */
#define DW_OP_addr                0x03

/* ---- ELF section table ------------------------------------------------- */

typedef struct {
    const uint8_t* data;
    size_t         size;
} DwSection;

typedef struct {
    int        fd;
    void*      map;
    size_t     map_size;
    DwSection  info;
    DwSection  abbrev;
    DwSection  str;
    DwSection  line_str; /* DWARF4+ optional */
} DwFile;

/* ---- small helpers ----------------------------------------------------- */

static uint16_t rd_u16(const uint8_t* p) {
    return (uint16_t)p[0] | ((uint16_t)p[1] << 8);
}
static uint32_t rd_u32(const uint8_t* p) {
    return (uint32_t)p[0] | ((uint32_t)p[1] << 8) |
           ((uint32_t)p[2] << 16) | ((uint32_t)p[3] << 24);
}
static uint64_t rd_u64(const uint8_t* p) {
    return (uint64_t)rd_u32(p) | ((uint64_t)rd_u32(p + 4) << 32);
}

/* LEB128 — advance *p (bounded by `end`). Returns 0 on underflow. */
static int rd_uleb(const uint8_t** p, const uint8_t* end, uint64_t* out) {
    uint64_t r = 0; int shift = 0;
    while (*p < end) {
        uint8_t b = *(*p)++;
        r |= (uint64_t)(b & 0x7f) << shift;
        if ((b & 0x80) == 0) { *out = r; return 1; }
        shift += 7;
        if (shift > 63) return 0;
    }
    return 0;
}
static int rd_sleb(const uint8_t** p, const uint8_t* end, int64_t* out) {
    int64_t r = 0; int shift = 0; uint8_t b = 0;
    while (*p < end) {
        b = *(*p)++;
        r |= (int64_t)(b & 0x7f) << shift;
        shift += 7;
        if ((b & 0x80) == 0) break;
        if (shift > 63) return 0;
    }
    if (shift < 64 && (b & 0x40)) r |= -((int64_t)1 << shift);
    *out = r; return 1;
}

const char* gpa_dwarf_strerror(int err) {
    switch (err) {
        case GPA_DWARF_OK: return "ok";
        case GPA_DWARF_ERR_OPEN: return "open failed";
        case GPA_DWARF_ERR_NOT_ELF: return "not a 64-bit ELF";
        case GPA_DWARF_ERR_NO_DEBUG_INFO: return "no .debug_info";
        case GPA_DWARF_UNSUPPORTED_VERSION: return "unsupported DWARF version";
        case GPA_DWARF_ERR_MALFORMED: return "malformed DWARF";
    }
    return "unknown";
}

/* ---- ELF mmap + section lookup ----------------------------------------- */

static int dwfile_open(DwFile* f, const char* path) {
    memset(f, 0, sizeof(*f));
    f->fd = open(path, O_RDONLY | O_CLOEXEC);
    if (f->fd < 0) return GPA_DWARF_ERR_OPEN;

    struct stat st;
    if (fstat(f->fd, &st) < 0 || st.st_size < (off_t)sizeof(Elf64_Ehdr)) {
        close(f->fd); f->fd = -1;
        return GPA_DWARF_ERR_OPEN;
    }
    f->map_size = (size_t)st.st_size;
    f->map = mmap(NULL, f->map_size, PROT_READ, MAP_PRIVATE, f->fd, 0);
    if (f->map == MAP_FAILED) {
        close(f->fd); f->fd = -1;
        return GPA_DWARF_ERR_OPEN;
    }

    const Elf64_Ehdr* eh = (const Elf64_Ehdr*)f->map;
    if (memcmp(eh->e_ident, ELFMAG, SELFMAG) != 0 ||
        eh->e_ident[EI_CLASS] != ELFCLASS64) {
        return GPA_DWARF_ERR_NOT_ELF;
    }
    if ((size_t)eh->e_shoff + (size_t)eh->e_shnum * sizeof(Elf64_Shdr) >
        f->map_size) return GPA_DWARF_ERR_NOT_ELF;

    const Elf64_Shdr* sh = (const Elf64_Shdr*)((const uint8_t*)f->map + eh->e_shoff);
    const Elf64_Shdr* shstr = &sh[eh->e_shstrndx];
    if ((size_t)shstr->sh_offset + (size_t)shstr->sh_size > f->map_size)
        return GPA_DWARF_ERR_NOT_ELF;
    const char* strtab = (const char*)f->map + shstr->sh_offset;

    for (int i = 0; i < eh->e_shnum; i++) {
        const char* name = strtab + sh[i].sh_name;
        if ((size_t)sh[i].sh_offset + (size_t)sh[i].sh_size > f->map_size)
            continue;
        const uint8_t* data = (const uint8_t*)f->map + sh[i].sh_offset;
        size_t size = (size_t)sh[i].sh_size;
        if      (strcmp(name, ".debug_info")   == 0) { f->info   = (DwSection){data, size}; }
        else if (strcmp(name, ".debug_abbrev") == 0) { f->abbrev = (DwSection){data, size}; }
        else if (strcmp(name, ".debug_str")    == 0) { f->str    = (DwSection){data, size}; }
        else if (strcmp(name, ".debug_line_str") == 0) { f->line_str = (DwSection){data, size}; }
    }
    if (f->info.size == 0 || f->abbrev.size == 0)
        return GPA_DWARF_ERR_NO_DEBUG_INFO;
    return GPA_DWARF_OK;
}

static void dwfile_close(DwFile* f) {
    if (f->map && f->map != MAP_FAILED) munmap(f->map, f->map_size);
    if (f->fd >= 0) close(f->fd);
    memset(f, 0, sizeof(*f));
}

/* ---- Abbrev table ------------------------------------------------------ */

typedef struct {
    uint64_t name;
    uint64_t form;
} DwAttrSpec;

typedef struct {
    uint64_t code;
    uint64_t tag;
    int      has_children;
    DwAttrSpec* attrs;
    size_t   attr_count;
} DwAbbrev;

typedef struct {
    DwAbbrev* items;
    size_t    count;
    size_t    cap;
} DwAbbrevTable;

static void abbrev_free(DwAbbrevTable* t) {
    for (size_t i = 0; i < t->count; i++) free(t->items[i].attrs);
    free(t->items);
    memset(t, 0, sizeof(*t));
}

static DwAbbrev* abbrev_find(const DwAbbrevTable* t, uint64_t code) {
    /* Linear scan; abbrev tables are typically small (< 100 entries). */
    for (size_t i = 0; i < t->count; i++) {
        if (t->items[i].code == code) return &t->items[i];
    }
    return NULL;
}

static int abbrev_parse(DwAbbrevTable* out,
                        const uint8_t* p, const uint8_t* end) {
    memset(out, 0, sizeof(*out));
    while (p < end) {
        uint64_t code;
        if (!rd_uleb(&p, end, &code)) return GPA_DWARF_ERR_MALFORMED;
        if (code == 0) break;
        uint64_t tag;
        if (!rd_uleb(&p, end, &tag)) return GPA_DWARF_ERR_MALFORMED;
        if (p >= end) return GPA_DWARF_ERR_MALFORMED;
        int has_children = (*p++ != 0);

        DwAbbrev a = {code, tag, has_children, NULL, 0};
        size_t acap = 0;
        for (;;) {
            uint64_t an, af;
            if (!rd_uleb(&p, end, &an) || !rd_uleb(&p, end, &af))
                { free(a.attrs); return GPA_DWARF_ERR_MALFORMED; }
            if (an == 0 && af == 0) break;
            if (a.attr_count == acap) {
                acap = acap ? acap * 2 : 8;
                a.attrs = (DwAttrSpec*)realloc(a.attrs, acap * sizeof(DwAttrSpec));
            }
            a.attrs[a.attr_count++] = (DwAttrSpec){an, af};
        }

        if (out->count == out->cap) {
            out->cap = out->cap ? out->cap * 2 : 16;
            out->items = (DwAbbrev*)realloc(out->items, out->cap * sizeof(DwAbbrev));
        }
        out->items[out->count++] = a;
    }
    return GPA_DWARF_OK;
}

/* ---- Form reader ------------------------------------------------------- */

typedef struct {
    /* For forms we care about, we parse into these. */
    int        has_addr;       uint64_t  addr;
    int        has_ref;        uint64_t  ref;      /* CU-relative DIE offset */
    int        has_uconst;     uint64_t  uconst;
    int        has_sconst;     int64_t   sconst;
    int        has_string;     const char* str;
    int        has_block;      const uint8_t* block; size_t block_len;
    int        has_flag;       int flag;
} DwFormVal;

/* Read an attribute value for `form`, advancing *p. `cu_base` points to the
 * start of the CU DIE stream (for ref* forms). `cu_addr_size` is the address
 * byte size stated in the CU header. Returns 0 on malformed input. */
static int read_form(uint64_t form,
                     const uint8_t** p, const uint8_t* end,
                     const uint8_t* cu_base, size_t cu_size,
                     uint8_t addr_size,
                     const DwFile* file,
                     DwFormVal* out) {
    (void)cu_base; (void)cu_size;
    memset(out, 0, sizeof(*out));

    /* DW_FORM_indirect wraps another form */
    if (form == DW_FORM_indirect) {
        uint64_t real;
        if (!rd_uleb(p, end, &real)) return 0;
        return read_form(real, p, end, cu_base, cu_size, addr_size, file, out);
    }

    switch (form) {
    case DW_FORM_addr:
        if (*p + addr_size > end) return 0;
        out->has_addr = 1;
        if (addr_size == 8) out->addr = rd_u64(*p);
        else if (addr_size == 4) out->addr = rd_u32(*p);
        else return 0;
        *p += addr_size;
        return 1;
    case DW_FORM_data1: case DW_FORM_ref1: case DW_FORM_flag:
        if (*p + 1 > end) return 0;
        out->has_uconst = 1; out->uconst = *(*p)++;
        if (form == DW_FORM_ref1) { out->has_ref = 1; out->ref = out->uconst; }
        if (form == DW_FORM_flag) { out->has_flag = 1; out->flag = (int)out->uconst; }
        return 1;
    case DW_FORM_data2: case DW_FORM_ref2:
        if (*p + 2 > end) return 0;
        out->has_uconst = 1; out->uconst = rd_u16(*p);
        if (form == DW_FORM_ref2) { out->has_ref = 1; out->ref = out->uconst; }
        *p += 2; return 1;
    case DW_FORM_data4: case DW_FORM_ref4:
        if (*p + 4 > end) return 0;
        out->has_uconst = 1; out->uconst = rd_u32(*p);
        if (form == DW_FORM_ref4) { out->has_ref = 1; out->ref = out->uconst; }
        *p += 4; return 1;
    case DW_FORM_data8: case DW_FORM_ref8:
        if (*p + 8 > end) return 0;
        out->has_uconst = 1; out->uconst = rd_u64(*p);
        if (form == DW_FORM_ref8) { out->has_ref = 1; out->ref = out->uconst; }
        *p += 8; return 1;
    case DW_FORM_sdata: {
        int64_t v; if (!rd_sleb(p, end, &v)) return 0;
        out->has_sconst = 1; out->sconst = v; return 1;
    }
    case DW_FORM_udata: case DW_FORM_ref_udata: {
        uint64_t v; if (!rd_uleb(p, end, &v)) return 0;
        out->has_uconst = 1; out->uconst = v;
        if (form == DW_FORM_ref_udata) { out->has_ref = 1; out->ref = v; }
        return 1;
    }
    case DW_FORM_string: {
        const char* s = (const char*)*p;
        while (*p < end && **p) (*p)++;
        if (*p >= end) return 0;
        (*p)++; /* nul */
        out->has_string = 1; out->str = s; return 1;
    }
    case DW_FORM_strp: {
        if (*p + 4 > end) return 0;
        uint32_t off = rd_u32(*p); *p += 4;
        if (off < file->str.size) {
            out->has_string = 1;
            out->str = (const char*)file->str.data + off;
        }
        return 1;
    }
    case DW_FORM_block1: {
        if (*p + 1 > end) return 0;
        uint8_t len = *(*p)++;
        if (*p + len > end) return 0;
        out->has_block = 1; out->block = *p; out->block_len = len;
        *p += len; return 1;
    }
    case DW_FORM_block2: {
        if (*p + 2 > end) return 0;
        uint16_t len = rd_u16(*p); *p += 2;
        if (*p + len > end) return 0;
        out->has_block = 1; out->block = *p; out->block_len = len;
        *p += len; return 1;
    }
    case DW_FORM_block4: {
        if (*p + 4 > end) return 0;
        uint32_t len = rd_u32(*p); *p += 4;
        if (*p + len > end) return 0;
        out->has_block = 1; out->block = *p; out->block_len = len;
        *p += len; return 1;
    }
    case DW_FORM_block:
    case DW_FORM_exprloc: {
        uint64_t len;
        if (!rd_uleb(p, end, &len)) return 0;
        if (*p + len > end) return 0;
        out->has_block = 1; out->block = *p; out->block_len = (size_t)len;
        *p += len; return 1;
    }
    case DW_FORM_flag_present:
        out->has_flag = 1; out->flag = 1; return 1;
    case DW_FORM_sec_offset:
        if (*p + 4 > end) return 0;
        out->has_uconst = 1; out->uconst = rd_u32(*p); *p += 4; return 1;
    case DW_FORM_ref_addr:
        if (*p + 4 > end) return 0;
        out->has_uconst = 1; out->uconst = rd_u32(*p); *p += 4; return 1;
    case DW_FORM_ref_sig8:
        if (*p + 8 > end) return 0;
        *p += 8; return 1;
    default:
        /* Unknown form — bail. Caller will error. */
        return 0;
    }
}

/* ---- Type resolver ----------------------------------------------------- */
/* Follow a chain of typedef/const/volatile DIEs to the underlying base type
 * and extract byte_size + encoding. We parse the CU on demand: given a
 * CU-relative DIE offset, walk from the CU header back to that DIE. */

typedef struct {
    const uint8_t* cu_base; /* start of CU header (for ref-form offsets) */
    const uint8_t* data;   /* pointer to first DIE in CU */
    const uint8_t* end;    /* end of CU */
    const DwAbbrevTable* ab;
    uint8_t addr_size;
} CuView;

static int resolve_type(const CuView* cu, const DwFile* file,
                        uint64_t die_off, /* CU-relative offset */
                        uint64_t* out_size, uint32_t* out_enc);

static int walk_die_at(const CuView* cu, const DwFile* file,
                       const uint8_t* die_ptr,
                       uint64_t* out_size, uint32_t* out_enc,
                       uint64_t* out_ref) {
    const uint8_t* p = die_ptr;
    const uint8_t* end = cu->end;
    uint64_t code;
    if (!rd_uleb(&p, end, &code)) return 0;
    if (code == 0) return 0;
    DwAbbrev* ab = abbrev_find(cu->ab, code);
    if (!ab) return 0;

    uint64_t byte_size = 0; uint32_t encoding = 0; uint64_t type_ref = 0;
    int have_size = 0, have_enc = 0, have_ref = 0;
    for (size_t i = 0; i < ab->attr_count; i++) {
        DwFormVal v;
        if (!read_form(ab->attrs[i].form, &p, end,
                       cu->data, (size_t)(cu->end - cu->data),
                       cu->addr_size, file, &v)) return 0;
        switch (ab->attrs[i].name) {
        case DW_AT_byte_size: if (v.has_uconst) { byte_size = v.uconst; have_size = 1; } break;
        case DW_AT_encoding:  if (v.has_uconst) { encoding  = (uint32_t)v.uconst; have_enc = 1; } break;
        case DW_AT_type:      if (v.has_ref) { type_ref = v.ref; have_ref = 1; } break;
        default: break;
        }
    }
    if (ab->tag == DW_TAG_base_type) {
        if (have_size) *out_size = byte_size;
        if (have_enc)  *out_enc  = encoding;
        return 1;
    }
    /* const/typedef/volatile wrappers — follow .type */
    if ((ab->tag == DW_TAG_typedef || ab->tag == DW_TAG_const_type ||
         ab->tag == DW_TAG_volatile_type) && have_ref) {
        *out_ref = type_ref;
        return 2;
    }
    /* Aggregate (struct/class/union/array) — capture size only. */
    if (have_size) { *out_size = byte_size; *out_enc = 0; return 1; }
    return 0;
}

static int resolve_type(const CuView* cu, const DwFile* file,
                        uint64_t die_off,
                        uint64_t* out_size, uint32_t* out_enc) {
    /* DW_FORM_ref* offsets are from the CU header start, not the first DIE.
     * Prevent pathological cycles. */
    for (int depth = 0; depth < 16; depth++) {
        const uint8_t* target = cu->cu_base + die_off;
        if (target < cu->data || target >= cu->end) return 0;
        uint64_t ref = 0;
        int rc = walk_die_at(cu, file, target, out_size, out_enc, &ref);
        if (rc == 1) return 1;
        if (rc == 2) { die_off = ref; continue; }
        return 0;
    }
    return 0;
}

/* ---- CU walker --------------------------------------------------------- */

static int globals_push(GpaDwarfGlobals* g, const char* name,
                        uintptr_t addr, uint64_t size, uint32_t enc) {
    size_t nlen = strlen(name);
    if (g->strpool_len + nlen + 1 > g->strpool_cap) {
        size_t nc = g->strpool_cap ? g->strpool_cap * 2 : 4096;
        while (nc < g->strpool_len + nlen + 1) nc *= 2;
        char* nb = (char*)realloc(g->strpool, nc);
        if (!nb) return 0;
        /* Relocate previously stored name pointers. Since name entries
         * point into the old pool, we must rebase them. */
        if (nb != g->strpool) {
            ptrdiff_t delta = nb - g->strpool;
            for (size_t i = 0; i < g->count; i++) {
                g->items[i].name = (g->items[i].name ? g->items[i].name + delta : NULL);
            }
        }
        g->strpool = nb; g->strpool_cap = nc;
    }
    char* slot = g->strpool + g->strpool_len;
    memcpy(slot, name, nlen); slot[nlen] = '\0';
    g->strpool_len += nlen + 1;

    if (g->count == g->cap) {
        size_t nc = g->cap ? g->cap * 2 : 32;
        GpaDwarfGlobal* nb = (GpaDwarfGlobal*)realloc(g->items,
                                                      nc * sizeof(GpaDwarfGlobal));
        if (!nb) return 0;
        g->items = nb; g->cap = nc;
    }
    g->items[g->count++] = (GpaDwarfGlobal){slot, addr, size, enc};
    return 1;
}

static int parse_cu(const DwFile* file,
                    const uint8_t* cu_start, const uint8_t* cu_end,
                    uintptr_t load_bias,
                    GpaDwarfGlobals* out) {
    /* CU header. We assume 32-bit DWARF. */
    if (cu_start + 11 > cu_end) return GPA_DWARF_ERR_MALFORMED;
    uint32_t len = rd_u32(cu_start);
    if (len == 0xffffffff) return GPA_DWARF_ERR_MALFORMED; /* 64-bit DWARF unsupported */
    uint16_t version = rd_u16(cu_start + 4);
    if (version == 5) return GPA_DWARF_UNSUPPORTED_VERSION;
    if (version < 2 || version > 4) return GPA_DWARF_UNSUPPORTED_VERSION;
    uint32_t abbrev_off = rd_u32(cu_start + 6);
    uint8_t  addr_size  = cu_start[10];

    const uint8_t* die_start = cu_start + 11;
    const uint8_t* die_end   = cu_start + 4 + len; /* length field excludes its own 4 bytes */
    if (die_end > cu_end) die_end = cu_end;

    /* Parse abbrev table for this CU. */
    if (abbrev_off >= file->abbrev.size) return GPA_DWARF_ERR_MALFORMED;
    DwAbbrevTable tab;
    int rc = abbrev_parse(&tab,
                          file->abbrev.data + abbrev_off,
                          file->abbrev.data + file->abbrev.size);
    if (rc != GPA_DWARF_OK) return rc;

    CuView cu = {cu_start, die_start, die_end, &tab, addr_size};

    /* Walk DIEs flat — we don't need structural nesting for globals. */
    const uint8_t* p = die_start;
    /* Track depth to skip descent when abbrev says no_children. */
    int depth = 0;
    while (p < die_end) {
        const uint8_t* die_ptr = p;
        uint64_t die_off = (uint64_t)(die_ptr - die_start);
        uint64_t code;
        if (!rd_uleb(&p, die_end, &code)) break;
        if (code == 0) {
            if (depth > 0) depth--;
            continue;
        }
        DwAbbrev* ab = abbrev_find(&tab, code);
        if (!ab) { rc = GPA_DWARF_ERR_MALFORMED; break; }

        const char* name = NULL;
        const char* linkage = NULL;
        uintptr_t addr = 0; int have_addr = 0;
        uint64_t type_ref = 0; int have_type = 0;
        int declaration = 0;
        (void)die_off;

        for (size_t i = 0; i < ab->attr_count; i++) {
            DwFormVal v;
            if (!read_form(ab->attrs[i].form, &p, die_end,
                           die_start, (size_t)(die_end - die_start),
                           addr_size, file, &v)) {
                rc = GPA_DWARF_ERR_MALFORMED; goto done;
            }
            switch (ab->attrs[i].name) {
            case DW_AT_name: if (v.has_string) name = v.str; break;
            case DW_AT_linkage_name:
            case DW_AT_MIPS_linkage_name:
                if (v.has_string) linkage = v.str;
                break;
            case DW_AT_location:
                /* Only accept DW_OP_addr <addr> block for globals. */
                if (v.has_block && v.block_len >= 1 + addr_size &&
                    v.block[0] == DW_OP_addr) {
                    if (addr_size == 8) addr = (uintptr_t)rd_u64(v.block + 1);
                    else                addr = (uintptr_t)rd_u32(v.block + 1);
                    have_addr = 1;
                }
                break;
            case DW_AT_type:
                if (v.has_ref) { type_ref = v.ref; have_type = 1; }
                break;
            case DW_AT_declaration:
                if (v.has_flag && v.flag) declaration = 1;
                break;
            default: break;
            }
        }

        if (ab->tag == DW_TAG_variable && have_addr && !declaration) {
            const char* use_name = name ? name : linkage;
            if (use_name) {
                uint64_t sz = 0; uint32_t enc = 0;
                if (have_type) resolve_type(&cu, file, type_ref, &sz, &enc);
                uintptr_t final_addr = addr + load_bias;
                if (!globals_push(out, use_name, final_addr, sz, enc)) {
                    rc = GPA_DWARF_ERR_MALFORMED; goto done;
                }
            }
        }

        if (ab->has_children) depth++;
    }

done:
    abbrev_free(&tab);
    return rc;
}

int gpa_dwarf_parse_module(const char* path,
                           uintptr_t load_bias,
                           GpaDwarfGlobals* out) {
    memset(out, 0, sizeof(*out));
    DwFile f;
    int rc = dwfile_open(&f, path);
    if (rc != GPA_DWARF_OK) { dwfile_close(&f); return rc; }

    const uint8_t* p = f.info.data;
    const uint8_t* end = f.info.data + f.info.size;
    while (p + 11 <= end) {
        uint32_t len = rd_u32(p);
        if (len == 0xffffffff) { rc = GPA_DWARF_UNSUPPORTED_VERSION; break; }
        const uint8_t* cu_end = p + 4 + len;
        if (cu_end > end) { rc = GPA_DWARF_ERR_MALFORMED; break; }
        rc = parse_cu(&f, p, cu_end, load_bias, out);
        if (rc == GPA_DWARF_UNSUPPORTED_VERSION) break;
        if (rc != GPA_DWARF_OK) break;
        p = cu_end;
    }

    dwfile_close(&f);
    if (rc != GPA_DWARF_OK) {
        /* On partial failure, keep whatever globals we already collected —
         * caller decides. But still return the error code. */
    }
    return rc;
}

void gpa_dwarf_globals_free(GpaDwarfGlobals* g) {
    if (!g) return;
    free(g->items);
    free(g->strpool);
    memset(g, 0, sizeof(*g));
}

/* ======================================================================
 * Phase 2: subprogram + local-variable indexing
 * ====================================================================== */

static const char* sub_strpool_dup(GpaDwarfSubprograms* s, const char* src) {
    if (!src) return NULL;
    size_t n = strlen(src);
    if (s->strpool_len + n + 1 > s->strpool_cap) {
        size_t nc = s->strpool_cap ? s->strpool_cap * 2 : 4096;
        while (nc < s->strpool_len + n + 1) nc *= 2;
        char* nb = (char*)realloc(s->strpool, nc);
        if (!nb) return NULL;
        if (nb != s->strpool && s->strpool) {
            ptrdiff_t delta = nb - s->strpool;
            for (size_t i = 0; i < s->count; i++) {
                if (s->items[i].name) s->items[i].name += delta;
                for (size_t j = 0; j < s->items[i].local_count; j++) {
                    if (s->items[i].locals[j].name)
                        s->items[i].locals[j].name += delta;
                }
            }
        }
        s->strpool = nb; s->strpool_cap = nc;
    }
    char* dst = s->strpool + s->strpool_len;
    memcpy(dst, src, n); dst[n] = '\0';
    s->strpool_len += n + 1;
    return dst;
}

static void sub_append_local(GpaDwarfSubprogram* sp, const GpaDwarfLocal* l) {
    if (sp->local_count == sp->local_cap) {
        size_t nc = sp->local_cap ? sp->local_cap * 2 : 8;
        GpaDwarfLocal* nb = (GpaDwarfLocal*)realloc(sp->locals,
                                                    nc * sizeof(GpaDwarfLocal));
        if (!nb) return;
        sp->locals = nb; sp->local_cap = nc;
    }
    sp->locals[sp->local_count++] = *l;
}

/* Walk all DIEs in a CU, tracking nesting; emit subprograms with their
 * formal_parameter + variable children. */
static int parse_cu_subprograms(const DwFile* file,
                                const uint8_t* cu_start, const uint8_t* cu_end,
                                uintptr_t load_bias,
                                GpaDwarfSubprograms* out) {
    if (cu_start + 11 > cu_end) return GPA_DWARF_ERR_MALFORMED;
    uint32_t len = rd_u32(cu_start);
    if (len == 0xffffffff) return GPA_DWARF_ERR_MALFORMED;
    uint16_t version = rd_u16(cu_start + 4);
    if (version == 5) return GPA_DWARF_UNSUPPORTED_VERSION;
    if (version < 2 || version > 4) return GPA_DWARF_UNSUPPORTED_VERSION;
    uint32_t abbrev_off = rd_u32(cu_start + 6);
    uint8_t  addr_size  = cu_start[10];

    const uint8_t* die_start = cu_start + 11;
    const uint8_t* die_end   = cu_start + 4 + len;
    if (die_end > cu_end) die_end = cu_end;

    if (abbrev_off >= file->abbrev.size) return GPA_DWARF_ERR_MALFORMED;
    DwAbbrevTable tab;
    int rc = abbrev_parse(&tab,
                          file->abbrev.data + abbrev_off,
                          file->abbrev.data + file->abbrev.size);
    if (rc != GPA_DWARF_OK) return rc;

    CuView cu = {cu_start, die_start, die_end, &tab, addr_size};

    /* Depth-tracked walk. When we enter a subprogram DIE, remember its
     * depth+1 is where its direct children live; capture variables at
     * that depth only. Nested subprograms (lambdas) become their own
     * subprograms, but we skip their variables from the outer one. */
    const uint8_t* p = die_start;
    int depth = 0;
    int in_sub_depth = -1;    /* depth at which current subprogram's children sit */
    /* Index (not pointer) into out->items to survive realloc. */
    size_t cur_sub_idx = (size_t)-1;

    while (p < die_end) {
        uint64_t code;
        if (!rd_uleb(&p, die_end, &code)) break;
        if (code == 0) {
            if (depth > 0) depth--;
            if (cur_sub_idx != (size_t)-1 && depth < in_sub_depth) {
                cur_sub_idx = (size_t)-1;
                in_sub_depth = -1;
            }
            continue;
        }
        DwAbbrev* ab = abbrev_find(&tab, code);
        if (!ab) { rc = GPA_DWARF_ERR_MALFORMED; break; }

        const char* name = NULL;
        const char* linkage = NULL;
        uintptr_t low_pc = 0; int have_low = 0;
        uint64_t high_pc_raw = 0; int have_high = 0; int high_is_offset = 0;
        const uint8_t* loc_expr = NULL; size_t loc_len = 0;
        uint64_t type_ref = 0; int have_type = 0;
        int declaration = 0;

        for (size_t i = 0; i < ab->attr_count; i++) {
            DwFormVal v;
            if (!read_form(ab->attrs[i].form, &p, die_end,
                           die_start, (size_t)(die_end - die_start),
                           addr_size, file, &v)) {
                rc = GPA_DWARF_ERR_MALFORMED; goto done;
            }
            switch (ab->attrs[i].name) {
            case DW_AT_name: if (v.has_string) name = v.str; break;
            case DW_AT_linkage_name:
            case DW_AT_MIPS_linkage_name:
                if (v.has_string) linkage = v.str;
                break;
            case DW_AT_low_pc:
                if (v.has_addr) { low_pc = (uintptr_t)v.addr; have_low = 1; }
                break;
            case DW_AT_high_pc:
                if (v.has_addr) {
                    high_pc_raw = v.addr; have_high = 1; high_is_offset = 0;
                } else if (v.has_uconst) {
                    /* DWARF 4: high_pc as constant = offset from low_pc. */
                    high_pc_raw = v.uconst; have_high = 1; high_is_offset = 1;
                }
                break;
            case DW_AT_location:
                if (v.has_block) { loc_expr = v.block; loc_len = v.block_len; }
                break;
            case DW_AT_type:
                if (v.has_ref) { type_ref = v.ref; have_type = 1; }
                break;
            case DW_AT_declaration:
                if (v.has_flag && v.flag) declaration = 1;
                break;
            default: break;
            }
        }

        if (ab->tag == DW_TAG_subprogram && have_low && !declaration) {
            /* Append a new subprogram entry. */
            if (out->count == out->cap) {
                size_t nc = out->cap ? out->cap * 2 : 64;
                GpaDwarfSubprogram* nb = (GpaDwarfSubprogram*)realloc(out->items,
                    nc * sizeof(GpaDwarfSubprogram));
                if (!nb) { rc = GPA_DWARF_ERR_MALFORMED; goto done; }
                out->items = nb; out->cap = nc;
            }
            size_t idx = out->count++;
            GpaDwarfSubprogram* sp = &out->items[idx];
            memset(sp, 0, sizeof(*sp));
            const char* use_name = name ? name : linkage;
            sp->name = sub_strpool_dup(out, use_name ? use_name : "");
            sp->low_pc = low_pc + load_bias;
            if (have_high) {
                sp->high_pc = high_is_offset
                    ? sp->low_pc + (uintptr_t)high_pc_raw
                    : (uintptr_t)high_pc_raw + load_bias;
            } else {
                sp->high_pc = sp->low_pc; /* empty range */
            }
            if (ab->has_children) {
                cur_sub_idx = idx;
                in_sub_depth = depth + 1;
            }
        }
        else if ((ab->tag == DW_TAG_variable ||
                  ab->tag == DW_TAG_formal_parameter) &&
                 cur_sub_idx != (size_t)-1 && depth == in_sub_depth &&
                 loc_expr && loc_len > 0) {
            /* A direct child local/parameter of the current subprogram.
             * Resolve its type right now (follow typedef/const chain). */
            uint64_t sz = 0; uint32_t enc = 0;
            if (have_type) resolve_type(&cu, file, type_ref, &sz, &enc);
            const char* use_name = name ? name : linkage;
            if (use_name) {
                /* Dup name first (may realloc strpool + rebase pointers). */
                const char* nm = sub_strpool_dup(out, use_name);
                GpaDwarfLocal l = {
                    .name = nm,
                    .location_expr = loc_expr,
                    .location_len = loc_len,
                    .byte_size = sz,
                    .type_encoding = enc,
                };
                sub_append_local(&out->items[cur_sub_idx], &l);
            }
        }

        if (ab->has_children) depth++;
    }

done:
    abbrev_free(&tab);
    return rc;
}

int gpa_dwarf_parse_subprograms(const char* path,
                                uintptr_t load_bias,
                                GpaDwarfSubprograms* out) {
    memset(out, 0, sizeof(*out));
    DwFile f;
    int rc = dwfile_open(&f, path);
    if (rc != GPA_DWARF_OK) { dwfile_close(&f); return rc; }

    /* Hand ownership of the mmap to `out` so location-expression pointers
     * into it stay valid after we return. */
    out->map = f.map;
    out->map_size = f.map_size;
    out->fd = f.fd;
    /* Detach from `f` so dwfile_close won't unmap/close. */
    f.map = NULL;
    f.fd = -1;

    const uint8_t* p = f.info.data;
    const uint8_t* end = f.info.data + f.info.size;
    while (p + 11 <= end) {
        uint32_t len = rd_u32(p);
        if (len == 0xffffffff) { rc = GPA_DWARF_UNSUPPORTED_VERSION; break; }
        const uint8_t* cu_end = p + 4 + len;
        if (cu_end > end) { rc = GPA_DWARF_ERR_MALFORMED; break; }
        rc = parse_cu_subprograms(&f, p, cu_end, load_bias, out);
        if (rc == GPA_DWARF_UNSUPPORTED_VERSION) break;
        if (rc != GPA_DWARF_OK) break;
        p = cu_end;
    }

    /* We zeroed f.map/f.fd above; dwfile_close is now a no-op for them. */
    dwfile_close(&f);
    return rc;
}

void gpa_dwarf_subprograms_free(GpaDwarfSubprograms* s) {
    if (!s) return;
    for (size_t i = 0; i < s->count; i++) free(s->items[i].locals);
    free(s->items);
    free(s->strpool);
    if (s->map) munmap(s->map, s->map_size);
    if (s->fd >= 0) close(s->fd);
    memset(s, 0, sizeof(*s));
    s->fd = -1;
}
