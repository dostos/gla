#ifndef GPA_SHADOW_STATE_H
#define GPA_SHADOW_STATE_H

#include <stddef.h>
#include <stdint.h>
#include <stdbool.h>

#define GPA_MAX_TEXTURE_UNITS 32
#define GPA_MAX_UNIFORMS 256
#define GPA_MAX_VERTEX_ATTRIBS 16
#define GPA_MAX_TEXTURES 4096
#define GPA_MAX_DEBUG_GROUP_DEPTH 32
#define GPA_MAX_DEBUG_GROUP_NAME 128
#define GPA_MAX_CLEARS_PER_FRAME 16
#define GPA_MAX_FBOS 64

typedef struct {
    char name[GPA_MAX_DEBUG_GROUP_NAME];
    uint32_t id;
} GpaDebugGroupEntry;

typedef struct {
    uint32_t mask;             /* GL_COLOR_BUFFER_BIT | GL_DEPTH_BUFFER_BIT | GL_STENCIL_BUFFER_BIT */
    uint32_t draw_call_before; /* how many draw calls happened before this clear */
} GpaClearRecord;

/* GL enum constants (no GL headers needed) */
#define GL_TEXTURE0             0x84C0
#define GL_TEXTURE_2D           0x0DE1
#define GL_DEPTH_TEST           0x0B71
#define GL_BLEND                0x0BE2
#define GL_CULL_FACE            0x0B44
#define GL_SCISSOR_TEST         0x0C11
#define GL_LESS                 0x0201
#define GL_LEQUAL               0x0203
#define GL_BACK                 0x0405
#define GL_CCW                  0x0901
#define GL_ARRAY_BUFFER         0x8892
#define GL_ELEMENT_ARRAY_BUFFER 0x8893
#define GL_FRAMEBUFFER          0x8D40
#define GL_FLOAT                0x1406
#define GL_FLOAT_VEC3           0x8B51
#define GL_FLOAT_VEC4           0x8B52
#define GL_FLOAT_MAT3           0x8B5B
#define GL_FLOAT_MAT4           0x8B5C
#define GL_INT                  0x1404
#define GL_COLOR_ATTACHMENT0    0x8CE0
#define GL_DEPTH_ATTACHMENT     0x8D00

/* Uniform value (up to mat4 = 16 floats = 64 bytes) */
typedef struct {
    uint32_t location;
    uint32_t type;       /* GL type enum */
    uint8_t  data[64];   /* raw value bytes */
    uint32_t data_size;  /* actual size used */
    char     name[64];   /* uniform name (if known) */
    bool     active;
} GpaShadowUniform;

/* Per-texture dimension/format info, populated by glTexImage2D intercept */
typedef struct {
    uint32_t width;
    uint32_t height;
    uint32_t internal_format;
} GpaTextureInfo;

/* Per-FBO attachment tracking */
#define GPA_MAX_COLOR_ATTACHMENTS 8
typedef struct {
    uint32_t fbo_id;
    /* Texture IDs for GL_COLOR_ATTACHMENT0..7. Slot 0 mirrors
     * color_attachment_tex below for backward compat.  A value of 0 in slot i
     * means "no texture attached at COLOR_ATTACHMENT<i>". */
    uint32_t color_attachments[GPA_MAX_COLOR_ATTACHMENTS];
    uint32_t color_attachment_tex;   /* texture ID attached as COLOR_ATTACHMENT0 (== color_attachments[0]) */
    uint32_t depth_attachment_tex;   /* texture ID attached as DEPTH_ATTACHMENT */
} GpaFboInfo;

typedef struct {
    /* Texture bindings */
    uint32_t active_texture_unit;                       /* 0-based index */
    uint32_t bound_textures_2d[GPA_MAX_TEXTURE_UNITS];

    /* Per-texture metadata (indexed by texture name/id) */
    GpaTextureInfo texture_info[GPA_MAX_TEXTURES];

    /* Shader program */
    uint32_t        current_program;
    GpaShadowUniform uniforms[GPA_MAX_UNIFORMS];
    uint32_t        uniform_count;

    /* Pipeline state */
    int32_t  viewport[4];           /* x, y, w, h */
    int32_t  scissor[4];            /* x, y, w, h */
    bool     depth_test_enabled;
    bool     depth_write_enabled;
    uint32_t depth_func;            /* GL_LESS, GL_LEQUAL, etc. */
    bool     blend_enabled;
    uint32_t blend_src;
    uint32_t blend_dst;
    bool     cull_enabled;
    uint32_t cull_mode;             /* GL_BACK, GL_FRONT */
    uint32_t front_face;            /* GL_CCW, GL_CW */
    bool     scissor_test_enabled;

    /* Buffer bindings */
    uint32_t bound_vao;
    uint32_t bound_vbo;             /* GL_ARRAY_BUFFER */
    uint32_t bound_ebo;             /* GL_ELEMENT_ARRAY_BUFFER */
    uint32_t bound_fbo;             /* GL_FRAMEBUFFER */

    /* FBO attachment tracking */
    GpaFboInfo fbo_info[GPA_MAX_FBOS];
    uint32_t fbo_count;

    /* Frame tracking */
    uint64_t frame_number;
    uint32_t draw_call_count;       /* resets each frame */

    /* Per-frame clear records */
    GpaClearRecord clear_records[GPA_MAX_CLEARS_PER_FRAME];
    uint32_t clear_count;           /* resets each frame */

    /* Debug group stack (GL_KHR_debug) */
    GpaDebugGroupEntry debug_group_stack[GPA_MAX_DEBUG_GROUP_DEPTH];
    uint32_t debug_group_depth;
} GpaShadowState;

/* Initialize to GL defaults */
void gpa_shadow_init(GpaShadowState *state);

/* Texture */
void gpa_shadow_active_texture(GpaShadowState *state, uint32_t texture_unit); /* GL_TEXTURE0+n */
void gpa_shadow_bind_texture_2d(GpaShadowState *state, uint32_t texture_id);
void gpa_shadow_tex_image_2d(GpaShadowState *state, uint32_t texture_id,
                             uint32_t width, uint32_t height, uint32_t internal_format);
const GpaTextureInfo* gpa_shadow_get_texture_info(const GpaShadowState *state, uint32_t texture_id);

/* Shader */
void gpa_shadow_use_program(GpaShadowState *state, uint32_t program_id);

/* Uniforms */
void gpa_shadow_set_uniform_1f(GpaShadowState *state, int32_t location, float v);
void gpa_shadow_set_uniform_3f(GpaShadowState *state, int32_t location, float x, float y, float z);
void gpa_shadow_set_uniform_4f(GpaShadowState *state, int32_t location, float x, float y, float z, float w);
void gpa_shadow_set_uniform_1i(GpaShadowState *state, int32_t location, int32_t v);
void gpa_shadow_set_uniform_mat4(GpaShadowState *state, int32_t location, const float *data);
void gpa_shadow_set_uniform_mat3(GpaShadowState *state, int32_t location, const float *data);

/* Pipeline state */
void gpa_shadow_enable(GpaShadowState *state, uint32_t cap);
void gpa_shadow_disable(GpaShadowState *state, uint32_t cap);
void gpa_shadow_depth_func(GpaShadowState *state, uint32_t func);
void gpa_shadow_depth_mask(GpaShadowState *state, bool flag);
void gpa_shadow_blend_func(GpaShadowState *state, uint32_t src, uint32_t dst);
void gpa_shadow_cull_face(GpaShadowState *state, uint32_t mode);
void gpa_shadow_front_face(GpaShadowState *state, uint32_t mode);
void gpa_shadow_viewport(GpaShadowState *state, int32_t x, int32_t y, int32_t w, int32_t h);
void gpa_shadow_scissor(GpaShadowState *state, int32_t x, int32_t y, int32_t w, int32_t h);

/* Buffer bindings */
void gpa_shadow_bind_vao(GpaShadowState *state, uint32_t vao);
void gpa_shadow_bind_buffer(GpaShadowState *state, uint32_t target, uint32_t buffer);
void gpa_shadow_bind_framebuffer(GpaShadowState *state, uint32_t target, uint32_t fbo);

/* FBO attachment tracking */
void gpa_shadow_framebuffer_texture_2d(GpaShadowState *state, uint32_t target,
                                        uint32_t attachment, uint32_t texture);
const GpaFboInfo* gpa_shadow_get_fbo_info(const GpaShadowState *state, uint32_t fbo_id);

/* Draw call tracking */
void gpa_shadow_record_draw(GpaShadowState *state);

/* Clear tracking */
void gpa_shadow_record_clear(GpaShadowState *state, uint32_t mask);

/* Frame boundary */
void gpa_shadow_new_frame(GpaShadowState *state);

/* Debug groups (GL_KHR_debug) */
void gpa_shadow_push_debug_group(GpaShadowState *state, uint32_t id, const char *name);
void gpa_shadow_pop_debug_group(GpaShadowState *state);
int  gpa_shadow_get_debug_group_path(const GpaShadowState *state, char *buf, size_t buf_size);

#endif /* GPA_SHADOW_STATE_H */
