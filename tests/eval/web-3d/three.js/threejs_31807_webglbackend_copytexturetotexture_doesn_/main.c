// SOURCE: https://github.com/mrdoob/three.js/issues/31807
#define GL_GLEXT_PROTOTYPES
#include <GL/gl.h>
#include <GL/glx.h>
#include <GL/glext.h>
#include <X11/Xlib.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#define SIZE 8
#define LAYERS 4

static PFNGLGENFRAMEBUFFERSPROC        pglGenFramebuffers;
static PFNGLBINDFRAMEBUFFERPROC        pglBindFramebuffer;
static PFNGLFRAMEBUFFERTEXTURELAYERPROC pglFramebufferTextureLayer;
static PFNGLBLITFRAMEBUFFERPROC        pglBlitFramebuffer;
static PFNGLTEXIMAGE3DPROC             pglTexImage3D;
static PFNGLTEXSUBIMAGE3DPROC          pglTexSubImage3D;

#define LOAD(fn) p##fn = (void*)glXGetProcAddress((const GLubyte*)#fn)

static void load_gl(void) {
    LOAD(glGenFramebuffers);
    LOAD(glBindFramebuffer);
    LOAD(glFramebufferTextureLayer);
    LOAD(glBlitFramebuffer);
    LOAD(glTexImage3D);
    LOAD(glTexSubImage3D);
}

int main(void) {
    Display *dpy = XOpenDisplay(NULL);
    if (!dpy) { fprintf(stderr, "no display\n"); return 1; }

    int visual_attrs[] = {
        GLX_X_RENDERABLE, True,
        GLX_DRAWABLE_TYPE, GLX_WINDOW_BIT,
        GLX_RENDER_TYPE, GLX_RGBA_BIT,
        GLX_X_VISUAL_TYPE, GLX_TRUE_COLOR,
        GLX_RED_SIZE, 8, GLX_GREEN_SIZE, 8, GLX_BLUE_SIZE, 8, GLX_ALPHA_SIZE, 8,
        GLX_DEPTH_SIZE, 24,
        GLX_DOUBLEBUFFER, True,
        None
    };
    int fb_count = 0;
    GLXFBConfig *fbc = glXChooseFBConfig(dpy, DefaultScreen(dpy), visual_attrs, &fb_count);
    if (!fbc || fb_count <= 0) { fprintf(stderr, "no fbc\n"); return 1; }

    XVisualInfo *vi = glXGetVisualFromFBConfig(dpy, fbc[0]);
    XSetWindowAttributes swa;
    memset(&swa, 0, sizeof(swa));
    swa.colormap = XCreateColormap(dpy, RootWindow(dpy, vi->screen), vi->visual, AllocNone);
    Window win = XCreateWindow(dpy, RootWindow(dpy, vi->screen), 0, 0, 64, 64, 0,
                               vi->depth, InputOutput, vi->visual, CWColormap, &swa);

    typedef GLXContext (*glXCreateContextAttribsARB_t)(Display*, GLXFBConfig, GLXContext, Bool, const int*);
    glXCreateContextAttribsARB_t glXCreateContextAttribsARB =
        (glXCreateContextAttribsARB_t)glXGetProcAddress((const GLubyte*)"glXCreateContextAttribsARB");

    int ctx_attrs[] = {
        GLX_CONTEXT_MAJOR_VERSION_ARB, 3,
        GLX_CONTEXT_MINOR_VERSION_ARB, 3,
        GLX_CONTEXT_PROFILE_MASK_ARB, GLX_CONTEXT_CORE_PROFILE_BIT_ARB,
        None
    };
    GLXContext ctx = glXCreateContextAttribsARB(dpy, fbc[0], 0, True, ctx_attrs);
    glXMakeCurrent(dpy, win, ctx);
    load_gl();

    // Source 3D texture: each layer filled with a distinct solid color.
    GLuint src;
    glGenTextures(1, &src);
    glBindTexture(GL_TEXTURE_3D, src);
    pglTexImage3D(GL_TEXTURE_3D, 0, GL_RGBA8, SIZE, SIZE, LAYERS, 0,
                  GL_RGBA, GL_UNSIGNED_BYTE, NULL);
    glTexParameteri(GL_TEXTURE_3D, GL_TEXTURE_MIN_FILTER, GL_NEAREST);
    glTexParameteri(GL_TEXTURE_3D, GL_TEXTURE_MAG_FILTER, GL_NEAREST);

    unsigned char layer_data[SIZE*SIZE*4];
    for (int z = 0; z < LAYERS; z++) {
        unsigned char r = (z == 0 || z == 3) ? 255 : 0;
        unsigned char g = (z == 1 || z == 3) ? 255 : 0;
        unsigned char b = (z == 2)           ? 255 : 0;
        for (int i = 0; i < SIZE*SIZE; i++) {
            layer_data[i*4+0] = r;
            layer_data[i*4+1] = g;
            layer_data[i*4+2] = b;
            layer_data[i*4+3] = 255;
        }
        pglTexSubImage3D(GL_TEXTURE_3D, 0, 0, 0, z, SIZE, SIZE, 1,
                         GL_RGBA, GL_UNSIGNED_BYTE, layer_data);
    }

    // Destination 3D texture, zero-initialized on every layer.
    GLuint dst;
    glGenTextures(1, &dst);
    glBindTexture(GL_TEXTURE_3D, dst);
    pglTexImage3D(GL_TEXTURE_3D, 0, GL_RGBA8, SIZE, SIZE, LAYERS, 0,
                  GL_RGBA, GL_UNSIGNED_BYTE, NULL);
    glTexParameteri(GL_TEXTURE_3D, GL_TEXTURE_MIN_FILTER, GL_NEAREST);
    glTexParameteri(GL_TEXTURE_3D, GL_TEXTURE_MAG_FILTER, GL_NEAREST);
    unsigned char zeros[SIZE*SIZE*4];
    memset(zeros, 0, sizeof(zeros));
    for (int z = 0; z < LAYERS; z++) {
        pglTexSubImage3D(GL_TEXTURE_3D, 0, 0, 0, z, SIZE, SIZE, 1,
                         GL_RGBA, GL_UNSIGNED_BYTE, zeros);
    }

    // Copy src -> dst via FBO blit.
    GLuint read_fbo = 0, draw_fbo = 0;
    pglGenFramebuffers(1, &read_fbo);
    pglGenFramebuffers(1, &draw_fbo);

    pglBindFramebuffer(GL_READ_FRAMEBUFFER, read_fbo);
    pglFramebufferTextureLayer(GL_READ_FRAMEBUFFER, GL_COLOR_ATTACHMENT0, src, 0, 0);
    pglBindFramebuffer(GL_DRAW_FRAMEBUFFER, draw_fbo);
    pglFramebufferTextureLayer(GL_DRAW_FRAMEBUFFER, GL_COLOR_ATTACHMENT0, dst, 0, 0);
    pglBlitFramebuffer(0, 0, SIZE, SIZE, 0, 0, SIZE, SIZE,
                       GL_COLOR_BUFFER_BIT, GL_NEAREST);

    // Read back the center texel of every destination layer.
    GLuint probe_fbo = 0;
    pglGenFramebuffers(1, &probe_fbo);
    pglBindFramebuffer(GL_FRAMEBUFFER, probe_fbo);
    for (int z = 0; z < LAYERS; z++) {
        pglFramebufferTextureLayer(GL_FRAMEBUFFER, GL_COLOR_ATTACHMENT0, dst, 0, z);
        unsigned char px[4] = {0,0,0,0};
        glReadPixels(SIZE/2, SIZE/2, 1, 1, GL_RGBA, GL_UNSIGNED_BYTE, px);
        printf("dst layer %d center rgba=%u,%u,%u,%u\n", z, px[0], px[1], px[2], px[3]);
    }

    glXSwapBuffers(dpy, win);

    glXMakeCurrent(dpy, 0, 0);
    glXDestroyContext(dpy, ctx);
    XDestroyWindow(dpy, win);
    XCloseDisplay(dpy);
    return 0;
}