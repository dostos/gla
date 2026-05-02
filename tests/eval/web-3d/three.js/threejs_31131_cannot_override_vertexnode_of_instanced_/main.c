// SOURCE: https://github.com/mrdoob/three.js/issues/31131
//
// This scenario is tier=snapshot: the bug lives in three.js's TSL node
// pipeline and the WebGPURenderer's instancing/morph code path, which
// cannot be faithfully ported to minimal OpenGL 3.3. This file exists
// only as a placeholder so the eval harness has an executable to launch.
// The real payload is the upstream snapshot referenced in scenario.md.

#include <GL/gl.h>
#include <GL/glx.h>
#include <X11/Xlib.h>
#include <stdio.h>
#include <string.h>

int main(void) {
    Display *dpy = XOpenDisplay(NULL);
    if (!dpy) { fprintf(stderr, "no display\n"); return 0; }

    int attribs[] = {
        GLX_RGBA, GLX_DEPTH_SIZE, 24, GLX_DOUBLEBUFFER, None
    };
    XVisualInfo *vi = glXChooseVisual(dpy, 0, attribs);
    if (!vi) { XCloseDisplay(dpy); return 0; }

    Window root = DefaultRootWindow(dpy);
    XSetWindowAttributes swa;
    memset(&swa, 0, sizeof(swa));
    swa.colormap = XCreateColormap(dpy, root, vi->visual, AllocNone);
    Window win = XCreateWindow(dpy, root, 0, 0, 256, 256, 0,
                               vi->depth, InputOutput, vi->visual,
                               CWColormap, &swa);
    XMapWindow(dpy, win);

    GLXContext ctx = glXCreateContext(dpy, vi, NULL, GL_TRUE);
    glXMakeCurrent(dpy, win, ctx);

    glClearColor(0.0f, 0.0f, 0.0f, 1.0f);
    glClear(GL_COLOR_BUFFER_BIT);
    glXSwapBuffers(dpy, win);

    printf("placeholder frame emitted; see upstream snapshot\n");

    glXMakeCurrent(dpy, None, NULL);
    glXDestroyContext(dpy, ctx);
    XDestroyWindow(dpy, win);
    XCloseDisplay(dpy);
    return 0;
}