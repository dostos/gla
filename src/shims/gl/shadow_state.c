/* GL shadow state tracker
 * Mirrors the OpenGL state machine to avoid expensive glGet* calls at capture
 * time. Every intercepted state-setting call updates this shadow; serialization
 * reads from here instead of querying the driver.
 */

#include "src/shims/gl/shadow_state.h"

#include <stddef.h>
#include <string.h>

/* -------------------------------------------------------------------------
 * Internal helpers
 * ---------------------------------------------------------------------- */

/* Find or allocate a uniform slot for the given location.
 * Returns NULL if the table is full. */
static GlaShadowUniform *find_or_alloc_uniform(GlaShadowState *state,
                                                int32_t location) {
    /* Search existing slots first */
    for (uint32_t i = 0; i < state->uniform_count; i++) {
        if (state->uniforms[i].active &&
            (int32_t)state->uniforms[i].location == location) {
            return &state->uniforms[i];
        }
    }
    /* Allocate a new slot */
    if (state->uniform_count >= GLA_MAX_UNIFORMS) {
        return NULL;
    }
    GlaShadowUniform *u = &state->uniforms[state->uniform_count++];
    memset(u, 0, sizeof(*u));
    u->location = (uint32_t)location;
    u->active   = true;
    return u;
}

/* -------------------------------------------------------------------------
 * Initialization
 * ---------------------------------------------------------------------- */

void gla_shadow_init(GlaShadowState *state) {
    memset(state, 0, sizeof(*state));

    /* GL spec defaults */
    state->depth_func        = GL_LESS;
    state->depth_write_enabled = true;   /* glDepthMask defaults to GL_TRUE */
    state->front_face        = GL_CCW;
    state->cull_mode         = GL_BACK;

    /* blend_src/blend_dst default: GL_ONE / GL_ZERO — but we zero-init so
     * leave as 0; callers that care about the initial blend equation should
     * call gla_shadow_blend_func themselves after init. */
}

/* -------------------------------------------------------------------------
 * Texture
 * ---------------------------------------------------------------------- */

void gla_shadow_active_texture(GlaShadowState *state, uint32_t texture_unit) {
    /* texture_unit is the raw GL enum, e.g. GL_TEXTURE0 + n */
    uint32_t idx = texture_unit - GL_TEXTURE0;
    if (idx < GLA_MAX_TEXTURE_UNITS) {
        state->active_texture_unit = idx;
    }
}

void gla_shadow_bind_texture_2d(GlaShadowState *state, uint32_t texture_id) {
    if (state->active_texture_unit < GLA_MAX_TEXTURE_UNITS) {
        state->bound_textures_2d[state->active_texture_unit] = texture_id;
    }
}

/* -------------------------------------------------------------------------
 * Shader program
 * ---------------------------------------------------------------------- */

void gla_shadow_use_program(GlaShadowState *state, uint32_t program_id) {
    state->current_program = program_id;
}

/* -------------------------------------------------------------------------
 * Uniforms
 * ---------------------------------------------------------------------- */

void gla_shadow_set_uniform_1f(GlaShadowState *state, int32_t location,
                                float v) {
    GlaShadowUniform *u = find_or_alloc_uniform(state, location);
    if (!u) return;
    u->type      = GL_FLOAT;
    u->data_size = sizeof(float);
    memcpy(u->data, &v, sizeof(float));
}

void gla_shadow_set_uniform_3f(GlaShadowState *state, int32_t location,
                                float x, float y, float z) {
    GlaShadowUniform *u = find_or_alloc_uniform(state, location);
    if (!u) return;
    float tmp[3] = {x, y, z};
    u->type      = GL_FLOAT_VEC3;
    u->data_size = 3 * sizeof(float);
    memcpy(u->data, tmp, u->data_size);
}

void gla_shadow_set_uniform_4f(GlaShadowState *state, int32_t location,
                                float x, float y, float z, float w) {
    GlaShadowUniform *u = find_or_alloc_uniform(state, location);
    if (!u) return;
    float tmp[4] = {x, y, z, w};
    u->type      = GL_FLOAT_VEC4;
    u->data_size = 4 * sizeof(float);
    memcpy(u->data, tmp, u->data_size);
}

void gla_shadow_set_uniform_1i(GlaShadowState *state, int32_t location,
                                int32_t v) {
    GlaShadowUniform *u = find_or_alloc_uniform(state, location);
    if (!u) return;
    u->type      = GL_INT;
    u->data_size = sizeof(int32_t);
    memcpy(u->data, &v, sizeof(int32_t));
}

void gla_shadow_set_uniform_mat4(GlaShadowState *state, int32_t location,
                                  const float *data) {
    GlaShadowUniform *u = find_or_alloc_uniform(state, location);
    if (!u) return;
    u->type      = GL_FLOAT_MAT4;
    u->data_size = 16 * sizeof(float);
    memcpy(u->data, data, u->data_size);
}

void gla_shadow_set_uniform_mat3(GlaShadowState *state, int32_t location,
                                  const float *data) {
    GlaShadowUniform *u = find_or_alloc_uniform(state, location);
    if (!u) return;
    u->type      = GL_FLOAT_MAT3;
    u->data_size = 9 * sizeof(float);
    memcpy(u->data, data, u->data_size);
}

/* -------------------------------------------------------------------------
 * Pipeline state — enable / disable
 * ---------------------------------------------------------------------- */

void gla_shadow_enable(GlaShadowState *state, uint32_t cap) {
    switch (cap) {
        case GL_DEPTH_TEST:   state->depth_test_enabled  = true; break;
        case GL_BLEND:        state->blend_enabled        = true; break;
        case GL_CULL_FACE:    state->cull_enabled         = true; break;
        case GL_SCISSOR_TEST: state->scissor_test_enabled = true; break;
        default: break;
    }
}

void gla_shadow_disable(GlaShadowState *state, uint32_t cap) {
    switch (cap) {
        case GL_DEPTH_TEST:   state->depth_test_enabled  = false; break;
        case GL_BLEND:        state->blend_enabled        = false; break;
        case GL_CULL_FACE:    state->cull_enabled         = false; break;
        case GL_SCISSOR_TEST: state->scissor_test_enabled = false; break;
        default: break;
    }
}

void gla_shadow_depth_func(GlaShadowState *state, uint32_t func) {
    state->depth_func = func;
}

void gla_shadow_depth_mask(GlaShadowState *state, bool flag) {
    state->depth_write_enabled = flag;
}

void gla_shadow_blend_func(GlaShadowState *state, uint32_t src,
                            uint32_t dst) {
    state->blend_src = src;
    state->blend_dst = dst;
}

void gla_shadow_cull_face(GlaShadowState *state, uint32_t mode) {
    state->cull_mode = mode;
}

void gla_shadow_front_face(GlaShadowState *state, uint32_t mode) {
    state->front_face = mode;
}

void gla_shadow_viewport(GlaShadowState *state, int32_t x, int32_t y,
                          int32_t w, int32_t h) {
    state->viewport[0] = x;
    state->viewport[1] = y;
    state->viewport[2] = w;
    state->viewport[3] = h;
}

void gla_shadow_scissor(GlaShadowState *state, int32_t x, int32_t y,
                         int32_t w, int32_t h) {
    state->scissor[0] = x;
    state->scissor[1] = y;
    state->scissor[2] = w;
    state->scissor[3] = h;
}

/* -------------------------------------------------------------------------
 * Buffer bindings
 * ---------------------------------------------------------------------- */

void gla_shadow_bind_vao(GlaShadowState *state, uint32_t vao) {
    state->bound_vao = vao;
}

void gla_shadow_bind_buffer(GlaShadowState *state, uint32_t target,
                             uint32_t buffer) {
    switch (target) {
        case GL_ARRAY_BUFFER:         state->bound_vbo = buffer; break;
        case GL_ELEMENT_ARRAY_BUFFER: state->bound_ebo = buffer; break;
        default: break;
    }
}

void gla_shadow_bind_framebuffer(GlaShadowState *state, uint32_t target,
                                  uint32_t fbo) {
    (void)target; /* GL_FRAMEBUFFER, GL_READ_FRAMEBUFFER, etc. */
    state->bound_fbo = fbo;
}

/* -------------------------------------------------------------------------
 * Draw call tracking
 * ---------------------------------------------------------------------- */

void gla_shadow_record_draw(GlaShadowState *state) {
    state->draw_call_count++;
}

/* -------------------------------------------------------------------------
 * Frame boundary
 * ---------------------------------------------------------------------- */

void gla_shadow_new_frame(GlaShadowState *state) {
    state->frame_number++;
    state->draw_call_count = 0;
}
