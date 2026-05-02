// SOURCE: https://github.com/mapbox/mapbox-gl-js/issues/13415
//
// This scenario is tier: snapshot. The bug lives inside mapbox-gl-js's
// symbol-layer and image-atlas code, which has no meaningful minimal-C
// equivalent. The eval payload is the upstream snapshot at the parent of
// the fix commit; see scenario.md for details.
//
// This file exists only to satisfy the core harness contract. It creates a
// GL 3.3 context via GLX and renders a single solid-color frame so the
// capture shim has something to attach to.

#include <GL/gl.h>
#include <GL/glx.h>
#include <X11/Xlib.h>
#include <stdio.h>
#include <stdlib.h>

static int visual_attribs[] = {
    GLX_X_RENDERABLE, True,
    GLX_DRAWABLE_TYPE, GLX_WINDOW_BIT,
    GLX_RENDER_TYPE, GLX_RGBA_BIT,
    GLX_X_VISUAL_TYPE, GLX_TRUE_COLOR,
    GLX_RED_SIZE, 8, GLX_GREEN_SIZE, 8, GLX_BLUE_SIZE, 8, GLX_ALPHA_SIZE, 8,
    GLX_DEPTH_SIZE, 24, GLX_DOUBLEBUFFER, True,
    None
};

typedef GLXContext (*glXCreateContextAttribsARBProc)(Display*, GLXFBConfig, GLXContext, Bool, const int*);

int main(void) {
    Display *dpy = XOpenDisplay(NULL);
    if (!dpy) { fprintf(stderr, "no display\n"); return 1; }

    int fbcount = 0;
    GLXFBConfig *fbc = glXChooseFBConfig(dpy, DefaultScreen(dpy), visual_attribs, &fbcount);
    if (!fbc || fbcount == 0) { fprintf(stderr, "no fbconfig\n"); return 1; }
    GLXFBConfig chosen = fbc[0];

    XVisualInfo *vi = glXGetVisualFromFBConfig(dpy, chosen);
    XSetWindowAttributes swa;
    swa.colormap = XCreateColormap(dpy, RootWindow(dpy, vi->screen), vi->visual, AllocNone);
    swa.background_pixmap = None;
    swa.border_pixel = 0;
    swa.event_mask = StructureNotifyMask;

    Window win = XCreateWindow(dpy, RootWindow(dpy, vi->screen), 0, 0, 512, 512, 0,
                               vi->depth, InputOutput, vi->visual,
                               CWColormap | CWBorderPixel | CWEventMask, &swa);
    XMapWindow(dpy, win);

    int ctx_attribs[] = {
        GLX_CONTEXT_MAJOR_VERSION_ARB, 3,
        GLX_CONTEXT_MINOR_VERSION_ARB, 3,
        GLX_CONTEXT_PROFILE_MASK_ARB, GLX_CONTEXT_CORE_PROFILE_BIT_ARB,
        None
    };
    glXCreateContextAttribsARBProc glXCreateContextAttribsARB =
        (glXCreateContextAttribsARBProc) glXGetProcAddressARB((const GLubyte*)"glXCreateContextAttribsARB");
    GLXContext ctx = glXCreateContextAttribsARB(dpy, chosen, NULL, True, ctx_attribs);
    glXMakeCurrent(dpy, win, ctx);

    glViewport(0, 0, 512, 512);
    glClearColor(0.1f, 0.1f, 0.1f, 1.0f);
    glClear(GL_COLOR_BUFFER_BIT);
    glXSwapBuffers(dpy, win);

    glXMakeCurrent(dpy, None, NULL);
    glXDestroyContext(dpy, ctx);
    XDestroyWindow(dpy, win);
    XFree(vi);
    XFree(fbc);
    XCloseDisplay(dpy);
    return 0;
}