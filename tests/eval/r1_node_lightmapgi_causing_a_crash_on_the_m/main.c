// SOURCE: https://github.com/godotengine/godot/issues/118136
// Minimal GLES-compat stand-in for a LightmapGI bake dispatch on the
// Compatibility (OpenGL ES 3.2) renderer: render a scene into an FBO with a
// floating-point color attachment (what the bake accumulator uses) and then
// read it back.  This is the shape of the operation that is reported to
// crash on Adreno 710; it does not itself reproduce the crash on desktop.
#include <GL/gl.h>
#include <GL/glx.h>
#include <X11/Xlib.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

typedef void (*PFNGLGENFBPROC)(GLsizei, GLuint*);
typedef void (*PFNGLBINDFBPROC)(GLenum, GLuint);
typedef void (*PFNGLFBTEX2DPROC)(GLenum, GLenum, GLenum, GLuint, GLint);
typedef GLenum (*PFNGLCHECKFBPROC)(GLenum);
static PFNGLGENFBPROC glGenFramebuffersX;
static PFNGLBINDFBPROC glBindFramebufferX;
static PFNGLFBTEX2DPROC glFramebufferTexture2DX;
static PFNGLCHECKFBPROC glCheckFramebufferStatusX;

static void load_gl(void) {
    glGenFramebuffersX        = (PFNGLGENFBPROC)        glXGetProcAddress((const GLubyte*)"glGenFramebuffers");
    glBindFramebufferX        = (PFNGLBINDFBPROC)       glXGetProcAddress((const GLubyte*)"glBindFramebuffer");
    glFramebufferTexture2DX   = (PFNGLFBTEX2DPROC)      glXGetProcAddress((const GLubyte*)"glFramebufferTexture2D");
    glCheckFramebufferStatusX = (PFNGLCHECKFBPROC)      glXGetProcAddress((const GLubyte*)"glCheckFramebufferStatus");
}

int main(void) {
    Display* dpy = XOpenDisplay(NULL);
    if (!dpy) { fprintf(stderr, "no display\n"); return 1; }
    int attr[] = { GLX_RGBA, GLX_DEPTH_SIZE, 24, GLX_DOUBLEBUFFER, None };
    XVisualInfo* vi = glXChooseVisual(dpy, 0, attr);
    if (!vi) { fprintf(stderr, "no visual\n"); return 1; }
    Window root = DefaultRootWindow(dpy);
    XSetWindowAttributes swa = {0};
    swa.colormap = XCreateColormap(dpy, root, vi->visual, AllocNone);
    Window win = XCreateWindow(dpy, root, 0, 0, 256, 256, 0, vi->depth,
                               InputOutput, vi->visual, CWColormap, &swa);
    XMapWindow(dpy, win);
    GLXContext ctx = glXCreateContext(dpy, vi, NULL, GL_TRUE);
    glXMakeCurrent(dpy, win, ctx);
    load_gl();

    // Bake target: float color attachment, like a lightmap accumulator.
    GLuint tex; glGenTextures(1, &tex);
    glBindTexture(GL_TEXTURE_2D, tex);
    glTexImage2D(GL_TEXTURE_2D, 0, GL_RGBA16F, 512, 512, 0, GL_RGBA, GL_FLOAT, NULL);
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MIN_FILTER, GL_LINEAR);
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MAG_FILTER, GL_LINEAR);

    GLuint fbo; glGenFramebuffersX(1, &fbo);
    glBindFramebufferX(GL_FRAMEBUFFER, fbo);
    glFramebufferTexture2DX(GL_FRAMEBUFFER, GL_COLOR_ATTACHMENT0, GL_TEXTURE_2D, tex, 0);
    GLenum st = glCheckFramebufferStatusX(GL_FRAMEBUFFER);
    if (st != GL_FRAMEBUFFER_COMPLETE) {
        fprintf(stderr, "FBO incomplete: 0x%x\n", st);
    }

    glViewport(0, 0, 512, 512);
    glClearColor(0.1f, 0.1f, 0.1f, 1.0f);
    glClear(GL_COLOR_BUFFER_BIT);

    // Many small quads — stands in for per-texel lightmap accumulation.
    for (int i = 0; i < 64; i++) {
        glScissor((i % 8) * 64, (i / 8) * 64, 64, 64);
        glEnable(GL_SCISSOR_TEST);
        glClearColor((i % 8) / 8.0f, (i / 8) / 8.0f, 0.5f, 1.0f);
        glClear(GL_COLOR_BUFFER_BIT);
    }
    glDisable(GL_SCISSOR_TEST);

    float* px = (float*)malloc(512 * 512 * 4 * sizeof(float));
    glReadPixels(0, 0, 512, 512, GL_RGBA, GL_FLOAT, px);
    free(px);

    glBindFramebufferX(GL_FRAMEBUFFER, 0);
    glXSwapBuffers(dpy, win);
    glXMakeCurrent(dpy, None, NULL);
    glXDestroyContext(dpy, ctx);
    XDestroyWindow(dpy, win);
    XCloseDisplay(dpy);
    return 0;
}