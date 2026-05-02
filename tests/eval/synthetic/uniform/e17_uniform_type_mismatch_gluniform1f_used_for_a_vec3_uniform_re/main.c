// SOURCE: synthetic (no upstream)
// glUniform1f used to set a vec3 tint uniform — GL silently ignores the
// type-mismatched call, leaving the uniform at its default (0,0,0), so the
// tinted quad renders black instead of the intended warm orange.
//
// Minimal OpenGL 2.1 / 3.3 compatible program. Uses GLX for context.
// Link: -lGL -lX11 -lm only. Compiles with:
//   gcc -Wall -std=gnu11 main.c -lGL -lX11 -lm
// Runs under Xvfb; exits cleanly after rendering 3-5 frames.
// The bug manifests on the first rendered frame.
#include <X11/Xlib.h>
#include <GL/gl.h>
#include <GL/glx.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <math.h>

typedef GLuint (*PFNGLCREATESHADERPROC)(GLenum);
typedef void   (*PFNGLSHADERSOURCEPROC)(GLuint, GLsizei, const char* const*, const GLint*);
typedef void   (*PFNGLCOMPILESHADERPROC)(GLuint);
typedef void   (*PFNGLGETSHADERIVPROC)(GLuint, GLenum, GLint*);
typedef void   (*PFNGLGETSHADERINFOLOGPROC)(GLuint, GLsizei, GLsizei*, char*);
typedef GLuint (*PFNGLCREATEPROGRAMPROC)(void);
typedef void   (*PFNGLATTACHSHADERPROC)(GLuint, GLuint);
typedef void   (*PFNGLLINKPROGRAMPROC)(GLuint);
typedef void   (*PFNGLGETPROGRAMIVPROC)(GLuint, GLenum, GLint*);
typedef void   (*PFNGLUSEPROGRAMPROC)(GLuint);
typedef GLint  (*PFNGLGETUNIFORMLOCATIONPROC)(GLuint, const char*);
typedef void   (*PFNGLUNIFORM1FPROC)(GLint, GLfloat);
typedef void   (*PFNGLUNIFORM3FPROC)(GLint, GLfloat, GLfloat, GLfloat);
typedef void   (*PFNGLGENBUFFERSPROC)(GLsizei, GLuint*);
typedef void   (*PFNGLBINDBUFFERPROC)(GLenum, GLuint);
typedef void   (*PFNGLBUFFERDATAPROC)(GLenum, GLsizeiptr, const void*, GLenum);
typedef void   (*PFNGLENABLEVERTEXATTRIBARRAYPROC)(GLuint);
typedef void   (*PFNGLVERTEXATTRIBPOINTERPROC)(GLuint, GLint, GLenum, GLboolean, GLsizei, const void*);
typedef void   (*PFNGLBINDATTRIBLOCATIONPROC)(GLuint, GLuint, const char*);

static PFNGLCREATESHADERPROC        pglCreateShader;
static PFNGLSHADERSOURCEPROC        pglShaderSource;
static PFNGLCOMPILESHADERPROC       pglCompileShader;
static PFNGLGETSHADERIVPROC         pglGetShaderiv;
static PFNGLGETSHADERINFOLOGPROC    pglGetShaderInfoLog;
static PFNGLCREATEPROGRAMPROC       pglCreateProgram;
static PFNGLATTACHSHADERPROC        pglAttachShader;
static PFNGLLINKPROGRAMPROC         pglLinkProgram;
static PFNGLGETPROGRAMIVPROC        pglGetProgramiv;
static PFNGLUSEPROGRAMPROC          pglUseProgram;
static PFNGLGETUNIFORMLOCATIONPROC  pglGetUniformLocation;
static PFNGLUNIFORM1FPROC           pglUniform1f;
static PFNGLUNIFORM3FPROC           pglUniform3f;
static PFNGLGENBUFFERSPROC          pglGenBuffers;
static PFNGLBINDBUFFERPROC          pglBindBuffer;
static PFNGLBUFFERDATAPROC          pglBufferData;
static PFNGLENABLEVERTEXATTRIBARRAYPROC pglEnableVertexAttribArray;
static PFNGLVERTEXATTRIBPOINTERPROC pglVertexAttribPointer;
static PFNGLBINDATTRIBLOCATIONPROC  pglBindAttribLocation;

static void* gl_get(const char* n) { return (void*)glXGetProcAddress((const GLubyte*)n); }

static const char* VS =
    "#version 120\n"
    "attribute vec2 a_pos;\n"
    "void main(){ gl_Position = vec4(a_pos, 0.0, 1.0); }\n";

static const char* FS =
    "#version 120\n"
    "uniform vec3 u_tint;\n"
    "void main(){ gl_FragColor = vec4(u_tint, 1.0); }\n";

static GLuint compile(GLenum type, const char* src) {
    GLuint s = pglCreateShader(type);
    pglShaderSource(s, 1, &src, NULL);
    pglCompileShader(s);
    GLint ok = 0; pglGetShaderiv(s, GL_COMPILE_STATUS, &ok);
    if (!ok) { char log[1024]; pglGetShaderInfoLog(s, 1024, NULL, log); fprintf(stderr, "shader: %s\n", log); exit(1); }
    return s;
}

int main(void) {
    Display* dpy = XOpenDisplay(NULL);
    if (!dpy) { fprintf(stderr, "XOpenDisplay failed\n"); return 1; }
    int attribs[] = { GLX_RGBA, GLX_DOUBLEBUFFER, GLX_DEPTH_SIZE, 24, None };
    XVisualInfo* vi = glXChooseVisual(dpy, DefaultScreen(dpy), attribs);
    if (!vi) { fprintf(stderr, "no visual\n"); return 1; }
    Colormap cmap = XCreateColormap(dpy, RootWindow(dpy, vi->screen), vi->visual, AllocNone);
    XSetWindowAttributes swa = {0};
    swa.colormap = cmap;
    swa.event_mask = StructureNotifyMask;
    Window win = XCreateWindow(dpy, RootWindow(dpy, vi->screen), 0, 0, 400, 300, 0,
                               vi->depth, InputOutput, vi->visual, CWColormap | CWEventMask, &swa);
    XMapWindow(dpy, win);
    GLXContext ctx = glXCreateContext(dpy, vi, NULL, GL_TRUE);
    glXMakeCurrent(dpy, win, ctx);

    pglCreateShader = gl_get("glCreateShader");
    pglShaderSource = gl_get("glShaderSource");
    pglCompileShader = gl_get("glCompileShader");
    pglGetShaderiv = gl_get("glGetShaderiv");
    pglGetShaderInfoLog = gl_get("glGetShaderInfoLog");
    pglCreateProgram = gl_get("glCreateProgram");
    pglAttachShader = gl_get("glAttachShader");
    pglLinkProgram = gl_get("glLinkProgram");
    pglGetProgramiv = gl_get("glGetProgramiv");
    pglUseProgram = gl_get("glUseProgram");
    pglGetUniformLocation = gl_get("glGetUniformLocation");
    pglUniform1f = gl_get("glUniform1f");
    pglUniform3f = gl_get("glUniform3f");
    pglGenBuffers = gl_get("glGenBuffers");
    pglBindBuffer = gl_get("glBindBuffer");
    pglBufferData = gl_get("glBufferData");
    pglEnableVertexAttribArray = gl_get("glEnableVertexAttribArray");
    pglVertexAttribPointer = gl_get("glVertexAttribPointer");
    pglBindAttribLocation = gl_get("glBindAttribLocation");

    GLuint vs = compile(GL_VERTEX_SHADER, VS);
    GLuint fs = compile(GL_FRAGMENT_SHADER, FS);
    GLuint prog = pglCreateProgram();
    pglAttachShader(prog, vs);
    pglAttachShader(prog, fs);
    pglBindAttribLocation(prog, 0, "a_pos");
    pglLinkProgram(prog);
    GLint linked = 0; pglGetProgramiv(prog, GL_LINK_STATUS, &linked);
    if (!linked) { fprintf(stderr, "link failed\n"); return 1; }

    float verts[] = { -0.8f, -0.8f,  0.8f, -0.8f,  0.8f, 0.8f,
                      -0.8f, -0.8f,  0.8f,  0.8f, -0.8f, 0.8f };
    GLuint vbo; pglGenBuffers(1, &vbo);
    pglBindBuffer(GL_ARRAY_BUFFER, vbo);
    pglBufferData(GL_ARRAY_BUFFER, sizeof(verts), verts, GL_STATIC_DRAW);

    pglUseProgram(prog);
    GLint loc_tint = pglGetUniformLocation(prog, "u_tint");

    // Intent: set warm orange tint (1.0, 0.55, 0.10) on the fullscreen quad.
    // The author refactored from a scalar "intensity" uniform to a vec3 tint
    // but forgot to update the setter — still calls glUniform1f here.
    // GL sees a type mismatch against vec3 u_tint and silently ignores the
    // call; the uniform remains at its default zero vec3.
    float tint_r = 1.0f;
    pglUniform1f(loc_tint, tint_r);

    pglEnableVertexAttribArray(0);
    pglVertexAttribPointer(0, 2, GL_FLOAT, GL_FALSE, 0, (void*)0);

    for (int i = 0; i < 4; i++) {
        glClearColor(0.2f, 0.2f, 0.2f, 1.0f);
        glClear(GL_COLOR_BUFFER_BIT | GL_DEPTH_BUFFER_BIT);
        glDrawArrays(GL_TRIANGLES, 0, 6);
        glXSwapBuffers(dpy, win);
    }

    unsigned char px[4] = {0,0,0,0};
    glReadPixels(200, 150, 1, 1, GL_RGBA, GL_UNSIGNED_BYTE, px);
    printf("center RGBA = %u %u %u %u\n", px[0], px[1], px[2], px[3]);

    glXMakeCurrent(dpy, None, NULL);
    glXDestroyContext(dpy, ctx);
    XDestroyWindow(dpy, win);
    XFreeColormap(dpy, cmap);
    XCloseDisplay(dpy);
    (void)pglUniform3f;
    return 0;
}