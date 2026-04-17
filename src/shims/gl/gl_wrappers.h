#ifndef GLA_GL_WRAPPERS_H
#define GLA_GL_WRAPPERS_H

#include <stdint.h>

// X11/GLX types (avoid pulling in GL headers)
typedef struct _XDisplay Display;
typedef unsigned long GLXDrawable;
typedef void (*__GLXextFuncPtr)(void);

// GL types
typedef unsigned int GLenum;
typedef int GLint;
typedef int GLsizei;
typedef unsigned int GLuint;
typedef float GLfloat;
typedef unsigned char GLboolean;
typedef void GLvoid;

// Dispatch table of real GL functions
typedef struct {
    // Draw calls
    void (*glDrawArrays)(GLenum mode, GLint first, GLsizei count);
    void (*glDrawElements)(GLenum mode, GLsizei count, GLenum type, const void* indices);
    void (*glDrawArraysInstanced)(GLenum mode, GLint first, GLsizei count, GLsizei instancecount);
    void (*glDrawElementsInstanced)(GLenum mode, GLsizei count, GLenum type, const void* indices, GLsizei instancecount);

    // Shader
    void (*glUseProgram)(GLuint program);
    void (*glUniform1f)(GLint location, GLfloat v0);
    void (*glUniform3f)(GLint location, GLfloat v0, GLfloat v1, GLfloat v2);
    void (*glUniform4f)(GLint location, GLfloat v0, GLfloat v1, GLfloat v2, GLfloat v3);
    void (*glUniform1i)(GLint location, GLint v0);
    void (*glUniformMatrix4fv)(GLint location, GLsizei count, GLboolean transpose, const GLfloat* value);
    void (*glUniformMatrix3fv)(GLint location, GLsizei count, GLboolean transpose, const GLfloat* value);

    // Textures
    void (*glActiveTexture)(GLenum texture);
    void (*glBindTexture)(GLenum target, GLuint texture);
    void (*glTexImage2D)(GLenum target, GLint level, GLint internalformat,
                         GLsizei width, GLsizei height, GLint border,
                         GLenum format, GLenum type, const void* pixels);

    // State
    void (*glEnable)(GLenum cap);
    void (*glDisable)(GLenum cap);
    void (*glDepthFunc)(GLenum func);
    void (*glDepthMask)(GLboolean flag);
    void (*glBlendFunc)(GLenum sfactor, GLenum dfactor);
    void (*glCullFace)(GLenum mode);
    void (*glFrontFace)(GLenum mode);
    void (*glViewport)(GLint x, GLint y, GLsizei width, GLsizei height);
    void (*glScissor)(GLint x, GLint y, GLsizei width, GLsizei height);

    // Buffers
    void (*glBindVertexArray)(GLuint array);
    void (*glBindBuffer)(GLenum target, GLuint buffer);
    void (*glBindFramebuffer)(GLenum target, GLuint framebuffer);

    // Readback (for frame capture)
    void (*glReadPixels)(GLint x, GLint y, GLsizei width, GLsizei height, GLenum format, GLenum type, void* pixels);
    void (*glGetIntegerv)(GLenum pname, GLint* data);

    // Debug groups (GL_KHR_debug)
    void (*glPushDebugGroup)(GLenum source, GLuint id, GLsizei length, const char* message);
    void (*glPopDebugGroup)(void);

    // GLX
    void (*glXSwapBuffers)(Display* dpy, GLXDrawable drawable);
    __GLXextFuncPtr (*glXGetProcAddressARB)(const unsigned char* procName);
} GlaRealGlFuncs;

// Global dispatch table (defined in gl_shim.c)
extern GlaRealGlFuncs gla_real_gl;

// Initialize dispatch table (called from constructor)
void gla_wrappers_init(void);

#endif // GLA_GL_WRAPPERS_H
