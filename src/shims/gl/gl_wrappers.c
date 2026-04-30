#define _GNU_SOURCE
#include <dlfcn.h>
#include <stdio.h>
#include <string.h>
#include "gl_wrappers.h"
#include "shadow_state.h"
#include "frame_capture.h"
#include "native_trace.h"

/* Declared in gl_shim.c */
extern GpaShadowState gpa_shadow;
void gpa_init(void);

/* Native-trace scan hook. Fires on glUniform* / glBindTexture in gated
 * mode, matching the browser JS scanner.
 *
 *   GPA_TRACE_NATIVE=1        → globals scan (Phase 1)
 *   GPA_TRACE_NATIVE_STACK=1  → stack-local scan (Phase 2)
 *
 * Both env vars are independent; either or both may be enabled. Each scan
 * is a no-op unless its scanner was successfully initialised. */
static inline void gpa_trace_gated(void) {
    if (gpa_native_trace_is_enabled()) {
        gpa_native_trace_scan(gpa_shadow.frame_number,
                              gpa_shadow.draw_call_count);
    }
    if (gpa_native_trace_stack_is_enabled()) {
        gpa_native_trace_scan_stack(gpa_shadow.frame_number,
                                    gpa_shadow.draw_call_count);
    }
}

/* --------------------------------------------------------------------------
 * Dispatch table initialization
 * -------------------------------------------------------------------------- */

void gpa_wrappers_init(void) {
    gpa_real_gl.glDrawArrays            = dlsym(RTLD_NEXT, "glDrawArrays");
    gpa_real_gl.glDrawElements          = dlsym(RTLD_NEXT, "glDrawElements");
    gpa_real_gl.glDrawArraysInstanced   = dlsym(RTLD_NEXT, "glDrawArraysInstanced");
    gpa_real_gl.glDrawElementsInstanced = dlsym(RTLD_NEXT, "glDrawElementsInstanced");

    gpa_real_gl.glUseProgram        = dlsym(RTLD_NEXT, "glUseProgram");
    gpa_real_gl.glUniform1f         = dlsym(RTLD_NEXT, "glUniform1f");
    gpa_real_gl.glUniform3f         = dlsym(RTLD_NEXT, "glUniform3f");
    gpa_real_gl.glUniform4f         = dlsym(RTLD_NEXT, "glUniform4f");
    gpa_real_gl.glUniform1i         = dlsym(RTLD_NEXT, "glUniform1i");
    gpa_real_gl.glUniformMatrix4fv  = dlsym(RTLD_NEXT, "glUniformMatrix4fv");
    gpa_real_gl.glUniformMatrix3fv  = dlsym(RTLD_NEXT, "glUniformMatrix3fv");

    gpa_real_gl.glActiveTexture = dlsym(RTLD_NEXT, "glActiveTexture");
    gpa_real_gl.glBindTexture   = dlsym(RTLD_NEXT, "glBindTexture");
    gpa_real_gl.glTexImage2D    = dlsym(RTLD_NEXT, "glTexImage2D");

    gpa_real_gl.glClear       = dlsym(RTLD_NEXT, "glClear");

    gpa_real_gl.glEnable      = dlsym(RTLD_NEXT, "glEnable");
    gpa_real_gl.glDisable     = dlsym(RTLD_NEXT, "glDisable");
    gpa_real_gl.glDepthFunc   = dlsym(RTLD_NEXT, "glDepthFunc");
    gpa_real_gl.glDepthMask   = dlsym(RTLD_NEXT, "glDepthMask");
    gpa_real_gl.glBlendFunc   = dlsym(RTLD_NEXT, "glBlendFunc");
    gpa_real_gl.glCullFace    = dlsym(RTLD_NEXT, "glCullFace");
    gpa_real_gl.glFrontFace   = dlsym(RTLD_NEXT, "glFrontFace");
    gpa_real_gl.glViewport    = dlsym(RTLD_NEXT, "glViewport");
    gpa_real_gl.glScissor     = dlsym(RTLD_NEXT, "glScissor");

    gpa_real_gl.glBindVertexArray      = dlsym(RTLD_NEXT, "glBindVertexArray");
    gpa_real_gl.glBindBuffer           = dlsym(RTLD_NEXT, "glBindBuffer");
    gpa_real_gl.glBindFramebuffer      = dlsym(RTLD_NEXT, "glBindFramebuffer");
    gpa_real_gl.glFramebufferTexture2D = dlsym(RTLD_NEXT, "glFramebufferTexture2D");

    gpa_real_gl.glReadPixels   = dlsym(RTLD_NEXT, "glReadPixels");
    gpa_real_gl.glGetIntegerv  = dlsym(RTLD_NEXT, "glGetIntegerv");

    gpa_real_gl.glPushDebugGroup = dlsym(RTLD_NEXT, "glPushDebugGroup");
    gpa_real_gl.glPopDebugGroup  = dlsym(RTLD_NEXT, "glPopDebugGroup");

    gpa_real_gl.glXSwapBuffers        = dlsym(RTLD_NEXT, "glXSwapBuffers");
    gpa_real_gl.glXGetProcAddressARB  = dlsym(RTLD_NEXT, "glXGetProcAddressARB");

    gpa_real_gl.eglSwapBuffers        = dlsym(RTLD_NEXT, "eglSwapBuffers");
}

/* --------------------------------------------------------------------------
 * Draw call wrappers
 * -------------------------------------------------------------------------- */

void glDrawArrays(GLenum mode, GLint first, GLsizei count) {
    gpa_init();
    gpa_real_gl.glDrawArrays(mode, first, count);
    gpa_shadow_record_draw(&gpa_shadow);
    gpa_frame_record_draw_call(&gpa_shadow, (uint32_t)mode,
                               (uint32_t)count, /*index_count=*/0,
                               /*index_type=*/0,
                               /*instance_count=*/1);
    (void)first;
}

void glDrawElements(GLenum mode, GLsizei count, GLenum type, const void* indices) {
    gpa_init();
    gpa_real_gl.glDrawElements(mode, count, type, indices);
    gpa_shadow_record_draw(&gpa_shadow);
    gpa_frame_record_draw_call(&gpa_shadow, (uint32_t)mode,
                               /*vertex_count=*/(uint32_t)count,
                               /*index_count=*/(uint32_t)count,
                               /*index_type=*/(uint32_t)type,
                               /*instance_count=*/1);
    (void)indices;
}

void glDrawArraysInstanced(GLenum mode, GLint first, GLsizei count, GLsizei instancecount) {
    gpa_init();
    gpa_real_gl.glDrawArraysInstanced(mode, first, count, instancecount);
    gpa_shadow_record_draw(&gpa_shadow);
    gpa_frame_record_draw_call(&gpa_shadow, (uint32_t)mode,
                               (uint32_t)count, /*index_count=*/0,
                               /*index_type=*/0,
                               (uint32_t)instancecount);
    (void)first;
}

void glDrawElementsInstanced(GLenum mode, GLsizei count, GLenum type,
                              const void* indices, GLsizei instancecount) {
    gpa_init();
    gpa_real_gl.glDrawElementsInstanced(mode, count, type, indices, instancecount);
    gpa_shadow_record_draw(&gpa_shadow);
    gpa_frame_record_draw_call(&gpa_shadow, (uint32_t)mode,
                               /*vertex_count=*/(uint32_t)count,
                               /*index_count=*/(uint32_t)count,
                               /*index_type=*/(uint32_t)type,
                               (uint32_t)instancecount);
    (void)indices;
}

/* --------------------------------------------------------------------------
 * Shader wrappers
 * -------------------------------------------------------------------------- */

void glUseProgram(GLuint program) {
    gpa_init();
    gpa_real_gl.glUseProgram(program);
    gpa_shadow_use_program(&gpa_shadow, program);
}

void glUniform1f(GLint location, GLfloat v0) {
    gpa_init();
    gpa_real_gl.glUniform1f(location, v0);
    gpa_shadow_set_uniform_1f(&gpa_shadow, location, v0);
    gpa_trace_gated();
}

void glUniform3f(GLint location, GLfloat v0, GLfloat v1, GLfloat v2) {
    gpa_init();
    gpa_real_gl.glUniform3f(location, v0, v1, v2);
    gpa_shadow_set_uniform_3f(&gpa_shadow, location, v0, v1, v2);
    gpa_trace_gated();
}

void glUniform4f(GLint location, GLfloat v0, GLfloat v1, GLfloat v2, GLfloat v3) {
    gpa_init();
    gpa_real_gl.glUniform4f(location, v0, v1, v2, v3);
    gpa_shadow_set_uniform_4f(&gpa_shadow, location, v0, v1, v2, v3);
    gpa_trace_gated();
}

void glUniform1i(GLint location, GLint v0) {
    gpa_init();
    gpa_real_gl.glUniform1i(location, v0);
    gpa_shadow_set_uniform_1i(&gpa_shadow, location, v0);
    gpa_trace_gated();
}

void glUniformMatrix4fv(GLint location, GLsizei count, GLboolean transpose,
                         const GLfloat* value) {
    gpa_init();
    gpa_real_gl.glUniformMatrix4fv(location, count, transpose, value);
    gpa_shadow_set_uniform_mat4(&gpa_shadow, location, value);
    gpa_trace_gated();
}

void glUniformMatrix3fv(GLint location, GLsizei count, GLboolean transpose,
                         const GLfloat* value) {
    gpa_init();
    gpa_real_gl.glUniformMatrix3fv(location, count, transpose, value);
    gpa_shadow_set_uniform_mat3(&gpa_shadow, location, value);
    gpa_trace_gated();
}

/* --------------------------------------------------------------------------
 * Texture wrappers
 * -------------------------------------------------------------------------- */

void glActiveTexture(GLenum texture) {
    gpa_init();
    gpa_real_gl.glActiveTexture(texture);
    gpa_shadow_active_texture(&gpa_shadow, texture);
}

void glBindTexture(GLenum target, GLuint texture) {
    gpa_init();
    gpa_real_gl.glBindTexture(target, texture);
    if (target == GL_TEXTURE_2D) {
        gpa_shadow_bind_texture_2d(&gpa_shadow, texture);
    }
    gpa_trace_gated();
}

void glTexImage2D(GLenum target, GLint level, GLint internalformat,
                  GLsizei width, GLsizei height, GLint border,
                  GLenum format, GLenum type, const void* pixels) {
    gpa_init();
    gpa_real_gl.glTexImage2D(target, level, internalformat, width, height,
                             border, format, type, pixels);
    /* Track texture dimensions for level 0 of GL_TEXTURE_2D */
    if (target == GL_TEXTURE_2D && level == 0) {
        uint32_t tex_id = gpa_shadow.bound_textures_2d[gpa_shadow.active_texture_unit];
        if (tex_id > 0) {
            gpa_shadow_tex_image_2d(&gpa_shadow, tex_id,
                                    (uint32_t)width, (uint32_t)height,
                                    (uint32_t)internalformat);
        }
    }
}

/* --------------------------------------------------------------------------
 * Clear wrapper
 * -------------------------------------------------------------------------- */

void glClear(GLbitfield mask) {
    gpa_init();
    gpa_real_gl.glClear(mask);
    gpa_shadow_record_clear(&gpa_shadow, (uint32_t)mask);
}

/* --------------------------------------------------------------------------
 * Pipeline state wrappers
 * -------------------------------------------------------------------------- */

void glEnable(GLenum cap) {
    gpa_init();
    gpa_real_gl.glEnable(cap);
    gpa_shadow_enable(&gpa_shadow, cap);
}

void glDisable(GLenum cap) {
    gpa_init();
    gpa_real_gl.glDisable(cap);
    gpa_shadow_disable(&gpa_shadow, cap);
}

void glDepthFunc(GLenum func) {
    gpa_init();
    gpa_real_gl.glDepthFunc(func);
    gpa_shadow_depth_func(&gpa_shadow, func);
}

void glDepthMask(GLboolean flag) {
    gpa_init();
    gpa_real_gl.glDepthMask(flag);
    gpa_shadow_depth_mask(&gpa_shadow, (bool)flag);
}

void glBlendFunc(GLenum sfactor, GLenum dfactor) {
    gpa_init();
    gpa_real_gl.glBlendFunc(sfactor, dfactor);
    gpa_shadow_blend_func(&gpa_shadow, sfactor, dfactor);
}

void glCullFace(GLenum mode) {
    gpa_init();
    gpa_real_gl.glCullFace(mode);
    gpa_shadow_cull_face(&gpa_shadow, mode);
}

void glFrontFace(GLenum mode) {
    gpa_init();
    gpa_real_gl.glFrontFace(mode);
    gpa_shadow_front_face(&gpa_shadow, mode);
}

void glViewport(GLint x, GLint y, GLsizei width, GLsizei height) {
    gpa_init();
    gpa_real_gl.glViewport(x, y, width, height);
    gpa_shadow_viewport(&gpa_shadow, x, y, width, height);
}

void glScissor(GLint x, GLint y, GLsizei width, GLsizei height) {
    gpa_init();
    gpa_real_gl.glScissor(x, y, width, height);
    gpa_shadow_scissor(&gpa_shadow, x, y, width, height);
}

/* --------------------------------------------------------------------------
 * Buffer binding wrappers
 * -------------------------------------------------------------------------- */

void glBindVertexArray(GLuint array) {
    gpa_init();
    gpa_real_gl.glBindVertexArray(array);
    gpa_shadow_bind_vao(&gpa_shadow, array);
}

void glBindBuffer(GLenum target, GLuint buffer) {
    gpa_init();
    gpa_real_gl.glBindBuffer(target, buffer);
    gpa_shadow_bind_buffer(&gpa_shadow, target, buffer);
}

void glBindFramebuffer(GLenum target, GLuint framebuffer) {
    gpa_init();
    gpa_real_gl.glBindFramebuffer(target, framebuffer);
    gpa_shadow_bind_framebuffer(&gpa_shadow, target, framebuffer);
}

void glFramebufferTexture2D(GLenum target, GLenum attachment, GLenum textarget,
                             GLuint texture, GLint level) {
    gpa_init();
    if (gpa_real_gl.glFramebufferTexture2D)
        gpa_real_gl.glFramebufferTexture2D(target, attachment, textarget, texture, level);
    gpa_shadow_framebuffer_texture_2d(&gpa_shadow, target, attachment, texture);
}

/* --------------------------------------------------------------------------
 * Readback pass-throughs (no shadow state to update)
 * -------------------------------------------------------------------------- */

void glReadPixels(GLint x, GLint y, GLsizei width, GLsizei height,
                   GLenum format, GLenum type, void* pixels) {
    gpa_init();
    gpa_real_gl.glReadPixels(x, y, width, height, format, type, pixels);
}

void glGetIntegerv(GLenum pname, GLint* data) {
    gpa_init();
    gpa_real_gl.glGetIntegerv(pname, data);
}

/* --------------------------------------------------------------------------
 * Debug group wrappers (GL_KHR_debug)
 * -------------------------------------------------------------------------- */

void glPushDebugGroup(GLenum source, GLuint id, GLsizei length, const char* message) {
    gpa_init();
    if (gpa_real_gl.glPushDebugGroup)
        gpa_real_gl.glPushDebugGroup(source, id, length, message);
    gpa_shadow_push_debug_group(&gpa_shadow, id, message);
}

void glPopDebugGroup(void) {
    gpa_init();
    if (gpa_real_gl.glPopDebugGroup)
        gpa_real_gl.glPopDebugGroup();
    gpa_shadow_pop_debug_group(&gpa_shadow);
}

/* --------------------------------------------------------------------------
 * GLX wrappers
 * -------------------------------------------------------------------------- */

void glXSwapBuffers(Display* dpy, GLXDrawable drawable) {
    gpa_init();
    gpa_frame_on_swap();             /* capture before swap (includes draw call data) */
    gpa_frame_reset_draw_calls();    /* clear per-frame buffer for next frame */
    gpa_shadow_new_frame(&gpa_shadow);
    gpa_real_gl.glXSwapBuffers(dpy, drawable);
}

/* EGL swap path — same shape as glXSwapBuffers. Triggers on chromium /
 * Wayland / Android-style stacks where libEGL is the swap entrypoint. */
unsigned int eglSwapBuffers(void* dpy, void* surface) {
    gpa_init();
    gpa_frame_on_swap();
    gpa_frame_reset_draw_calls();
    gpa_shadow_new_frame(&gpa_shadow);
    if (gpa_real_gl.eglSwapBuffers) {
        return gpa_real_gl.eglSwapBuffers(dpy, surface);
    }
    return 1;  /* EGL_TRUE */
}

/* --------------------------------------------------------------------------
 * Programmatic frame trigger
 *
 * For offscreen GL contexts (headless-gl, EGL pbuffer, FBO-only pipelines)
 * that never call glXSwapBuffers. Mirrors the body of glXSwapBuffers
 * exactly except for the (omitted) real swap. The host process loads the
 * shim under LD_PRELOAD, dlsym()s this symbol, and calls it once per
 * logical frame.
 * -------------------------------------------------------------------------- */

__attribute__((visibility("default")))
void gpa_emit_frame(void) {
    gpa_init();
    gpa_frame_on_swap();             /* capture: draw calls + framebuffer + IPC notify */
    gpa_frame_reset_draw_calls();    /* clear per-frame buffer for next frame */
    gpa_shadow_new_frame(&gpa_shadow);
}

/* Map function names to our wrapper addresses so that apps using
 * glXGetProcAddress get our interceptors, not the real GL functions. */
static __GLXextFuncPtr gpa_resolve_wrapper(const char* name) {
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
    /* Clear */
    if (strcmp(name, "glClear") == 0)                  return (__GLXextFuncPtr)glClear;
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
    if (strcmp(name, "glFramebufferTexture2D") == 0)   return (__GLXextFuncPtr)glFramebufferTexture2D;
    /* Readback */
    if (strcmp(name, "glReadPixels") == 0)             return (__GLXextFuncPtr)glReadPixels;
    if (strcmp(name, "glGetIntegerv") == 0)            return (__GLXextFuncPtr)glGetIntegerv;
    /* Debug groups */
    if (strcmp(name, "glPushDebugGroup") == 0) return (__GLXextFuncPtr)glPushDebugGroup;
    if (strcmp(name, "glPopDebugGroup") == 0)  return (__GLXextFuncPtr)glPopDebugGroup;
    return (void*)0;
}

__GLXextFuncPtr glXGetProcAddressARB(const unsigned char* procName) {
    gpa_init();
    __GLXextFuncPtr wrapper = gpa_resolve_wrapper((const char*)procName);
    if (wrapper) return wrapper;
    return gpa_real_gl.glXGetProcAddressARB(procName);
}

/* Also intercept glXGetProcAddress (non-ARB variant) */
__GLXextFuncPtr glXGetProcAddress(const unsigned char* procName) {
    gpa_init();
    __GLXextFuncPtr wrapper = gpa_resolve_wrapper((const char*)procName);
    if (wrapper) return wrapper;
    return gpa_real_gl.glXGetProcAddressARB(procName);
}
