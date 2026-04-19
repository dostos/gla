// SOURCE: https://github.com/godotengine/godot/issues/115441
// Snapshot-tier scenario. The bug is inside Godot's shader compiler, which
// rewrites the `RADIANCE` uniform in sky shaders. After PR #107902 the backing
// storage changed from samplerCube to a 2D octahedral map, but no compatibility
// shim was added to translate `texture(RADIANCE, EYEDIR)` from a direction
// lookup into an octahedral UV lookup. PR #114773 added that shim.
//
// A minimal GL reproduction can't capture the shader-rewrite logic, so this
// program is a stub. The real eval payload is the upstream Godot codebase at
// the snapshot SHA; see scenario.md for the relevant files.

#include <GL/gl.h>
#include <GL/glx.h>
#include <X11/Xlib.h>
#include <stdio.h>

int main(void) {
    Display *dpy = XOpenDisplay(NULL);
    if (!dpy) { fprintf(stderr, "No display\n"); return 1; }
    int attrs[] = { GLX_RGBA, GLX_DEPTH_SIZE, 24, GLX_DOUBLEBUFFER, None };
    XVisualInfo *vi = glXChooseVisual(dpy, 0, attrs);
    if (!vi) { fprintf(stderr, "No visual\n"); return 1; }
    Window root = DefaultRootWindow(dpy);
    XSetWindowAttributes swa = {0};
    swa.colormap = XCreateColormap(dpy, root, vi->visual, AllocNone);
    Window win = XCreateWindow(dpy, root, 0, 0, 64, 64, 0, vi->depth,
                               InputOutput, vi->visual, CWColormap, &swa);
    GLXContext ctx = glXCreateContext(dpy, vi, NULL, GL_TRUE);
    glXMakeCurrent(dpy, win, ctx);
    glClearColor(0.f, 0.f, 0.f, 1.f);
    glClear(GL_COLOR_BUFFER_BIT);
    glXSwapBuffers(dpy, win);
    glXMakeCurrent(dpy, None, NULL);
    glXDestroyContext(dpy, ctx);
    XDestroyWindow(dpy, win);
    XCloseDisplay(dpy);
    return 0;
}