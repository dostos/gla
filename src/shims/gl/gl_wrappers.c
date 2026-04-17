#define _GNU_SOURCE
#include <dlfcn.h>
#include <stdio.h>
#include <string.h>
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
    gla_real_gl.glTexImage2D    = dlsym(RTLD_NEXT, "glTexImage2D");

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

    gla_real_gl.glPushDebugGroup = dlsym(RTLD_NEXT, "glPushDebugGroup");
    gla_real_gl.glPopDebugGroup  = dlsym(RTLD_NEXT, "glPopDebugGroup");

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
    gla_frame_record_draw_call(&gla_shadow, (uint32_t)mode,
                               (uint32_t)count, /*index_count=*/0,
                               /*instance_count=*/1);
    (void)first;
}

void glDrawElements(GLenum mode, GLsizei count, GLenum type, const void* indices) {
    gla_init();
    gla_real_gl.glDrawElements(mode, count, type, indices);
    gla_shadow_record_draw(&gla_shadow);
    gla_frame_record_draw_call(&gla_shadow, (uint32_t)mode,
                               /*vertex_count=*/(uint32_t)count,
                               /*index_count=*/(uint32_t)count,
                               /*instance_count=*/1);
    (void)type; (void)indices;
}

void glDrawArraysInstanced(GLenum mode, GLint first, GLsizei count, GLsizei instancecount) {
    gla_init();
    gla_real_gl.glDrawArraysInstanced(mode, first, count, instancecount);
    gla_shadow_record_draw(&gla_shadow);
    gla_frame_record_draw_call(&gla_shadow, (uint32_t)mode,
                               (uint32_t)count, /*index_count=*/0,
                               (uint32_t)instancecount);
    (void)first;
}

void glDrawElementsInstanced(GLenum mode, GLsizei count, GLenum type,
                              const void* indices, GLsizei instancecount) {
    gla_init();
    gla_real_gl.glDrawElementsInstanced(mode, count, type, indices, instancecount);
    gla_shadow_record_draw(&gla_shadow);
    gla_frame_record_draw_call(&gla_shadow, (uint32_t)mode,
                               /*vertex_count=*/(uint32_t)count,
                               /*index_count=*/(uint32_t)count,
                               (uint32_t)instancecount);
    (void)type; (void)indices;
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

void glTexImage2D(GLenum target, GLint level, GLint internalformat,
                  GLsizei width, GLsizei height, GLint border,
                  GLenum format, GLenum type, const void* pixels) {
    gla_init();
    gla_real_gl.glTexImage2D(target, level, internalformat, width, height,
                             border, format, type, pixels);
    /* Track texture dimensions for level 0 of GL_TEXTURE_2D */
    if (target == GL_TEXTURE_2D && level == 0) {
        uint32_t tex_id = gla_shadow.bound_textures_2d[gla_shadow.active_texture_unit];
        if (tex_id > 0) {
            gla_shadow_tex_image_2d(&gla_shadow, tex_id,
                                    (uint32_t)width, (uint32_t)height,
                                    (uint32_t)internalformat);
        }
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
 * Debug group wrappers (GL_KHR_debug)
 * -------------------------------------------------------------------------- */

void glPushDebugGroup(GLenum source, GLuint id, GLsizei length, const char* message) {
    gla_init();
    if (gla_real_gl.glPushDebugGroup)
        gla_real_gl.glPushDebugGroup(source, id, length, message);
    gla_shadow_push_debug_group(&gla_shadow, id, message);
}

void glPopDebugGroup(void) {
    gla_init();
    if (gla_real_gl.glPopDebugGroup)
        gla_real_gl.glPopDebugGroup();
    gla_shadow_pop_debug_group(&gla_shadow);
}

/* --------------------------------------------------------------------------
 * GLX wrappers
 * -------------------------------------------------------------------------- */

void glXSwapBuffers(Display* dpy, GLXDrawable drawable) {
    gla_init();
    gla_frame_on_swap();             /* capture before swap (includes draw call data) */
    gla_frame_reset_draw_calls();    /* clear per-frame buffer for next frame */
    gla_shadow_new_frame(&gla_shadow);
    gla_real_gl.glXSwapBuffers(dpy, drawable);
}

/* Map function names to our wrapper addresses so that apps using
 * glXGetProcAddress get our interceptors, not the real GL functions. */
static __GLXextFuncPtr gla_resolve_wrapper(const char* name) {
    if (!name) return (void*)0;
    /* Draw calls */
    if (strcmp(name, "glDrawArrays") == 0)            return (__GLXextFuncPtr)glDrawArrays;
    if (strcmp(name, "glDrawElements") == 0)           return (__GLXextFuncPtr)glDrawElements;
    if (strcmp(name, "glDrawArraysInstanced") == 0)    return (__GLXextFuncPtr)glDrawArraysInstanced;
    if (strcmp(name, "glDrawElementsInstanced") == 0)  return (__GLXextFuncPtr)glDrawElementsInstanced;
    /* Shader */
    if (strcmp(name, "glUseProgram") == 0)             return (__GLXextFuncPtr)glUseProgram;
    if (strcmp(name, "glUniform1f") == 0)              return (__GLXextFuncPtr)glUniform1f;
    if (strcmp(name, "glUniform3f") == 0)              return (__GLXextFuncPtr)glUniform3f;
    if (strcmp(name, "glUniform4f") == 0)              return (__GLXextFuncPtr)glUniform4f;
    if (strcmp(name, "glUniform1i") == 0)              return (__GLXextFuncPtr)glUniform1i;
    if (strcmp(name, "glUniformMatrix4fv") == 0)       return (__GLXextFuncPtr)glUniformMatrix4fv;
    if (strcmp(name, "glUniformMatrix3fv") == 0)       return (__GLXextFuncPtr)glUniformMatrix3fv;
    /* Textures */
    if (strcmp(name, "glActiveTexture") == 0)          return (__GLXextFuncPtr)glActiveTexture;
    if (strcmp(name, "glBindTexture") == 0)            return (__GLXextFuncPtr)glBindTexture;
    if (strcmp(name, "glTexImage2D") == 0)             return (__GLXextFuncPtr)glTexImage2D;
    /* State */
    if (strcmp(name, "glEnable") == 0)                 return (__GLXextFuncPtr)glEnable;
    if (strcmp(name, "glDisable") == 0)                return (__GLXextFuncPtr)glDisable;
    if (strcmp(name, "glDepthFunc") == 0)              return (__GLXextFuncPtr)glDepthFunc;
    if (strcmp(name, "glDepthMask") == 0)              return (__GLXextFuncPtr)glDepthMask;
    if (strcmp(name, "glBlendFunc") == 0)              return (__GLXextFuncPtr)glBlendFunc;
    if (strcmp(name, "glCullFace") == 0)               return (__GLXextFuncPtr)glCullFace;
    if (strcmp(name, "glFrontFace") == 0)              return (__GLXextFuncPtr)glFrontFace;
    if (strcmp(name, "glViewport") == 0)               return (__GLXextFuncPtr)glViewport;
    if (strcmp(name, "glScissor") == 0)                return (__GLXextFuncPtr)glScissor;
    /* Buffers */
    if (strcmp(name, "glBindVertexArray") == 0)        return (__GLXextFuncPtr)glBindVertexArray;
    if (strcmp(name, "glBindBuffer") == 0)             return (__GLXextFuncPtr)glBindBuffer;
    if (strcmp(name, "glBindFramebuffer") == 0)        return (__GLXextFuncPtr)glBindFramebuffer;
    /* Readback */
    if (strcmp(name, "glReadPixels") == 0)             return (__GLXextFuncPtr)glReadPixels;
    if (strcmp(name, "glGetIntegerv") == 0)            return (__GLXextFuncPtr)glGetIntegerv;
    /* Debug groups */
    if (strcmp(name, "glPushDebugGroup") == 0) return (__GLXextFuncPtr)glPushDebugGroup;
    if (strcmp(name, "glPopDebugGroup") == 0)  return (__GLXextFuncPtr)glPopDebugGroup;
    return (void*)0;
}

__GLXextFuncPtr glXGetProcAddressARB(const unsigned char* procName) {
    gla_init();
    __GLXextFuncPtr wrapper = gla_resolve_wrapper((const char*)procName);
    if (wrapper) return wrapper;
    return gla_real_gl.glXGetProcAddressARB(procName);
}

/* Also intercept glXGetProcAddress (non-ARB variant) */
__GLXextFuncPtr glXGetProcAddress(const unsigned char* procName) {
    gla_init();
    __GLXextFuncPtr wrapper = gla_resolve_wrapper((const char*)procName);
    if (wrapper) return wrapper;
    return gla_real_gl.glXGetProcAddressARB(procName);
}
