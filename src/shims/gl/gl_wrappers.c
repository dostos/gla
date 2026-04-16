#define _GNU_SOURCE
#include <dlfcn.h>
#include "gl_wrappers.h"
#include "shadow_state.h"
#include "frame_capture.h"

/* Declared in gl_shim.c */
extern GlaShadowState gla_shadow;
void gla_init(void);

/* --------------------------------------------------------------------------
 * Dispatch table initialization
 * -------------------------------------------------------------------------- */

void gla_wrappers_init(void) {
    gla_real_gl.glDrawArrays            = dlsym(RTLD_NEXT, "glDrawArrays");
    gla_real_gl.glDrawElements          = dlsym(RTLD_NEXT, "glDrawElements");
    gla_real_gl.glDrawArraysInstanced   = dlsym(RTLD_NEXT, "glDrawArraysInstanced");
    gla_real_gl.glDrawElementsInstanced = dlsym(RTLD_NEXT, "glDrawElementsInstanced");

    gla_real_gl.glUseProgram        = dlsym(RTLD_NEXT, "glUseProgram");
    gla_real_gl.glUniform1f         = dlsym(RTLD_NEXT, "glUniform1f");
    gla_real_gl.glUniform3f         = dlsym(RTLD_NEXT, "glUniform3f");
    gla_real_gl.glUniform4f         = dlsym(RTLD_NEXT, "glUniform4f");
    gla_real_gl.glUniform1i         = dlsym(RTLD_NEXT, "glUniform1i");
    gla_real_gl.glUniformMatrix4fv  = dlsym(RTLD_NEXT, "glUniformMatrix4fv");
    gla_real_gl.glUniformMatrix3fv  = dlsym(RTLD_NEXT, "glUniformMatrix3fv");

    gla_real_gl.glActiveTexture = dlsym(RTLD_NEXT, "glActiveTexture");
    gla_real_gl.glBindTexture   = dlsym(RTLD_NEXT, "glBindTexture");

    gla_real_gl.glEnable      = dlsym(RTLD_NEXT, "glEnable");
    gla_real_gl.glDisable     = dlsym(RTLD_NEXT, "glDisable");
    gla_real_gl.glDepthFunc   = dlsym(RTLD_NEXT, "glDepthFunc");
    gla_real_gl.glDepthMask   = dlsym(RTLD_NEXT, "glDepthMask");
    gla_real_gl.glBlendFunc   = dlsym(RTLD_NEXT, "glBlendFunc");
    gla_real_gl.glCullFace    = dlsym(RTLD_NEXT, "glCullFace");
    gla_real_gl.glFrontFace   = dlsym(RTLD_NEXT, "glFrontFace");
    gla_real_gl.glViewport    = dlsym(RTLD_NEXT, "glViewport");
    gla_real_gl.glScissor     = dlsym(RTLD_NEXT, "glScissor");

    gla_real_gl.glBindVertexArray  = dlsym(RTLD_NEXT, "glBindVertexArray");
    gla_real_gl.glBindBuffer       = dlsym(RTLD_NEXT, "glBindBuffer");
    gla_real_gl.glBindFramebuffer  = dlsym(RTLD_NEXT, "glBindFramebuffer");

    gla_real_gl.glReadPixels   = dlsym(RTLD_NEXT, "glReadPixels");
    gla_real_gl.glGetIntegerv  = dlsym(RTLD_NEXT, "glGetIntegerv");

    gla_real_gl.glXSwapBuffers        = dlsym(RTLD_NEXT, "glXSwapBuffers");
    gla_real_gl.glXGetProcAddressARB  = dlsym(RTLD_NEXT, "glXGetProcAddressARB");
}

/* --------------------------------------------------------------------------
 * Draw call wrappers
 * -------------------------------------------------------------------------- */

void glDrawArrays(GLenum mode, GLint first, GLsizei count) {
    gla_init();
    gla_real_gl.glDrawArrays(mode, first, count);
    gla_shadow_record_draw(&gla_shadow);
}

void glDrawElements(GLenum mode, GLsizei count, GLenum type, const void* indices) {
    gla_init();
    gla_real_gl.glDrawElements(mode, count, type, indices);
    gla_shadow_record_draw(&gla_shadow);
}

void glDrawArraysInstanced(GLenum mode, GLint first, GLsizei count, GLsizei instancecount) {
    gla_init();
    gla_real_gl.glDrawArraysInstanced(mode, first, count, instancecount);
    gla_shadow_record_draw(&gla_shadow);
}

void glDrawElementsInstanced(GLenum mode, GLsizei count, GLenum type,
                              const void* indices, GLsizei instancecount) {
    gla_init();
    gla_real_gl.glDrawElementsInstanced(mode, count, type, indices, instancecount);
    gla_shadow_record_draw(&gla_shadow);
}

/* --------------------------------------------------------------------------
 * Shader wrappers
 * -------------------------------------------------------------------------- */

void glUseProgram(GLuint program) {
    gla_init();
    gla_real_gl.glUseProgram(program);
    gla_shadow_use_program(&gla_shadow, program);
}

void glUniform1f(GLint location, GLfloat v0) {
    gla_init();
    gla_real_gl.glUniform1f(location, v0);
    gla_shadow_set_uniform_1f(&gla_shadow, location, v0);
}

void glUniform3f(GLint location, GLfloat v0, GLfloat v1, GLfloat v2) {
    gla_init();
    gla_real_gl.glUniform3f(location, v0, v1, v2);
    gla_shadow_set_uniform_3f(&gla_shadow, location, v0, v1, v2);
}

void glUniform4f(GLint location, GLfloat v0, GLfloat v1, GLfloat v2, GLfloat v3) {
    gla_init();
    gla_real_gl.glUniform4f(location, v0, v1, v2, v3);
    gla_shadow_set_uniform_4f(&gla_shadow, location, v0, v1, v2, v3);
}

void glUniform1i(GLint location, GLint v0) {
    gla_init();
    gla_real_gl.glUniform1i(location, v0);
    gla_shadow_set_uniform_1i(&gla_shadow, location, v0);
}

void glUniformMatrix4fv(GLint location, GLsizei count, GLboolean transpose,
                         const GLfloat* value) {
    gla_init();
    gla_real_gl.glUniformMatrix4fv(location, count, transpose, value);
    gla_shadow_set_uniform_mat4(&gla_shadow, location, value);
}

void glUniformMatrix3fv(GLint location, GLsizei count, GLboolean transpose,
                         const GLfloat* value) {
    gla_init();
    gla_real_gl.glUniformMatrix3fv(location, count, transpose, value);
    gla_shadow_set_uniform_mat3(&gla_shadow, location, value);
}

/* --------------------------------------------------------------------------
 * Texture wrappers
 * -------------------------------------------------------------------------- */

void glActiveTexture(GLenum texture) {
    gla_init();
    gla_real_gl.glActiveTexture(texture);
    gla_shadow_active_texture(&gla_shadow, texture);
}

void glBindTexture(GLenum target, GLuint texture) {
    gla_init();
    gla_real_gl.glBindTexture(target, texture);
    if (target == GL_TEXTURE_2D) {
        gla_shadow_bind_texture_2d(&gla_shadow, texture);
    }
}

/* --------------------------------------------------------------------------
 * Pipeline state wrappers
 * -------------------------------------------------------------------------- */

void glEnable(GLenum cap) {
    gla_init();
    gla_real_gl.glEnable(cap);
    gla_shadow_enable(&gla_shadow, cap);
}

void glDisable(GLenum cap) {
    gla_init();
    gla_real_gl.glDisable(cap);
    gla_shadow_disable(&gla_shadow, cap);
}

void glDepthFunc(GLenum func) {
    gla_init();
    gla_real_gl.glDepthFunc(func);
    gla_shadow_depth_func(&gla_shadow, func);
}

void glDepthMask(GLboolean flag) {
    gla_init();
    gla_real_gl.glDepthMask(flag);
    gla_shadow_depth_mask(&gla_shadow, (bool)flag);
}

void glBlendFunc(GLenum sfactor, GLenum dfactor) {
    gla_init();
    gla_real_gl.glBlendFunc(sfactor, dfactor);
    gla_shadow_blend_func(&gla_shadow, sfactor, dfactor);
}

void glCullFace(GLenum mode) {
    gla_init();
    gla_real_gl.glCullFace(mode);
    gla_shadow_cull_face(&gla_shadow, mode);
}

void glFrontFace(GLenum mode) {
    gla_init();
    gla_real_gl.glFrontFace(mode);
    gla_shadow_front_face(&gla_shadow, mode);
}

void glViewport(GLint x, GLint y, GLsizei width, GLsizei height) {
    gla_init();
    gla_real_gl.glViewport(x, y, width, height);
    gla_shadow_viewport(&gla_shadow, x, y, width, height);
}

void glScissor(GLint x, GLint y, GLsizei width, GLsizei height) {
    gla_init();
    gla_real_gl.glScissor(x, y, width, height);
    gla_shadow_scissor(&gla_shadow, x, y, width, height);
}

/* --------------------------------------------------------------------------
 * Buffer binding wrappers
 * -------------------------------------------------------------------------- */

void glBindVertexArray(GLuint array) {
    gla_init();
    gla_real_gl.glBindVertexArray(array);
    gla_shadow_bind_vao(&gla_shadow, array);
}

void glBindBuffer(GLenum target, GLuint buffer) {
    gla_init();
    gla_real_gl.glBindBuffer(target, buffer);
    gla_shadow_bind_buffer(&gla_shadow, target, buffer);
}

void glBindFramebuffer(GLenum target, GLuint framebuffer) {
    gla_init();
    gla_real_gl.glBindFramebuffer(target, framebuffer);
    gla_shadow_bind_framebuffer(&gla_shadow, target, framebuffer);
}

/* --------------------------------------------------------------------------
 * Readback pass-throughs (no shadow state to update)
 * -------------------------------------------------------------------------- */

void glReadPixels(GLint x, GLint y, GLsizei width, GLsizei height,
                   GLenum format, GLenum type, void* pixels) {
    gla_init();
    gla_real_gl.glReadPixels(x, y, width, height, format, type, pixels);
}

void glGetIntegerv(GLenum pname, GLint* data) {
    gla_init();
    gla_real_gl.glGetIntegerv(pname, data);
}

/* --------------------------------------------------------------------------
 * GLX wrappers
 * -------------------------------------------------------------------------- */

void glXSwapBuffers(Display* dpy, GLXDrawable drawable) {
    gla_init();
    gla_frame_on_swap();   /* capture before swap */
    gla_shadow_new_frame(&gla_shadow);
    gla_real_gl.glXSwapBuffers(dpy, drawable);
}

__GLXextFuncPtr glXGetProcAddressARB(const unsigned char* procName) {
    gla_init();
    return gla_real_gl.glXGetProcAddressARB(procName);
}
