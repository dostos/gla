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
 * main
 * ---------------------------------------------------------------------- */
int main(void) {
    test_init_defaults();
    test_texture_bindings();
    test_program_binding();
    test_uniform_mat4();
    test_uniform_overwrite();
    test_enable_disable();
    test_viewport_and_scissor();
    test_blend_state();
    test_buffer_bindings();
    test_frame_boundary();

    printf("All shadow state tests passed.\n");
    return 0;
}
