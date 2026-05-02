// SOURCE: https://github.com/mrdoob/three.js/issues/22017
//
// Repro: on a multisampled framebuffer, writing gl_FragDepth in the
// fragment shader forces per-pixel (not per-sample) fragment execution.
// All samples within a pixel receive the same color and depth, so MSAA
// coverage-based antialiasing stops smoothing geometry intersections.
// Two triangles that intersect along a horizontal line produce a
// stair-stepped boundary instead of a blended one.
//
// Without the gl_FragDepth write (or with MSAA disabled), the bug
// vanishes: delete the "gl_FragDepth = ..." line to compare.

#define GL_GLEXT_PROTOTYPES
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <X11/Xlib.h>
#include <GL/gl.h>
#include <GL/glext.h>
#include <GL/glx.h>

typedef GLXContext (*glXCreateContextAttribsARBProc)(Display*, GLXFBConfig, GLXContext, Bool, const int*);
#define GLX_CONTEXT_MAJOR_VERSION_ARB     0x2091
#define GLX_CONTEXT_MINOR_VERSION_ARB     0x2092
#define GLX_CONTEXT_PROFILE_MASK_ARB      0x9126
#define GLX_CONTEXT_CORE_PROFILE_BIT_ARB  0x00000001

static const char* VS =
    "#version 330 core\n"
    "layout(location=0) in vec3 aPos;\n"
    "layout(location=1) in vec3 aCol;\n"
    "out vec3 vCol;\n"
    "void main(){ vCol = aCol; gl_Position = vec4(aPos, 1.0); }\n";

// Stand-in for three.js's logarithmic depth buffer fragment shader chunk,
// which assigns to gl_FragDepth. The specific expression does not matter;
// merely writing gl_FragDepth is what opts the fragment stage out of
// per-sample execution under MSAA.
static const char* FS =
    "#version 330 core\n"
    "in vec3 vCol;\n"
    "out vec4 outColor;\n"
    "void main(){\n"
    "    gl_FragDepth = gl_FragCoord.z;\n"
    "    outColor = vec4(vCol, 1.0);\n"
    "}\n";

static GLuint compile(GLenum type, const char* src) {
    GLuint sh = glCreateShader(type);
    glShaderSource(sh, 1, &src, NULL);
    glCompileShader(sh);
    GLint ok = 0;
    glGetShaderiv(sh, GL_COMPILE_STATUS, &ok);
    if (!ok) {
        char log[1024];
        glGetShaderInfoLog(sh, sizeof(log), NULL, log);
        fprintf(stderr, "shader compile failed: %s\n", log);
        exit(1);
    }
    return sh;
}

int main(void) {
    Display* dpy = XOpenDisplay(NULL);
    if (!dpy) { fprintf(stderr, "XOpenDisplay failed\n"); return 1; }

    int visAttrs[] = {
        GLX_X_RENDERABLE,    True,
        GLX_DRAWABLE_TYPE,   GLX_WINDOW_BIT,
        GLX_RENDER_TYPE,     GLX_RGBA_BIT,
        GLX_RED_SIZE,        8,
        GLX_GREEN_SIZE,      8,
        GLX_BLUE_SIZE,       8,
        GLX_ALPHA_SIZE,      8,
        GLX_DEPTH_SIZE,      24,
        GLX_DOUBLEBUFFER,    True,
        GLX_SAMPLE_BUFFERS,  1,
        GLX_SAMPLES,         4,
        None
    };
    int fbcount = 0;
    GLXFBConfig* fbc = glXChooseFBConfig(dpy, DefaultScreen(dpy), visAttrs, &fbcount);
    if (!fbc || fbcount == 0) { fprintf(stderr, "no multisample FBConfig\n"); return 1; }

    XVisualInfo* vi = glXGetVisualFromFBConfig(dpy, fbc[0]);
    XSetWindowAttributes swa;
    memset(&swa, 0, sizeof(swa));
    swa.colormap = XCreateColormap(dpy, RootWindow(dpy, vi->screen), vi->visual, AllocNone);
    swa.event_mask = StructureNotifyMask;
    Window win = XCreateWindow(dpy, RootWindow(dpy, vi->screen), 0, 0, 256, 256, 0,
                               vi->depth, InputOutput, vi->visual,
                               CWColormap | CWEventMask, &swa);
    XMapWindow(dpy, win);
    XSync(dpy, False);

    glXCreateContextAttribsARBProc glXCreateContextAttribsARB =
        (glXCreateContextAttribsARBProc)
        glXGetProcAddressARB((const GLubyte*)"glXCreateContextAttribsARB");
    int ctxAttrs[] = {
        GLX_CONTEXT_MAJOR_VERSION_ARB, 3,
        GLX_CONTEXT_MINOR_VERSION_ARB, 3,
        GLX_CONTEXT_PROFILE_MASK_ARB,  GLX_CONTEXT_CORE_PROFILE_BIT_ARB,
        None
    };
    GLXContext ctx = glXCreateContextAttribsARB(dpy, fbc[0], 0, True, ctxAttrs);
    glXMakeCurrent(dpy, win, ctx);

    glEnable(GL_MULTISAMPLE);
    glEnable(GL_DEPTH_TEST);

    GLuint vs = compile(GL_VERTEX_SHADER,   VS);
    GLuint fs = compile(GL_FRAGMENT_SHADER, FS);
    GLuint prog = glCreateProgram();
    glAttachShader(prog, vs);
    glAttachShader(prog, fs);
    glLinkProgram(prog);
    glUseProgram(prog);

    // Two triangles crossing at y=0. Tri A: bottom edge far (z=-0.5),
    // apex near (z=+0.5). Tri B: the vertical mirror. Their depths are
    // equal exactly at y=0 across all x, producing a horizontal depth
    // intersection. MSAA should blend colors in a ~1px transition band;
    // with gl_FragDepth written, the band collapses to a hard step.
    float verts[] = {
        // pos                    // color (blue)
        -0.8f, -0.8f, -0.5f,      0.1f, 0.2f, 0.9f,
         0.8f, -0.8f, -0.5f,      0.1f, 0.2f, 0.9f,
         0.0f,  0.8f,  0.5f,      0.1f, 0.2f, 0.9f,

        // pos                    // color (yellow)
        -0.8f,  0.8f, -0.5f,      0.9f, 0.8f, 0.1f,
         0.8f,  0.8f, -0.5f,      0.9f, 0.8f, 0.1f,
         0.0f, -0.8f,  0.5f,      0.9f, 0.8f, 0.1f,
    };
    GLuint vao, vbo;
    glGenVertexArrays(1, &vao);
    glBindVertexArray(vao);
    glGenBuffers(1, &vbo);
    glBindBuffer(GL_ARRAY_BUFFER, vbo);
    glBufferData(GL_ARRAY_BUFFER, sizeof(verts), verts, GL_STATIC_DRAW);
    glVertexAttribPointer(0, 3, GL_FLOAT, GL_FALSE, 6 * sizeof(float), (void*)0);
    glEnableVertexAttribArray(0);
    glVertexAttribPointer(1, 3, GL_FLOAT, GL_FALSE, 6 * sizeof(float),
                          (void*)(3 * sizeof(float)));
    glEnableVertexAttribArray(1);

    glViewport(0, 0, 256, 256);
    glClearColor(0.1f, 0.1f, 0.1f, 1.0f);
    glClear(GL_COLOR_BUFFER_BIT | GL_DEPTH_BUFFER_BIT);
    glDrawArrays(GL_TRIANGLES, 0, 6);

    glXSwapBuffers(dpy, win);
    glFinish();

    glXMakeCurrent(dpy, 0, 0);
    glXDestroyContext(dpy, ctx);
    XDestroyWindow(dpy, win);
    XCloseDisplay(dpy);
    return 0;
}