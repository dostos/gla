// SOURCE: https://github.com/mapbox/mapbox-gl-js/issues/13367
// Two textured quads ("animated" icon and "static" icon) drawn at the same
// screen-space position from a shared geometry source.
#include <GL/gl.h>
#include <GL/glx.h>
#include <X11/Xlib.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

static int xerr(Display *d, XErrorEvent *e) { (void)d; (void)e; return 0; }

static const char *VS =
    "#version 330 core\n"
    "layout(location=0) in vec2 aPos;\n"
    "layout(location=1) in vec2 aUV;\n"
    "out vec2 vUV;\n"
    "void main(){ vUV = aUV; gl_Position = vec4(aPos,0.0,1.0); }\n";

static const char *FS =
    "#version 330 core\n"
    "in vec2 vUV; out vec4 o;\n"
    "uniform vec3 uColor;\n"
    "void main(){\n"
    "  float d = length(vUV - vec2(0.5));\n"
    "  float a = smoothstep(0.5, 0.35, d);\n"
    "  o = vec4(uColor, a);\n"
    "}\n";

static GLuint compile(GLenum t, const char *s) {
    GLuint sh = glCreateShader(t);
    glShaderSource(sh, 1, &s, NULL);
    glCompileShader(sh);
    return sh;
}

static GLuint link_program(void) {
    GLuint vs = compile(GL_VERTEX_SHADER, VS);
    GLuint fs = compile(GL_FRAGMENT_SHADER, FS);
    GLuint p = glCreateProgram();
    glAttachShader(p, vs); glAttachShader(p, fs);
    glLinkProgram(p);
    glDeleteShader(vs); glDeleteShader(fs);
    return p;
}

typedef GLXContext (*glXCreateContextAttribsARBProc)(
    Display*, GLXFBConfig, GLXContext, Bool, const int*);

int main(void) {
    XSetErrorHandler(xerr);
    Display *dpy = XOpenDisplay(NULL);
    if (!dpy) { fprintf(stderr, "no display\n"); return 1; }

    int vis_attr[] = {GLX_RGBA, GLX_DEPTH_SIZE, 24, GLX_DOUBLEBUFFER, None};
    int fb_attr[] = {
        GLX_X_RENDERABLE, True, GLX_DRAWABLE_TYPE, GLX_WINDOW_BIT,
        GLX_RENDER_TYPE, GLX_RGBA_BIT, GLX_DEPTH_SIZE, 24,
        GLX_DOUBLEBUFFER, True, None};
    int nfb = 0;
    GLXFBConfig *fbc = glXChooseFBConfig(dpy, DefaultScreen(dpy), fb_attr, &nfb);
    if (!fbc || nfb == 0) { fprintf(stderr, "no fbconfig\n"); return 1; }
    XVisualInfo *vi = glXGetVisualFromFBConfig(dpy, fbc[0]);
    (void)vis_attr;

    Window root = RootWindow(dpy, vi->screen);
    XSetWindowAttributes swa = {0};
    swa.colormap = XCreateColormap(dpy, root, vi->visual, AllocNone);
    swa.event_mask = ExposureMask;
    Window win = XCreateWindow(dpy, root, 0, 0, 512, 512, 0, vi->depth,
                               InputOutput, vi->visual,
                               CWColormap | CWEventMask, &swa);
    XMapWindow(dpy, win);

    glXCreateContextAttribsARBProc create_ctx =
        (glXCreateContextAttribsARBProc)glXGetProcAddressARB(
            (const GLubyte *)"glXCreateContextAttribsARB");
    int ctx_attr[] = {
        GLX_CONTEXT_MAJOR_VERSION_ARB, 3,
        GLX_CONTEXT_MINOR_VERSION_ARB, 3,
        GLX_CONTEXT_PROFILE_MASK_ARB, GLX_CONTEXT_CORE_PROFILE_BIT_ARB,
        None};
    GLXContext ctx = create_ctx(dpy, fbc[0], 0, True, ctx_attr);
    glXMakeCurrent(dpy, win, ctx);

    GLuint prog = link_program();
    GLint locColor = glGetUniformLocation(prog, "uColor");

    // Quad A ("animated/pulsing" icon) at center.
    float vertsA[] = {
        -0.15f,-0.15f, 0.0f,0.0f,
         0.15f,-0.15f, 1.0f,0.0f,
         0.15f, 0.15f, 1.0f,1.0f,
        -0.15f, 0.15f, 0.0f,1.0f};
    // Quad B ("static" icon) sharing the same geometry source — same center.
    float vertsB[] = {
        -0.10f,-0.10f, 0.0f,0.0f,
         0.10f,-0.10f, 1.0f,0.0f,
         0.10f, 0.10f, 1.0f,1.0f,
        -0.10f, 0.10f, 0.0f,1.0f};
    unsigned idx[] = {0,1,2, 2,3,0};

    GLuint vaoA, vboA, vaoB, vboB, ebo;
    glGenVertexArrays(1, &vaoA); glGenBuffers(1, &vboA);
    glGenVertexArrays(1, &vaoB); glGenBuffers(1, &vboB);
    glGenBuffers(1, &ebo);

    glBindVertexArray(vaoA);
    glBindBuffer(GL_ARRAY_BUFFER, vboA);
    glBufferData(GL_ARRAY_BUFFER, sizeof(vertsA), vertsA, GL_STATIC_DRAW);
    glBindBuffer(GL_ELEMENT_ARRAY_BUFFER, ebo);
    glBufferData(GL_ELEMENT_ARRAY_BUFFER, sizeof(idx), idx, GL_STATIC_DRAW);
    glEnableVertexAttribArray(0);
    glVertexAttribPointer(0, 2, GL_FLOAT, GL_FALSE, 4*sizeof(float), (void*)0);
    glEnableVertexAttribArray(1);
    glVertexAttribPointer(1, 2, GL_FLOAT, GL_FALSE, 4*sizeof(float),
                          (void*)(2*sizeof(float)));

    glBindVertexArray(vaoB);
    glBindBuffer(GL_ARRAY_BUFFER, vboB);
    glBufferData(GL_ARRAY_BUFFER, sizeof(vertsB), vertsB, GL_STATIC_DRAW);
    glEnableVertexAttribArray(0);
    glVertexAttribPointer(0, 2, GL_FLOAT, GL_FALSE, 4*sizeof(float), (void*)0);
    glEnableVertexAttribArray(1);
    glVertexAttribPointer(1, 2, GL_FLOAT, GL_FALSE, 4*sizeof(float),
                          (void*)(2*sizeof(float)));

    glClearColor(0.05f, 0.05f, 0.08f, 1.0f);
    glEnable(GL_BLEND);
    glBlendFunc(GL_SRC_ALPHA, GL_ONE_MINUS_SRC_ALPHA);

    for (int frame = 0; frame < 2; ++frame) {
        glClear(GL_COLOR_BUFFER_BIT);
        glUseProgram(prog);

        glUniform3f(locColor, 0.9f, 0.2f, 0.2f);
        glBindVertexArray(vaoA);
        glDrawElements(GL_TRIANGLES, 6, GL_UNSIGNED_INT, 0);

        glUniform3f(locColor, 0.2f, 0.8f, 0.9f);
        glBindVertexArray(vaoB);
        glDrawElements(GL_TRIANGLES, 6, GL_UNSIGNED_INT, 0);

        glXSwapBuffers(dpy, win);
    }

    XFree(fbc); XFree(vi);
    glXMakeCurrent(dpy, None, NULL);
    glXDestroyContext(dpy, ctx);
    XDestroyWindow(dpy, win);
    XCloseDisplay(dpy);
    return 0;
}