/* Tests for the GL shadow state tracker.
 * Uses plain assert() — no external test framework required.
 */

#include "src/shims/gl/shadow_state.h"

#include <assert.h>
#include <string.h>
#include <stdio.h>

/* -------------------------------------------------------------------------
 * 1. InitDefaults
 * ---------------------------------------------------------------------- */
static void test_init_defaults(void) {
    GlaShadowState s;
    gla_shadow_init(&s);

    assert(s.depth_test_enabled  == false);
    assert(s.blend_enabled        == false);
    assert(s.cull_enabled         == false);
    assert(s.scissor_test_enabled == false);
    assert(s.depth_func           == GL_LESS);
    assert(s.front_face           == GL_CCW);
    assert(s.depth_write_enabled  == true);

    /* viewport defaults to (0,0,0,0) */
    assert(s.viewport[0] == 0 && s.viewport[1] == 0);
    assert(s.viewport[2] == 0 && s.viewport[3] == 0);

    assert(s.frame_number    == 0);
    assert(s.draw_call_count == 0);
    assert(s.current_program == 0);
    assert(s.active_texture_unit == 0);

    printf("PASS test_init_defaults\n");
}

/* -------------------------------------------------------------------------
 * 2. TextureBindings
 * ---------------------------------------------------------------------- */
static void test_texture_bindings(void) {
    GlaShadowState s;
    gla_shadow_init(&s);

    gla_shadow_active_texture(&s, GL_TEXTURE0 + 1);
    assert(s.active_texture_unit == 1);

    gla_shadow_bind_texture_2d(&s, 5);
    assert(s.bound_textures_2d[1] == 5);

    /* unit 0 should be untouched */
    assert(s.bound_textures_2d[0] == 0);

    printf("PASS test_texture_bindings\n");
}

/* -------------------------------------------------------------------------
 * 3. ProgramBinding
 * ---------------------------------------------------------------------- */
static void test_program_binding(void) {
    GlaShadowState s;
    gla_shadow_init(&s);

    gla_shadow_use_program(&s, 3);
    assert(s.current_program == 3);

    gla_shadow_use_program(&s, 0);
    assert(s.current_program == 0);

    printf("PASS test_program_binding\n");
}

/* -------------------------------------------------------------------------
 * 4. UniformMat4
 * ---------------------------------------------------------------------- */
static void test_uniform_mat4(void) {
    GlaShadowState s;
    gla_shadow_init(&s);

    /* identity matrix */
    static const float identity[16] = {
        1,0,0,0,
        0,1,0,0,
        0,0,1,0,
        0,0,0,1
    };

    gla_shadow_set_uniform_mat4(&s, 0, identity);

    assert(s.uniform_count == 1);
    assert(s.uniforms[0].location  == 0);
    assert(s.uniforms[0].type      == GL_FLOAT_MAT4);
    assert(s.uniforms[0].data_size == 16 * sizeof(float));
    assert(s.uniforms[0].active    == true);
    assert(memcmp(s.uniforms[0].data, identity, 16 * sizeof(float)) == 0);

    printf("PASS test_uniform_mat4\n");
}

/* -------------------------------------------------------------------------
 * 4b. UniformVec3
 * ---------------------------------------------------------------------- */
static void test_uniform_vec3(void) {
    GlaShadowState s;
    gla_shadow_init(&s);

    gla_shadow_set_uniform_3f(&s, 2, 0.1f, 0.5f, 0.9f);

    assert(s.uniform_count == 1);
    assert(s.uniforms[0].location  == 2);
    assert(s.uniforms[0].type      == GL_FLOAT_VEC3);
    assert(s.uniforms[0].data_size == 3 * sizeof(float));
    assert(s.uniforms[0].active    == true);

    float vals[3];
    memcpy(vals, s.uniforms[0].data, 3 * sizeof(float));
    assert(vals[0] == 0.1f);
    assert(vals[1] == 0.5f);
    assert(vals[2] == 0.9f);

    printf("PASS test_uniform_vec3\n");
}

/* -------------------------------------------------------------------------
 * 4c. UniformVec4
 * ---------------------------------------------------------------------- */
static void test_uniform_vec4(void) {
    GlaShadowState s;
    gla_shadow_init(&s);

    gla_shadow_set_uniform_4f(&s, 3, 1.0f, 0.0f, 0.0f, 1.0f);

    assert(s.uniform_count == 1);
    assert(s.uniforms[0].location  == 3);
    assert(s.uniforms[0].type      == GL_FLOAT_VEC4);
    assert(s.uniforms[0].data_size == 4 * sizeof(float));
    assert(s.uniforms[0].active    == true);

    float vals[4];
    memcpy(vals, s.uniforms[0].data, 4 * sizeof(float));
    assert(vals[0] == 1.0f);
    assert(vals[1] == 0.0f);
    assert(vals[2] == 0.0f);
    assert(vals[3] == 1.0f);

    printf("PASS test_uniform_vec4\n");
}

/* -------------------------------------------------------------------------
 * 5. UniformOverwrite
 * ---------------------------------------------------------------------- */
static void test_uniform_overwrite(void) {
    GlaShadowState s;
    gla_shadow_init(&s);

    gla_shadow_set_uniform_1f(&s, 0, 1.0f);
    assert(s.uniform_count == 1);

    gla_shadow_set_uniform_1f(&s, 0, 2.0f);
    /* Same location → same slot, no extra allocation */
    assert(s.uniform_count == 1);

    float v;
    memcpy(&v, s.uniforms[0].data, sizeof(float));
    assert(v == 2.0f);

    printf("PASS test_uniform_overwrite\n");
}

/* -------------------------------------------------------------------------
 * 6. EnableDisable
 * ---------------------------------------------------------------------- */
static void test_enable_disable(void) {
    GlaShadowState s;
    gla_shadow_init(&s);

    gla_shadow_enable(&s, GL_DEPTH_TEST);
    assert(s.depth_test_enabled == true);

    gla_shadow_disable(&s, GL_DEPTH_TEST);
    assert(s.depth_test_enabled == false);

    gla_shadow_enable(&s, GL_BLEND);
    assert(s.blend_enabled == true);

    gla_shadow_enable(&s, GL_CULL_FACE);
    assert(s.cull_enabled == true);

    gla_shadow_enable(&s, GL_SCISSOR_TEST);
    assert(s.scissor_test_enabled == true);

    gla_shadow_disable(&s, GL_BLEND);
    assert(s.blend_enabled == false);

    printf("PASS test_enable_disable\n");
}

/* -------------------------------------------------------------------------
 * 7. ViewportAndScissor
 * ---------------------------------------------------------------------- */
static void test_viewport_and_scissor(void) {
    GlaShadowState s;
    gla_shadow_init(&s);

    gla_shadow_viewport(&s, 0, 0, 800, 600);
    assert(s.viewport[0] == 0   && s.viewport[1] == 0);
    assert(s.viewport[2] == 800 && s.viewport[3] == 600);

    gla_shadow_scissor(&s, 10, 20, 400, 300);
    assert(s.scissor[0] == 10  && s.scissor[1] == 20);
    assert(s.scissor[2] == 400 && s.scissor[3] == 300);

    printf("PASS test_viewport_and_scissor\n");
}

/* -------------------------------------------------------------------------
 * 8. BlendState
 * ---------------------------------------------------------------------- */
static void test_blend_state(void) {
    GlaShadowState s;
    gla_shadow_init(&s);

    /* GL_SRC_ALPHA = 0x0302, GL_ONE_MINUS_SRC_ALPHA = 0x0303 */
    gla_shadow_blend_func(&s, 0x0302, 0x0303);
    assert(s.blend_src == 0x0302);
    assert(s.blend_dst == 0x0303);

    printf("PASS test_blend_state\n");
}

/* -------------------------------------------------------------------------
 * 9. BufferBindings
 * ---------------------------------------------------------------------- */
static void test_buffer_bindings(void) {
    GlaShadowState s;
    gla_shadow_init(&s);

    gla_shadow_bind_buffer(&s, GL_ARRAY_BUFFER, 7);
    assert(s.bound_vbo == 7);

    gla_shadow_bind_buffer(&s, GL_ELEMENT_ARRAY_BUFFER, 8);
    assert(s.bound_ebo == 8);

    gla_shadow_bind_vao(&s, 42);
    assert(s.bound_vao == 42);

    gla_shadow_bind_framebuffer(&s, GL_FRAMEBUFFER, 9);
    assert(s.bound_fbo == 9);

    printf("PASS test_buffer_bindings\n");
}

/* -------------------------------------------------------------------------
 * 10. FrameBoundary
 * ---------------------------------------------------------------------- */
static void test_frame_boundary(void) {
    GlaShadowState s;
    gla_shadow_init(&s);

    gla_shadow_record_draw(&s);
    gla_shadow_record_draw(&s);
    gla_shadow_record_draw(&s);
    assert(s.draw_call_count == 3);
    assert(s.frame_number    == 0);

    gla_shadow_new_frame(&s);
    assert(s.draw_call_count == 0);
    assert(s.frame_number    == 1);

    /* Second frame */
    gla_shadow_record_draw(&s);
    gla_shadow_new_frame(&s);
    assert(s.draw_call_count == 0);
    assert(s.frame_number    == 2);

    printf("PASS test_frame_boundary\n");
}

/* -------------------------------------------------------------------------
 * 11. DebugGroupPushPop
 * ---------------------------------------------------------------------- */
static void test_debug_group_push_pop(void) {
    GlaShadowState s;
    gla_shadow_init(&s);

    gla_shadow_push_debug_group(&s, 1, "GroupA");
    gla_shadow_push_debug_group(&s, 2, "GroupB");
    assert(s.debug_group_depth == 2);

    gla_shadow_pop_debug_group(&s);
    assert(s.debug_group_depth == 1);

    gla_shadow_pop_debug_group(&s);
    assert(s.debug_group_depth == 0);

    /* Extra pop on empty stack should be a no-op */
    gla_shadow_pop_debug_group(&s);
    assert(s.debug_group_depth == 0);

    printf("PASS test_debug_group_push_pop\n");
}

/* -------------------------------------------------------------------------
 * 12. DebugGroupPath
 * ---------------------------------------------------------------------- */
static void test_debug_group_path(void) {
    GlaShadowState s;
    gla_shadow_init(&s);

    gla_shadow_push_debug_group(&s, 10, "GBuffer");
    gla_shadow_push_debug_group(&s, 11, "Player Mesh");

    char buf[256];
    int len = gla_shadow_get_debug_group_path(&s, buf, sizeof(buf));
    assert(len == (int)strlen("GBuffer/Player Mesh"));
    assert(strcmp(buf, "GBuffer/Player Mesh") == 0);

    printf("PASS test_debug_group_path\n");
}

/* -------------------------------------------------------------------------
 * 13. DebugGroupEmptyPath
 * ---------------------------------------------------------------------- */
static void test_debug_group_empty_path(void) {
    GlaShadowState s;
    gla_shadow_init(&s);

    char buf[256];
    int len = gla_shadow_get_debug_group_path(&s, buf, sizeof(buf));
    assert(len == 0);
    assert(buf[0] == '\0');

    printf("PASS test_debug_group_empty_path\n");
}

/* -------------------------------------------------------------------------
 * 14. DebugGroupOverflow
 * ---------------------------------------------------------------------- */
static void test_debug_group_overflow(void) {
    GlaShadowState s;
    gla_shadow_init(&s);

    /* Push GLA_MAX_DEBUG_GROUP_DEPTH + 1 groups */
    for (int i = 0; i <= GLA_MAX_DEBUG_GROUP_DEPTH; i++) {
        gla_shadow_push_debug_group(&s, (uint32_t)i, "Group");
    }
    /* Depth must be capped at max */
    assert(s.debug_group_depth == GLA_MAX_DEBUG_GROUP_DEPTH);

    printf("PASS test_debug_group_overflow\n");
}

/* -------------------------------------------------------------------------
 * 15. ClearRecording
 * ---------------------------------------------------------------------- */
static void test_clear_recording(void) {
    GlaShadowState s;
    gla_shadow_init(&s);

    assert(s.clear_count == 0);

    /* GL_COLOR_BUFFER_BIT = 0x4000, GL_DEPTH_BUFFER_BIT = 0x100 */
    gla_shadow_record_clear(&s, 0x4000);
    assert(s.clear_count == 1);
    assert(s.clear_records[0].mask == 0x4000);
    assert(s.clear_records[0].draw_call_before == 0);

    /* Record a draw call, then another clear */
    gla_shadow_record_draw(&s);
    gla_shadow_record_clear(&s, 0x4100u); /* color + depth */
    assert(s.clear_count == 2);
    assert(s.clear_records[1].mask == 0x4100u);
    assert(s.clear_records[1].draw_call_before == 1);

    /* New frame resets clear_count */
    gla_shadow_new_frame(&s);
    assert(s.clear_count == 0);
    assert(s.draw_call_count == 0);

    printf("PASS test_clear_recording\n");
}

/* -------------------------------------------------------------------------
 * 16. ClearOverflow
 * ---------------------------------------------------------------------- */
static void test_clear_overflow(void) {
    GlaShadowState s;
    gla_shadow_init(&s);

    /* Fill up to the cap */
    for (int i = 0; i <= GLA_MAX_CLEARS_PER_FRAME; i++) {
        gla_shadow_record_clear(&s, (uint32_t)i);
    }
    /* Count must be capped at GLA_MAX_CLEARS_PER_FRAME */
    assert(s.clear_count == GLA_MAX_CLEARS_PER_FRAME);

    printf("PASS test_clear_overflow\n");
}

/* -------------------------------------------------------------------------
 * 17. FramebufferTexture2D — color attachment tracking
 * ---------------------------------------------------------------------- */
static void test_framebuffer_texture_2d_color(void) {
    GlaShadowState s;
    gla_shadow_init(&s);

    /* Bind FBO 5, attach texture 42 as COLOR_ATTACHMENT0 */
    gla_shadow_bind_framebuffer(&s, GL_FRAMEBUFFER, 5);
    gla_shadow_framebuffer_texture_2d(&s, GL_FRAMEBUFFER, GL_COLOR_ATTACHMENT0, 42);

    const GlaFboInfo* info = gla_shadow_get_fbo_info(&s, 5);
    assert(info != NULL);
    assert(info->fbo_id               == 5);
    assert(info->color_attachment_tex == 42);
    assert(info->depth_attachment_tex == 0);

    /* Attach texture 99 as DEPTH_ATTACHMENT */
    gla_shadow_framebuffer_texture_2d(&s, GL_FRAMEBUFFER, GL_DEPTH_ATTACHMENT, 99);
    info = gla_shadow_get_fbo_info(&s, 5);
    assert(info->depth_attachment_tex == 99);

    /* Overwrite color attachment */
    gla_shadow_framebuffer_texture_2d(&s, GL_FRAMEBUFFER, GL_COLOR_ATTACHMENT0, 77);
    info = gla_shadow_get_fbo_info(&s, 5);
    assert(info->color_attachment_tex == 77);

    printf("PASS test_framebuffer_texture_2d_color\n");
}

/* -------------------------------------------------------------------------
 * 18. FramebufferTexture2D — default FBO (id=0) is ignored
 * ---------------------------------------------------------------------- */
static void test_framebuffer_texture_2d_default_fbo(void) {
    GlaShadowState s;
    gla_shadow_init(&s);

    /* FBO 0 is the default framebuffer — attachments should be ignored */
    gla_shadow_bind_framebuffer(&s, GL_FRAMEBUFFER, 0);
    gla_shadow_framebuffer_texture_2d(&s, GL_FRAMEBUFFER, GL_COLOR_ATTACHMENT0, 10);

    assert(s.fbo_count == 0);

    printf("PASS test_framebuffer_texture_2d_default_fbo\n");
}

/* -------------------------------------------------------------------------
 * 19. FramebufferTexture2D — multiple distinct FBOs
 * ---------------------------------------------------------------------- */
static void test_framebuffer_texture_2d_multiple_fbos(void) {
    GlaShadowState s;
    gla_shadow_init(&s);

    gla_shadow_bind_framebuffer(&s, GL_FRAMEBUFFER, 1);
    gla_shadow_framebuffer_texture_2d(&s, GL_FRAMEBUFFER, GL_COLOR_ATTACHMENT0, 11);

    gla_shadow_bind_framebuffer(&s, GL_FRAMEBUFFER, 2);
    gla_shadow_framebuffer_texture_2d(&s, GL_FRAMEBUFFER, GL_COLOR_ATTACHMENT0, 22);

    assert(s.fbo_count == 2);

    const GlaFboInfo* a = gla_shadow_get_fbo_info(&s, 1);
    const GlaFboInfo* b = gla_shadow_get_fbo_info(&s, 2);
    assert(a != NULL && a->color_attachment_tex == 11);
    assert(b != NULL && b->color_attachment_tex == 22);

    /* Lookup of unknown FBO returns NULL */
    assert(gla_shadow_get_fbo_info(&s, 99) == NULL);

    printf("PASS test_framebuffer_texture_2d_multiple_fbos\n");
}

/* -------------------------------------------------------------------------
 * main
 * ---------------------------------------------------------------------- */
int main(void) {
    test_init_defaults();
    test_texture_bindings();
    test_program_binding();
    test_uniform_mat4();
    test_uniform_vec3();
    test_uniform_vec4();
    test_uniform_overwrite();
    test_enable_disable();
    test_viewport_and_scissor();
    test_blend_state();
    test_buffer_bindings();
    test_frame_boundary();
    test_debug_group_push_pop();
    test_debug_group_path();
    test_debug_group_empty_path();
    test_debug_group_overflow();
    test_clear_recording();
    test_clear_overflow();
    test_framebuffer_texture_2d_color();
    test_framebuffer_texture_2d_default_fbo();
    test_framebuffer_texture_2d_multiple_fbos();

    printf("All shadow state tests passed.\n");
    return 0;
}
