// SOURCE: https://github.com/mrdoob/three.js/issues/31776
//
// Minimal stub. The reported bug is specific to three.js WebGPURenderer +
// MeshStandardNodeMaterial + multiple InstancedMesh objects; it cannot be
// faithfully ported to desktop OpenGL because the failure lives in the
// NodeMaterial/WebGPU binding pipeline, not in generic instanced drawing.
// The scenario is tier: snapshot — the upstream three.js repository is the
// true eval payload. This file exists only so the build system has a target.

#include <GL/gl.h>
#include <GL/glx.h>
#include <X11/Xlib.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

static int visual_attribs[] = {
    GLX_RGBA, GLX_DOUBLEBUFFER,
    GLX_RED_SIZE, 8, GLX_GREEN_SIZE, 8, GLX_BLUE_SIZE, 8,
    GLX_DEPTH_SIZE, 24,
    None
};

int main(void) {
    Display *dpy = XOpenDisplay(NULL);
    if (!dpy) { fprintf(stderr, "no display\n"); return 1; }

    XVisualInfo *vi = glXChooseVisual(dpy, DefaultScreen(dpy), visual_attribs);
    if (!vi) { fprintf(stderr, "no visual\n"); return 1; }

    Window root = DefaultRootWindow(dpy);
    XSetWindowAttributes swa;
    swa.colormap = XCreateColormap(dpy, root, vi->visual, AllocNone);
    swa.event_mask = ExposureMask;
    Window win = XCreateWindow(dpy, root, 0, 0, 256, 256, 0, vi->depth,
                               InputOutput, vi->visual,
                               CWColormap | CWEventMask, &swa);
    XMapWindow(dpy, win);

    GLXContext ctx = glXCreateContext(dpy, vi, NULL, GL_TRUE);
    glXMakeCurrent(dpy, win, ctx);

    glClearColor(0.0f, 0.0f, 0.0f, 1.0f);
    glClear(GL_COLOR_BUFFER_BIT | GL_DEPTH_BUFFER_BIT);
    glXSwapBuffers(dpy, win);

    glXMakeCurrent(dpy, None, NULL);
    glXDestroyContext(dpy, ctx);
    XDestroyWindow(dpy, win);
    XCloseDisplay(dpy);
    return 0;
}