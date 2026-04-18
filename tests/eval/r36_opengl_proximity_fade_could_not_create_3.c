// SOURCE: https://github.com/godotengine/godot/issues/112167
#include <GL/gl.h>
#include <GL/glx.h>
#include <X11/Xlib.h>
#include <stdio.h>
#include <stdlib.h>

#ifndef GL_DEPTH24_STENCIL8
#define GL_DEPTH24_STENCIL8 0x88F0
#endif
#ifndef GL_DEPTH_STENCIL
#define GL_DEPTH_STENCIL 0x84F9
#endif
#ifndef GL_UNSIGNED_INT_24_8
#define GL_UNSIGNED_INT_24_8 0x84FA
#endif

#define GL_FRAMEBUFFER                         0x8D40
#define GL_READ_FRAMEBUFFER                    0x8CA8
#define GL_DRAW_FRAMEBUFFER                    0x8CA9
#define GL_COLOR_ATTACHMENT0                   0x8CE0
#define GL_DEPTH_STENCIL_ATTACHMENT            0x821A
#define GL_FRAMEBUFFER_COMPLETE                0x8CD5
#define GL_FRAMEBUFFER_INCOMPLETE_ATTACHMENT   0x8CD6

#define GLX_CONTEXT_MAJOR_VERSION_ARB          0x2091
#define GLX_CONTEXT_MINOR_VERSION_ARB          0x2092
#define GLX_CONTEXT_PROFILE_MASK_ARB           0x9126
#define GLX_CONTEXT_CORE_PROFILE_BIT_ARB       0x00000001

typedef void   (*GenFB_t)(GLsizei, GLuint*);
typedef void   (*BindFB_t)(GLenum, GLuint);
typedef void   (*FBTex2D_t)(GLenum, GLenum, GLenum, GLuint, GLint);
typedef GLenum (*CheckFB_t)(GLenum);
typedef void   (*Blit_t)(GLint,GLint,GLint,GLint,GLint,GLint,GLint,GLint,GLbitfield,GLenum);
typedef GLXContext (*CreateCtx_t)(Display*, GLXFBConfig, GLXContext, Bool, const int*);

#define W 256
#define H 256
#define GETP(T, n) (T)glXGetProcAddressARB((const GLubyte*)n)

int main(void) {
    Display* dpy = XOpenDisplay(NULL);
    if (!dpy) { fprintf(stderr, "XOpenDisplay failed\n"); return 1; }

    int attrs[] = {
        GLX_X_RENDERABLE,  True,
        GLX_DRAWABLE_TYPE, GLX_WINDOW_BIT,
        GLX_RENDER_TYPE,   GLX_RGBA_BIT,
        GLX_RED_SIZE, 8, GLX_GREEN_SIZE, 8, GLX_BLUE_SIZE, 8, GLX_ALPHA_SIZE, 8,
        GLX_DEPTH_SIZE, 24, GLX_STENCIL_SIZE, 8,
        GLX_DOUBLEBUFFER, True,
        None
    };
    int n = 0;
    GLXFBConfig* fbc = glXChooseFBConfig(dpy, DefaultScreen(dpy), attrs, &n);
    if (!fbc || n == 0) { fprintf(stderr, "no FBConfig\n"); return 1; }

    XVisualInfo* vi = glXGetVisualFromFBConfig(dpy, fbc[0]);
    Window root = RootWindow(dpy, vi->screen);
    XSetWindowAttributes swa = {0};
    swa.colormap = XCreateColormap(dpy, root, vi->visual, AllocNone);
    Window win = XCreateWindow(dpy, root, 0, 0, W, H, 0, vi->depth,
                               InputOutput, vi->visual, CWColormap, &swa);
    XMapWindow(dpy, win);

    CreateCtx_t create_ctx = GETP(CreateCtx_t, "glXCreateContextAttribsARB");
    int ca[] = {
        GLX_CONTEXT_MAJOR_VERSION_ARB, 3,
        GLX_CONTEXT_MINOR_VERSION_ARB, 3,
        GLX_CONTEXT_PROFILE_MASK_ARB, GLX_CONTEXT_CORE_PROFILE_BIT_ARB,
        0
    };
    GLXContext ctx = create_ctx(dpy, fbc[0], 0, True, ca);
    if (!ctx) { fprintf(stderr, "ctx create failed\n"); return 1; }
    glXMakeCurrent(dpy, win, ctx);

    GenFB_t   gen_fb    = GETP(GenFB_t,   "glGenFramebuffers");
    BindFB_t  bind_fb   = GETP(BindFB_t,  "glBindFramebuffer");
    FBTex2D_t fb_tex2d  = GETP(FBTex2D_t, "glFramebufferTexture2D");
    CheckFB_t check_fb  = GETP(CheckFB_t, "glCheckFramebufferStatus");
    Blit_t    blit_fb   = GETP(Blit_t,    "glBlitFramebuffer");

    GLuint color_tex;
    glGenTextures(1, &color_tex);
    glBindTexture(GL_TEXTURE_2D, color_tex);
    glTexImage2D(GL_TEXTURE_2D, 0, GL_RGBA, W, H, 0,
                 GL_RGBA, GL_UNSIGNED_BYTE, NULL);
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MIN_FILTER, GL_LINEAR);
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MAG_FILTER, GL_LINEAR);

    // Godot compat renderer, 3D-scaling path:
    GLuint ds_tex;
    glGenTextures(1, &ds_tex);
    glBindTexture(GL_TEXTURE_2D, ds_tex);
    glTexImage2D(GL_TEXTURE_2D, 0, GL_DEPTH24_STENCIL8, W, H, 0,
                 GL_DEPTH_STENCIL,
                 GL_FLOAT,
                 NULL);
    GLenum tex_err = glGetError();
    fprintf(stderr, "glTexImage2D(depth/stencil) err=0x%04X\n", tex_err);
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MIN_FILTER, GL_NEAREST);
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MAG_FILTER, GL_NEAREST);

    GLuint fbo;
    gen_fb(1, &fbo);
    bind_fb(GL_FRAMEBUFFER, fbo);
    fb_tex2d(GL_FRAMEBUFFER, GL_COLOR_ATTACHMENT0,
             GL_TEXTURE_2D, color_tex, 0);
    fb_tex2d(GL_FRAMEBUFFER, GL_DEPTH_STENCIL_ATTACHMENT,
             GL_TEXTURE_2D, ds_tex, 0);

    GLenum status = check_fb(GL_FRAMEBUFFER);
    fprintf(stderr, "FBO status=0x%04X%s\n", status,
            status == GL_FRAMEBUFFER_INCOMPLETE_ATTACHMENT
                ? " (GL_FRAMEBUFFER_INCOMPLETE_ATTACHMENT)"
                : (status == GL_FRAMEBUFFER_COMPLETE ? " (COMPLETE)" : ""));

    // Paint default framebuffer black (so untouched = broken).
    bind_fb(GL_FRAMEBUFFER, 0);
    glViewport(0, 0, W, H);
    glClearColor(0.0f, 0.0f, 0.0f, 1.0f);
    glClear(GL_COLOR_BUFFER_BIT);

    // Paint the user FBO green — silently skipped when incomplete.
    bind_fb(GL_FRAMEBUFFER, fbo);
    glClearColor(0.0f, 1.0f, 0.0f, 1.0f);
    glClear(GL_COLOR_BUFFER_BIT);

    // Blit FBO → default. Fails with GL_INVALID_FRAMEBUFFER_OPERATION
    // when the source FBO is incomplete, so the default stays black.
    bind_fb(GL_READ_FRAMEBUFFER, fbo);
    bind_fb(GL_DRAW_FRAMEBUFFER, 0);
    blit_fb(0, 0, W, H, 0, 0, W, H, GL_COLOR_BUFFER_BIT, GL_NEAREST);

    bind_fb(GL_FRAMEBUFFER, 0);
    glFinish();

    unsigned char px[4] = {0};
    glReadPixels(W / 2, H / 2, 1, 1, GL_RGBA, GL_UNSIGNED_BYTE, px);
    fprintf(stderr, "center pixel=%u,%u,%u,%u (expected 0,255,0,255)\n",
            px[0], px[1], px[2], px[3]);

    glXMakeCurrent(dpy, None, NULL);
    glXDestroyContext(dpy, ctx);
    XDestroyWindow(dpy, win);
    XCloseDisplay(dpy);
    return 0;
}