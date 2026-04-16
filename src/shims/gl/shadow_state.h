#ifndef GLA_SHADOW_STATE_H
#define GLA_SHADOW_STATE_H

#include <stdint.h>
#include <stdbool.h>

#define GLA_MAX_TEXTURE_UNITS 32
#define GLA_MAX_UNIFORMS 256
#define GLA_MAX_VERTEX_ATTRIBS 16

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

/* Uniform value (up to mat4 = 16 floats = 64 bytes) */
typedef struct {
    uint32_t location;
    uint32_t type;       /* GL type enum */
    uint8_t  data[64];   /* raw value bytes */
    uint32_t data_size;  /* actual size used */
    char     name[64];   /* uniform name (if known) */
    bool     active;
} GlaShadowUniform;

typedef struct {
    /* Texture bindings */
    uint32_t active_texture_unit;                       /* 0-based index */
    uint32_t bound_textures_2d[GLA_MAX_TEXTURE_UNITS];

    /* Shader program */
    uint32_t        current_program;
    GlaShadowUniform uniforms[GLA_MAX_UNIFORMS];
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

    /* Frame tracking */
    uint64_t frame_number;
    uint32_t draw_call_count;       /* resets each frame */
} GlaShadowState;

/* Initialize to GL defaults */
void gla_shadow_init(GlaShadowState *state);

/* Texture */
void gla_shadow_active_texture(GlaShadowState *state, uint32_t texture_unit); /* GL_TEXTURE0+n */
void gla_shadow_bind_texture_2d(GlaShadowState *state, uint32_t texture_id);

/* Shader */
void gla_shadow_use_program(GlaShadowState *state, uint32_t program_id);

/* Uniforms */
void gla_shadow_set_uniform_1f(GlaShadowState *state, int32_t location, float v);
void gla_shadow_set_uniform_3f(GlaShadowState *state, int32_t location, float x, float y, float z);
void gla_shadow_set_uniform_4f(GlaShadowState *state, int32_t location, float x, float y, float z, float w);
void gla_shadow_set_uniform_1i(GlaShadowState *state, int32_t location, int32_t v);
void gla_shadow_set_uniform_mat4(GlaShadowState *state, int32_t location, const float *data);
void gla_shadow_set_uniform_mat3(GlaShadowState *state, int32_t location, const float *data);

/* Pipeline state */
void gla_shadow_enable(GlaShadowState *state, uint32_t cap);
void gla_shadow_disable(GlaShadowState *state, uint32_t cap);
void gla_shadow_depth_func(GlaShadowState *state, uint32_t func);
void gla_shadow_depth_mask(GlaShadowState *state, bool flag);
void gla_shadow_blend_func(GlaShadowState *state, uint32_t src, uint32_t dst);
void gla_shadow_cull_face(GlaShadowState *state, uint32_t mode);
void gla_shadow_front_face(GlaShadowState *state, uint32_t mode);
void gla_shadow_viewport(GlaShadowState *state, int32_t x, int32_t y, int32_t w, int32_t h);
void gla_shadow_scissor(GlaShadowState *state, int32_t x, int32_t y, int32_t w, int32_t h);

/* Buffer bindings */
void gla_shadow_bind_vao(GlaShadowState *state, uint32_t vao);
void gla_shadow_bind_buffer(GlaShadowState *state, uint32_t target, uint32_t buffer);
void gla_shadow_bind_framebuffer(GlaShadowState *state, uint32_t target, uint32_t fbo);

/* Draw call tracking */
void gla_shadow_record_draw(GlaShadowState *state);

/* Frame boundary */
void gla_shadow_new_frame(GlaShadowState *state);

#endif /* GLA_SHADOW_STATE_H */
