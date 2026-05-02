// SOURCE: https://github.com/mrdoob/three.js/issues/32686
//
// This scenario is tier: snapshot. The bug lives in three.js's TSL (Three
// Shading Language) node graph compiler, specifically in how variable
// scoping interacts with logarithmicDepthBuffer's clip-space depth
// computation. It manifests only inside the JavaScript-driven WebGL2
// renderer and cannot be reproduced by a hand-written C GL program.
//
// The real eval payload is the upstream three.js snapshot; this stub only
// exists so the harness has a compilable artifact. It opens a GL 3.3 core
// context, clears, and swaps one frame.

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <X11/Xlib.h>
#include <GL/gl.h>
#include <GL/glx.h>

typedef GLXContext (*glXCreateContextAttribsARBProc)(Display*, GLXFBConfig, GLXContext, Bool, const int*);

static int ctx_attribs[] = {
    GLX_CONTEXT_MAJOR_VERSION_ARB, 3,
    GLX_CONTEXT_MINOR_VERSION_ARB, 3,
    GLX_CONTEXT_PROFILE_MASK_ARB,  GLX_CONTEXT_CORE_PROFILE_BIT_ARB,
    0
};

static int fb_attribs[] = {
    GLX_X_RENDERABLE,  True,
    GLX_DRAWABLE_TYPE, GLX_WINDOW_BIT,
    GLX_RENDER_TYPE,   GLX_RGBA_BIT,
    GLX_X_VISUAL_TYPE, GLX_TRUE_COLOR,
    GLX_DOUBLEBUFFER,  True,
    GLX_RED_SIZE, 8, GLX_GREEN_SIZE, 8, GLX_BLUE_SIZE, 8, GLX_ALPHA_SIZE, 8,
    GLX_DEPTH_SIZE, 24,
    0
};

int main(void) {
    Display* dpy = XOpenDisplay(NULL);
    if (!dpy) { fprintf(stderr, "XOpenDisplay failed\n"); return 1; }

    int screen = DefaultScreen(dpy);
    int fbcount = 0;
    GLXFBConfig* fbc = glXChooseFBConfig(dpy, screen, fb_attribs, &fbcount);
    if (!fbc || fbcount == 0) { fprintf(stderr, "glXChooseFBConfig failed\n"); return 1; }

    XVisualInfo* vi = glXGetVisualFromFBConfig(dpy, fbc[0]);
    XSetWindowAttributes swa;
    swa.colormap = XCreateColormap(dpy, RootWindow(dpy, screen), vi->visual, AllocNone);
    swa.event_mask = StructureNotifyMask;

    Window win = XCreateWindow(dpy, RootWindow(dpy, screen),
        0, 0, 320, 240, 0, vi->depth, InputOutput, vi->visual,
        CWColormap | CWEventMask, &swa);
    XMapWindow(dpy, win);

    glXCreateContextAttribsARBProc glXCreateContextAttribsARB =
        (glXCreateContextAttribsARBProc)glXGetProcAddressARB((const GLubyte*)"glXCreateContextAttribsARB");
    if (!glXCreateContextAttribsARB) { fprintf(stderr, "no glXCreateContextAttribsARB\n"); return 1; }

    GLXContext ctx = glXCreateContextAttribsARB(dpy, fbc[0], NULL, True, ctx_attribs);
    if (!ctx) { fprintf(stderr, "glXCreateContextAttribsARB failed\n"); return 1; }
    glXMakeCurrent(dpy, win, ctx);

    glClearColor(0.0f, 0.0f, 0.0f, 1.0f);
    glClear(GL_COLOR_BUFFER_BIT | GL_DEPTH_BUFFER_BIT);
    glXSwapBuffers(dpy, win);

    glXMakeCurrent(dpy, None, NULL);
    glXDestroyContext(dpy, ctx);
    XDestroyWindow(dpy, win);
    XFreeColormap(dpy, swa.colormap);
    XFree(vi);
    XFree(fbc);
    XCloseDisplay(dpy);
    return 0;
}