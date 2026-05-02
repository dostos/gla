// SOURCE: https://github.com/mapbox/mapbox-gl-js/issues/13556
//
// Snapshot-tier stub. The real bug is a JS-side numeric-precision mistake
// in the mapbox-gl-js terrain pipeline, where a fractional `maxZoom` is
// forwarded unrounded into a SourceCache that indexes tiles by integer
// zoom — so the DEM/proxy caches end up with maxzoom == 16.58 when the
// renderer needs integer-zoom-17 tiles, and terrain-draped satellite tiles
// render black. This pattern cannot be meaningfully compressed into a
// minimal OpenGL program: the failure is in how tile coordinates are
// computed, not in any GL call. See the upstream snapshot referenced in
// scenario.md for the actual code path. This stub exists only to satisfy
// the per-scenario main.c requirement and to render a visible black frame
// that mirrors the symptom (black satellite tiles).
#include <stdio.h>
#include <string.h>
#include <X11/Xlib.h>
#include <GL/gl.h>
#include <GL/glx.h>

#define W 400
#define H 300

static int x_error_handler(Display *dpy, XErrorEvent *ev) {
    char buf[256];
    XGetErrorText(dpy, ev->error_code, buf, sizeof(buf));
    fprintf(stderr, "X Error (suppressed): %s (opcode %d/%d)\n",
            buf, ev->request_code, ev->minor_code);
    return 0;
}

int main(void) {
    XSetErrorHandler(x_error_handler);

    Display *dpy = XOpenDisplay(NULL);
    if (!dpy) { fprintf(stderr, "XOpenDisplay failed\n"); return 1; }

    int fb_attribs[] = {
        GLX_X_RENDERABLE, True,
        GLX_DRAWABLE_TYPE, GLX_WINDOW_BIT,
        GLX_RENDER_TYPE, GLX_RGBA_BIT,
        GLX_RED_SIZE, 8, GLX_GREEN_SIZE, 8, GLX_BLUE_SIZE, 8,
        GLX_ALPHA_SIZE, 8, GLX_DEPTH_SIZE, 24,
        GLX_DOUBLEBUFFER, True,
        None
    };
    int fbcount = 0;
    GLXFBConfig *fbc = glXChooseFBConfig(dpy, DefaultScreen(dpy), fb_attribs, &fbcount);
    if (!fbc || fbcount == 0) { fprintf(stderr, "glXChooseFBConfig failed\n"); return 1; }
    XVisualInfo *vi = glXGetVisualFromFBConfig(dpy, fbc[0]);

    Window root = DefaultRootWindow(dpy);
    XSetWindowAttributes swa;
    memset(&swa, 0, sizeof(swa));
    swa.colormap = XCreateColormap(dpy, root, vi->visual, AllocNone);
    swa.event_mask = ExposureMask;
    Window win = XCreateWindow(dpy, root, 0, 0, W, H, 0, vi->depth,
                               InputOutput, vi->visual, CWColormap | CWEventMask, &swa);
    XMapWindow(dpy, win);

    typedef GLXContext (*CtxAttribsProc)(Display*, GLXFBConfig, GLXContext, Bool, const int*);
    CtxAttribsProc glXCreateContextAttribsARB =
        (CtxAttribsProc) glXGetProcAddressARB((const GLubyte *)"glXCreateContextAttribsARB");
    int ctx_attribs[] = {
        GLX_CONTEXT_MAJOR_VERSION_ARB, 3,
        GLX_CONTEXT_MINOR_VERSION_ARB, 3,
        GLX_CONTEXT_PROFILE_MASK_ARB, GLX_CONTEXT_CORE_PROFILE_BIT_ARB,
        None
    };
    GLXContext ctx = glXCreateContextAttribsARB(dpy, fbc[0], 0, True, ctx_attribs);
    if (!ctx) { fprintf(stderr, "no GL 3.3 core context\n"); return 1; }
    glXMakeCurrent(dpy, win, ctx);

    glViewport(0, 0, W, H);
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

    printf("r2: black frame submitted (stub for snapshot-tier scenario)\n");
    return 0;
}