// SOURCE: https://github.com/godotengine/godot/issues/97980
#define GL_GLEXT_PROTOTYPES
#include <GL/gl.h>
#include <GL/glext.h>
#include <GL/glx.h>
#include <X11/Xlib.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

static int xerr(Display *d, XErrorEvent *e) { (void)d; (void)e; return 0; }

typedef GLXContext (*PFNGLXCREATECONTEXTATTRIBSARBPROC)(Display *, GLXFBConfig, GLXContext, Bool, const int *);

static const char *VSRC =
    "#version 330 core\n"
    "layout(location=0) in vec3 aPos;\n"
    "uniform mat4 uMVP;\n"
    "void main(){ gl_Position = uMVP * vec4(aPos, 1.0); }\n";

static const char *FSRC =
    "#version 330 core\n"
    "uniform vec4 uColor;\n"
    "out vec4 FragColor;\n"
    "void main(){ FragColor = uColor; }\n";

static GLuint compile(GLenum type, const char *src) {
    GLuint sh = glCreateShader(type);
    glShaderSource(sh, 1, &src, NULL);
    glCompileShader(sh);
    GLint ok = 0;
    glGetShaderiv(sh, GL_COMPILE_STATUS, &ok);
    if (!ok) {
        char log[1024];
        glGetShaderInfoLog(sh, sizeof(log), NULL, log);
        fprintf(stderr, "shader: %s\n", log);
        exit(1);
    }
    return sh;
}

int main(void) {
    XSetErrorHandler(xerr);
    Display *dpy = XOpenDisplay(NULL);
    if (!dpy) { fprintf(stderr, "no display\n"); return 1; }

    int fbattr[] = {
        GLX_RENDER_TYPE, GLX_RGBA_BIT,
        GLX_DEPTH_SIZE, 24,
        GLX_DOUBLEBUFFER, True,
        GLX_RED_SIZE, 8, GLX_GREEN_SIZE, 8, GLX_BLUE_SIZE, 8,
        None
    };
    int nfb = 0;
    GLXFBConfig *fbc = glXChooseFBConfig(dpy, DefaultScreen(dpy), fbattr, &nfb);
    if (!fbc || nfb == 0) { fprintf(stderr, "no fbconfig\n"); return 1; }
    XVisualInfo *vi = glXGetVisualFromFBConfig(dpy, fbc[0]);

    XSetWindowAttributes swa = {0};
    swa.colormap = XCreateColormap(dpy, RootWindow(dpy, vi->screen), vi->visual, AllocNone);
    swa.event_mask = StructureNotifyMask;
    Window win = XCreateWindow(dpy, RootWindow(dpy, vi->screen),
        0, 0, 800, 600, 0, vi->depth, InputOutput, vi->visual,
        CWColormap | CWEventMask, &swa);
    XMapWindow(dpy, win);

    int ctxattr[] = {
        GLX_CONTEXT_MAJOR_VERSION_ARB, 3,
        GLX_CONTEXT_MINOR_VERSION_ARB, 3,
        GLX_CONTEXT_PROFILE_MASK_ARB, GLX_CONTEXT_CORE_PROFILE_BIT_ARB,
        None
    };
    PFNGLXCREATECONTEXTATTRIBSARBPROC glXCreateContextAttribsARB =
        (PFNGLXCREATECONTEXTATTRIBSARBPROC)glXGetProcAddressARB(
            (const GLubyte *)"glXCreateContextAttribsARB");
    GLXContext ctx = glXCreateContextAttribsARB(dpy, fbc[0], 0, True, ctxattr);
    if (!ctx) { fprintf(stderr, "no context\n"); return 1; }
    glXMakeCurrent(dpy, win, ctx);

    GLuint vs = compile(GL_VERTEX_SHADER, VSRC);
    GLuint fs = compile(GL_FRAGMENT_SHADER, FSRC);
    GLuint prog = glCreateProgram();
    glAttachShader(prog, vs);
    glAttachShader(prog, fs);
    glLinkProgram(prog);
    glDeleteShader(vs);
    glDeleteShader(fs);

    // Four coplanar corners of a quad tilted around Y so depth varies
    // across the face. Plane: z = x / 3.
    //   TL = (-0.6,  0.6, -0.2)
    //   TR = ( 0.6,  0.6,  0.2)
    //   BR = ( 0.6, -0.6,  0.2)
    //   BL = (-0.6, -0.6, -0.2)
    //
    // Quad A (the "CSG mesh"): split along TL-BR diagonal.
    // Quad B (the "selection gizmo"): split along BL-TR diagonal.
    // Same 4 corners, same plane, no depth bias — exactly the Godot
    // coplanar-faces situation.
    float qA[] = {
        -0.6f,  0.6f, -0.2f,
        -0.6f, -0.6f, -0.2f,
         0.6f, -0.6f,  0.2f,
        -0.6f,  0.6f, -0.2f,
         0.6f, -0.6f,  0.2f,
         0.6f,  0.6f,  0.2f,
    };
    float qB[] = {
        -0.6f,  0.6f, -0.2f,
        -0.6f, -0.6f, -0.2f,
         0.6f,  0.6f,  0.2f,
         0.6f,  0.6f,  0.2f,
        -0.6f, -0.6f, -0.2f,
         0.6f, -0.6f,  0.2f,
    };

    GLuint vao[2], vbo[2];
    glGenVertexArrays(2, vao);
    glGenBuffers(2, vbo);
    glBindVertexArray(vao[0]);
    glBindBuffer(GL_ARRAY_BUFFER, vbo[0]);
    glBufferData(GL_ARRAY_BUFFER, sizeof(qA), qA, GL_STATIC_DRAW);
    glVertexAttribPointer(0, 3, GL_FLOAT, GL_FALSE, 3 * sizeof(float), 0);
    glEnableVertexAttribArray(0);
    glBindVertexArray(vao[1]);
    glBindBuffer(GL_ARRAY_BUFFER, vbo[1]);
    glBufferData(GL_ARRAY_BUFFER, sizeof(qB), qB, GL_STATIC_DRAW);
    glVertexAttribPointer(0, 3, GL_FLOAT, GL_FALSE, 3 * sizeof(float), 0);
    glEnableVertexAttribArray(0);

    float mvp[16] = { 1,0,0,0,  0,1,0,0,  0,0,1,0,  0,0,0,1 };

    glViewport(0, 0, 800, 600);
    glClearColor(0.0f, 0.0f, 0.0f, 1.0f);
    glClearDepth(1.0f);
    glEnable(GL_DEPTH_TEST);
    glDepthFunc(GL_LESS);
    glClear(GL_COLOR_BUFFER_BIT | GL_DEPTH_BUFFER_BIT);

    glUseProgram(prog);
    GLint locMVP = glGetUniformLocation(prog, "uMVP");
    GLint locColor = glGetUniformLocation(prog, "uColor");
    glUniformMatrix4fv(locMVP, 1, GL_FALSE, mvp);

    // Draw A: the "CSG mesh" face, red.
    glUniform4f(locColor, 1.0f, 0.0f, 0.0f, 1.0f);
    glBindVertexArray(vao[0]);
    glDrawArrays(GL_TRIANGLES, 0, 6);

    // Draw B: the "selection gizmo" face, green. Same 4 corners, no
    // depth offset. Under GL_LESS this produces coplanar Z-fighting
    // rather than cleanly overpainting draw A.
    glUniform4f(locColor, 0.0f, 1.0f, 0.0f, 1.0f);
    glBindVertexArray(vao[1]);
    glDrawArrays(GL_TRIANGLES, 0, 6);

    glXSwapBuffers(dpy, win);
    glFinish();

    glXMakeCurrent(dpy, 0, 0);
    glXDestroyContext(dpy, ctx);
    XDestroyWindow(dpy, win);
    XCloseDisplay(dpy);
    return 0;
}