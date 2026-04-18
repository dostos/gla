#include "frame_capture.h"
#include "ipc_client.h"
#include "gl_wrappers.h"
#include "shadow_state.h"

#include <stdint.h>
#include <stddef.h>
#include <string.h>
#include <sys/types.h>
#include <unistd.h>

/* Declared in gl_shim.c — lazy IPC init on first swap */
void gla_ensure_ipc(void);

/* GL constants not pulled from GL headers */
#define GL_RGBA            0x1908
#define GL_UNSIGNED_BYTE   0x1401
/* GL_FLOAT 0x1406 already defined in shadow_state.h */
#define GL_DEPTH_COMPONENT 0x1902
#define GL_VIEWPORT        0x0BA2

/* Globals defined in gl_shim.c */
extern GlaShadowState   gla_shadow;
extern GlaRealGlFuncs   gla_real_gl;

/* -------------------------------------------------------------------------
 * Per-frame draw call recording buffer
 * -------------------------------------------------------------------------
 * We keep a fixed-size ring of snapshots.  The ceiling of 1024 draw calls
 * per frame is generous for the M1/M2 MVP; the serialisation path silently
 * stops recording once the cap is hit.
 * ---------------------------------------------------------------------- */

#define GLA_MAX_DRAW_CALLS_PER_FRAME 1024

/* Snapshot of a single draw call taken at the moment the draw is issued. */
typedef struct {
    uint32_t id;
    uint32_t primitive_type;
    uint32_t vertex_count;
    uint32_t index_count;
    uint32_t instance_count;
    uint32_t shader_program_id;

    /* Pipeline state */
    int32_t  viewport[4];
    int32_t  scissor[4];
    uint8_t  scissor_enabled;
    uint8_t  depth_test;
    uint8_t  depth_write;
    uint32_t depth_func;
    uint8_t  blend_enabled;
    uint32_t blend_src;
    uint32_t blend_dst;
    uint8_t  cull_enabled;
    uint32_t cull_mode;
    uint32_t front_face;

    /* Texture bindings: non-zero slots only */
    uint32_t texture_count;
    struct { uint32_t slot; uint32_t texture_id;
             uint32_t width; uint32_t height; uint32_t format; }
        textures[GLA_MAX_TEXTURE_UNITS];

    /* Uniform / shader params */
    uint32_t param_count;
    GlaShadowUniform params[GLA_MAX_UNIFORMS];

    /* Debug group path (GL_KHR_debug push/pop group stack) */
    char debug_group_path[512];
} GlaDrawCallSnapshot;

static GlaDrawCallSnapshot gla_draw_call_buf[GLA_MAX_DRAW_CALLS_PER_FRAME];
static uint32_t            gla_draw_call_count = 0;

/* -------------------------------------------------------------------------
 * Public: reset draw call buffer at frame start
 * ---------------------------------------------------------------------- */

void gla_frame_reset_draw_calls(void) {
    gla_draw_call_count = 0;
}

/* -------------------------------------------------------------------------
 * Public: snapshot draw call state
 * ---------------------------------------------------------------------- */

void gla_frame_record_draw_call(const GlaShadowState* shadow,
                                 uint32_t primitive,
                                 uint32_t vertex_count,
                                 uint32_t index_count,
                                 uint32_t instance_count) {
    if (gla_draw_call_count >= GLA_MAX_DRAW_CALLS_PER_FRAME) return;

    GlaDrawCallSnapshot* s = &gla_draw_call_buf[gla_draw_call_count];
    memset(s, 0, sizeof(*s));

    s->id               = gla_draw_call_count;
    s->primitive_type   = primitive;
    s->vertex_count     = vertex_count;
    s->index_count      = index_count;
    s->instance_count   = instance_count;
    s->shader_program_id = shadow->current_program;

    /* Pipeline state */
    memcpy(s->viewport, shadow->viewport, sizeof(s->viewport));
    memcpy(s->scissor,  shadow->scissor,  sizeof(s->scissor));
    s->scissor_enabled = shadow->scissor_test_enabled ? 1 : 0;
    s->depth_test      = shadow->depth_test_enabled   ? 1 : 0;
    s->depth_write     = shadow->depth_write_enabled  ? 1 : 0;
    s->depth_func      = shadow->depth_func;
    s->blend_enabled   = shadow->blend_enabled        ? 1 : 0;
    s->blend_src       = shadow->blend_src;
    s->blend_dst       = shadow->blend_dst;
    s->cull_enabled    = shadow->cull_enabled          ? 1 : 0;
    s->cull_mode       = shadow->cull_mode;
    s->front_face      = shadow->front_face;

    /* Texture bindings — collect non-zero slots, with dimensions */
    s->texture_count = 0;
    for (uint32_t i = 0; i < GLA_MAX_TEXTURE_UNITS; i++) {
        uint32_t tid = shadow->bound_textures_2d[i];
        if (tid != 0) {
            s->textures[s->texture_count].slot       = i;
            s->textures[s->texture_count].texture_id = tid;
            const GlaTextureInfo* info = gla_shadow_get_texture_info(shadow, tid);
            if (info) {
                s->textures[s->texture_count].width  = info->width;
                s->textures[s->texture_count].height = info->height;
                s->textures[s->texture_count].format = info->internal_format;
            } else {
                s->textures[s->texture_count].width  = 0;
                s->textures[s->texture_count].height = 0;
                s->textures[s->texture_count].format = 0;
            }
            s->texture_count++;
        }
    }

    /* Uniform params */
    s->param_count = shadow->uniform_count < GLA_MAX_UNIFORMS
                   ? shadow->uniform_count
                   : GLA_MAX_UNIFORMS;
    memcpy(s->params, shadow->uniforms,
           s->param_count * sizeof(GlaShadowUniform));

    gla_shadow_get_debug_group_path(shadow, s->debug_group_path, sizeof(s->debug_group_path));

    gla_draw_call_count++;
}

/* -------------------------------------------------------------------------
 * Serialise draw call records into a byte buffer.
 *
 * Wire format per draw call:
 *   uint32  id
 *   uint32  primitive_type
 *   uint32  vertex_count
 *   uint32  index_count
 *   uint32  instance_count
 *   uint32  shader_program_id
 *   int32[4] viewport
 *   int32[4] scissor
 *   uint8   scissor_enabled
 *   uint8   depth_test
 *   uint8   depth_write
 *   uint8   _pad
 *   uint32  depth_func
 *   uint8   blend_enabled
 *   uint8   _pad[3]
 *   uint32  blend_src
 *   uint32  blend_dst
 *   uint8   cull_enabled
 *   uint8   _pad[3]
 *   uint32  cull_mode
 *   uint32  front_face
 *   uint32  texture_count
 *   texture_count * { uint32 slot, uint32 texture_id, uint32 width,
 *                     uint32 height, uint32 format }
 *   uint32  param_count
 *   param_count * { uint32 location, uint32 type, uint32 data_size,
 *                   data_size bytes of data }
 *
 * Returns the number of bytes written.  The caller must ensure `buf` has
 * enough room; `buf_max` is the hard ceiling.
 * ---------------------------------------------------------------------- */

static size_t serialise_draw_calls(uint8_t* buf, size_t buf_max) {
    uint8_t* p   = buf;
    uint8_t* end = buf + buf_max;

    /* draw_call_count field */
    if (p + 4 > end) return 0;
    uint32_t n = gla_draw_call_count;
    memcpy(p, &n, 4); p += 4;

    for (uint32_t i = 0; i < n; i++) {
        const GlaDrawCallSnapshot* s = &gla_draw_call_buf[i];

        /* Fixed-size header: 6*uint32 + 4*int32 + 4*int32 + 4 bytes + 1*uint32
         *                   + 4 bytes + 2*uint32 + 4 bytes + 2*uint32
         *                   = 24 + 16 + 16 + 4 + 4 + 4 + 8 + 4 + 8 = 88 bytes
         * Plus texture_count field, then variable textures.
         * Plus param_count field, then variable params.
         * Conservative: require at least 128 bytes available before proceeding.
         */
        if (p + 128 > end) break;

        /* ids + counts */
        memcpy(p, &s->id,               4); p += 4;
        memcpy(p, &s->primitive_type,   4); p += 4;
        memcpy(p, &s->vertex_count,     4); p += 4;
        memcpy(p, &s->index_count,      4); p += 4;
        memcpy(p, &s->instance_count,   4); p += 4;
        memcpy(p, &s->shader_program_id,4); p += 4;

        /* viewport, scissor */
        memcpy(p, s->viewport, 16); p += 16;
        memcpy(p, s->scissor,  16); p += 16;

        /* booleans padded to 4-byte boundary */
        *p++ = s->scissor_enabled;
        *p++ = s->depth_test;
        *p++ = s->depth_write;
        *p++ = 0; /* pad */

        memcpy(p, &s->depth_func,   4); p += 4;

        *p++ = s->blend_enabled;
        *p++ = 0; *p++ = 0; *p++ = 0; /* pad */
        memcpy(p, &s->blend_src, 4); p += 4;
        memcpy(p, &s->blend_dst, 4); p += 4;

        *p++ = s->cull_enabled;
        *p++ = 0; *p++ = 0; *p++ = 0; /* pad */
        memcpy(p, &s->cull_mode,  4); p += 4;
        memcpy(p, &s->front_face, 4); p += 4;

        /* textures: slot(4) + texture_id(4) + width(4) + height(4) + format(4) = 20 bytes each */
        if (p + 4 + s->texture_count * 20 > end) break;
        memcpy(p, &s->texture_count, 4); p += 4;
        for (uint32_t t = 0; t < s->texture_count; t++) {
            memcpy(p, &s->textures[t].slot,       4); p += 4;
            memcpy(p, &s->textures[t].texture_id, 4); p += 4;
            memcpy(p, &s->textures[t].width,      4); p += 4;
            memcpy(p, &s->textures[t].height,     4); p += 4;
            memcpy(p, &s->textures[t].format,     4); p += 4;
        }

        /* shader params */
        uint32_t pc = s->param_count;
        /* each param: location(4) + type(4) + data_size(4) + data(up to 64) = up to 76 bytes */
        if (p + 4 + (uint64_t)pc * 76 > end) break;
        memcpy(p, &pc, 4); p += 4;
        for (uint32_t j = 0; j < pc; j++) {
            const GlaShadowUniform* u = &s->params[j];
            memcpy(p, &u->location,  4); p += 4;
            memcpy(p, &u->type,      4); p += 4;
            memcpy(p, &u->data_size, 4); p += 4;
            if (u->data_size > 0 && u->data_size <= 64) {
                memcpy(p, u->data, u->data_size);
                p += u->data_size;
            }
        }

        /* Wire format: uint16 path_len, then path_len chars (no null terminator) */
        uint16_t path_len = (uint16_t)strlen(s->debug_group_path);
        if (p + 2 + path_len > end) break;
        memcpy(p, &path_len, 2); p += 2;
        if (path_len > 0) { memcpy(p, s->debug_group_path, path_len); p += path_len; }
    }

    return (size_t)(p - buf);
}

/* -------------------------------------------------------------------------
 * Public: on swap — capture framebuffer + draw calls into SHM slot
 * ---------------------------------------------------------------------- */

void gla_frame_on_swap(void) {
    /* Lazy IPC init — only the process that actually renders will connect */
    gla_ensure_ipc();
    if (!gla_ipc_is_connected()) return;

    uint32_t slot_index;
    void* slot = gla_ipc_claim_slot(&slot_index);
    if (!slot) return;   /* ring buffer full — skip this frame */

    /* Query current viewport dimensions */
    GLint viewport[4];
    gla_real_gl.glGetIntegerv(GL_VIEWPORT, viewport);
    int width  = (int)viewport[2];
    int height = (int)viewport[3];

    /* Guard against degenerate viewports */
    if (width <= 0 || height <= 0) {
        gla_ipc_commit_slot(slot_index, 0);
        gla_ipc_send_frame_ready(gla_shadow.frame_number, slot_index);
        return;
    }

    /* Write frame data into the shm slot.
     * Layout:
     *   [0..3]      width  (uint32_t)
     *   [4..7]      height (uint32_t)
     *   [8 ..]      color data (width * height * 4 bytes, GL_RGBA / GL_UNSIGNED_BYTE)
     *   [8+w*h*4..] depth data (width * height * 4 bytes, GL_DEPTH_COMPONENT / GL_FLOAT)
     *   [8+2*w*h*4..] draw call data: uint32 draw_call_count, then serialised records
     */
    uint8_t*  ptr    = (uint8_t*)slot;
    uint32_t* header = (uint32_t*)ptr;
    header[0] = (uint32_t)width;
    header[1] = (uint32_t)height;
    ptr += 8;

    /* Color buffer */
    gla_real_gl.glReadPixels(0, 0, width, height, GL_RGBA, GL_UNSIGNED_BYTE, ptr);
    ptr += (size_t)width * (size_t)height * 4u;

    /* Depth buffer */
    gla_real_gl.glReadPixels(0, 0, width, height, GL_DEPTH_COMPONENT, GL_FLOAT, ptr);
    ptr += (size_t)width * (size_t)height * 4u;

    /* Draw call metadata — serialise into remaining slot space */
    {
        /* Compute how much of the slot we have used and what remains */
        uint8_t* slot_start = (uint8_t*)slot;

        /* The engine was created with slot_size = 64 MiB (engine.cpp default).
         * Rather than hard-coding that, we use a conservative upper bound of
         * 8 MiB for draw call data which is more than enough for any realistic
         * frame at this milestone. */
        const size_t kDrawCallBudget = 8u * 1024u * 1024u;
        size_t used_so_far = (size_t)(ptr - slot_start);
        (void)used_so_far; /* silence unused-var warning if asserts disabled */

        size_t written = serialise_draw_calls(ptr, kDrawCallBudget);
        ptr += written;
    }

    uint64_t total_size = (uint64_t)((uintptr_t)ptr - (uintptr_t)slot);

    gla_ipc_commit_slot(slot_index, total_size);
    gla_ipc_send_frame_ready(gla_shadow.frame_number, slot_index);

    /* Check for pause request from engine (non-blocking) */
    if (gla_ipc_should_pause()) {
        gla_ipc_wait_resume();
    }
}
