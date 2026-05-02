// SOURCE: synthetic (no upstream)
// Depth write disabled (GL_FALSE) leaked from a prior transparent pass;
// the second opaque draw incorrectly overwrites the first because the
// depth buffer was never updated.
//
// Minimal OpenGL 2.1 / 3.3 compatible program. Uses GLX for context.
// Link: -lGL -lX11 -lm only. Compiles with:
//   gcc -Wall -std=gnu11 main.c -lGL -lX11 -lm
// Runs under Xvfb; exits cleanly after rendering 4 frames.
// The bug manifests on the first rendered frame.
#include <X11/Xlib.h>
#include <GL/gl.h>
#include <GL/glx.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <math.h>

typedef GLuint (*PFNGLCREATESHADERPROC)(GLenum);
typedef void   (*PFNGLSHADERSOURCEPROC)(GLuint, GLsizei, const char * const *, const GLint *);
typedef void   (*PFNGLCOMPILESHADERPROC)(GLuint);
typedef void   (*PFNGLGETSHADERIVPROC)(GLuint, GLenum, GLint *);
typedef void   (*PFNGLGETSHADERINFOLOGPROC)(GLuint, GLsizei, GLsizei *, char *);
typedef GLuint (*PFNGLCREATEPROGRAMPROC)(void);
typedef void   (*PFNGLATTACHSHADERPROC)(GLuint, GLuint);
typedef void   (*PFNGLLINKPROGRAMPROC)(GLuint);
typedef void   (*PFNGLGETPROGRAMIVPROC)(GLuint, GLenum, GLint *);
typedef void   (*PFNGLUSEPROGRAMPROC)(GLuint);
typedef GLint  (*PFNGLGETUNIFORMLOCATIONPROC)(GLuint, const char *);
typedef void   (*PFNGLUNIFORM4FPROC)(GLint, GLfloat, GLfloat, GLfloat, GLfloat);
typedef void   (*PFNGLGENBUFFERSPROC)(GLsizei, GLuint *);
typedef void   (*PFNGLBINDBUFFERPROC)(GLenum, GLuint);
typedef void   (*PFNGLBUFFERDATAPROC)(GLenum, GLsizeiptr, const void *, GLenum);
typedef void   (*PFNGLENABLEVERTEXATTRIBARRAYPROC)(GLuint);
typedef void   (*PFNGLVERTEXATTRIBPOINTERPROC)(GLuint, GLint, GLenum, GLboolean, GLsizei, const void *);
typedef GLint  (*PFNGLGETATTRIBLOCATIONPROC)(GLuint, const char *);

#ifndef GL_ARRAY_BUFFER
#define GL_ARRAY_BUFFER    0x8892
#endif
#ifndef GL_STATIC_DRAW
#define GL_STATIC_DRAW     0x88E4
#endif
#ifndef GL_FRAGMENT_SHADER
#define GL_FRAGMENT_SHADER 0x8B30
#endif
#ifndef GL_VERTEX_SHADER
#define GL_VERTEX_SHADER   0x8B31
#endif
#ifndef GL_COMPILE_STATUS
#define GL_COMPILE_STATUS  0x8B81
#endif
#ifndef GL_LINK_STATUS
#define GL_LINK_STATUS     0x8B82
#endif

static PFNGLCREATESHADERPROC            p_CreateShader;
static PFNGLSHADERSOURCEPROC            p_ShaderSource;
static PFNGLCOMPILESHADERPROC           p_CompileShader;
static PFNGLGETSHADERIVPROC             p_GetShaderiv;
static PFNGLGETSHADERINFOLOGPROC        p_GetShaderInfoLog;
static PFNGLCREATEPROGRAMPROC           p_CreateProgram;
static PFNGLATTACHSHADERPROC            p_AttachShader;
static PFNGLLINKPROGRAMPROC             p_LinkProgram;
static PFNGLGETPROGRAMIVPROC            p_GetProgramiv;
static PFNGLUSEPROGRAMPROC              p_UseProgram;
static PFNGLGETUNIFORMLOCATIONPROC      p_GetUniformLocation;
static PFNGLUNIFORM4FPROC               p_Uniform4f;
static PFNGLGENBUFFERSPROC              p_GenBuffers;
static PFNGLBINDBUFFERPROC              p_BindBuffer;
static PFNGLBUFFERDATAPROC              p_BufferData;
static PFNGLENABLEVERTEXATTRIBARRAYPROC p_EnableVertexAttribArray;
static PFNGLVERTEXATTRIBPOINTERPROC     p_VertexAttribPointer;
static PFNGLGETATTRIBLOCATIONPROC       p_GetAttribLocation;

static void *resolve(const char *n) {
    return (void *)glXGetProcAddressARB((const GLubyte *)n);
}

static void load_gl(void) {
    p_CreateShader            = resolve("glCreateShader");
    p_ShaderSource            = resolve("glShaderSource");
    p_CompileShader           = resolve("glCompileShader");
    p_GetShaderiv             = resolve("glGetShaderiv");
    p_GetShaderInfoLog        = resolve("glGetShaderInfoLog");
    p_CreateProgram           = resolve("glCreateProgram");
    p_AttachShader            = resolve("glAttachShader");
    p_LinkProgram             = resolve("glLinkProgram");
    p_GetProgramiv            = resolve("glGetProgramiv");
    p_UseProgram              = resolve("glUseProgram");
    p_GetUniformLocation      = resolve("glGetUniformLocation");
    p_Uniform4f               = resolve("glUniform4f");
    p_GenBuffers              = resolve("glGenBuffers");
    p_BindBuffer              = resolve("glBindBuffer");
    p_BufferData              = resolve("glBufferData");
    p_EnableVertexAttribArray = resolve("glEnableVertexAttribArray");
    p_VertexAttribPointer     = resolve("glVertexAttribPointer");
    p_GetAttribLocation       = resolve("glGetAttribLocation");
}

static const char *VS =
    "#version 120\n"
    "attribute vec3 aPos;\n"
    "void main(){ gl_Position = vec4(aPos, 1.0); }\n";

static const char *FS =
    "#version 120\n"
    "uniform vec4 uColor;\n"
    "void main(){ gl_FragColor = uColor; }\n";

static GLuint compile(GLenum type, const char *src) {
    GLuint s = p_CreateShader(type);
    p_ShaderSource(s, 1, &src, NULL);
    p_CompileShader(s);
    GLint ok = 0;
    p_GetShaderiv(s, GL_COMPILE_STATUS, &ok);
    if (!ok) {
        char log[1024];
        p_GetShaderInfoLog(s, sizeof log, NULL, log);
        fprintf(stderr, "shader: %s\n", log);
        exit(1);
    }
    return s;
}

static void draw_quad(GLuint vbo, GLint uColor, float z,
                      float r, float g, float b, float a) {
    float v[] = {
        -1.f, -1.f, z,
         1.f, -1.f, z,
        -1.f,  1.f, z,
         1.f,  1.f, z,
    };
    p_BindBuffer(GL_ARRAY_BUFFER, vbo);
    p_BufferData(GL_ARRAY_BUFFER, sizeof v, v, GL_STATIC_DRAW);
    p_Uniform4f(uColor, r, g, b, a);
    glDrawArrays(GL_TRIANGLE_STRIP, 0, 4);
}

int main(void) {
    Display *dpy = XOpenDisplay(NULL);
    if (!dpy) { fprintf(stderr, "no display\n"); return 1; }
    int screen = DefaultScreen(dpy);
    int attr[] = { GLX_RGBA, GLX_DEPTH_SIZE, 24, GLX_DOUBLEBUFFER, None };
    XVisualInfo *vi = glXChooseVisual(dpy, screen, attr);
    if (!vi) { fprintf(stderr, "no visual\n"); return 1; }
    Window root = RootWindow(dpy, screen);
    XSetWindowAttributes swa;
    swa.colormap = XCreateColormap(dpy, root, vi->visual, AllocNone);
    swa.event_mask = StructureNotifyMask;
    Window win = XCreateWindow(dpy, root, 0, 0, 400, 300, 0,
        vi->depth, InputOutput, vi->visual,
        CWColormap | CWEventMask, &swa);
    XMapWindow(dpy, win);
    GLXContext ctx = glXCreateContext(dpy, vi, NULL, GL_TRUE);
    glXMakeCurrent(dpy, win, ctx);
    load_gl();

    GLuint vs = compile(GL_VERTEX_SHADER, VS);
    GLuint fs = compile(GL_FRAGMENT_SHADER, FS);
    GLuint prog = p_CreateProgram();
    p_AttachShader(prog, vs);
    p_AttachShader(prog, fs);
    p_LinkProgram(prog);
    GLint linked = 0;
    p_GetProgramiv(prog, GL_LINK_STATUS, &linked);
    if (!linked) { fprintf(stderr, "link failed\n"); return 1; }
    p_UseProgram(prog);
    GLint uColor = p_GetUniformLocation(prog, "uColor");
    GLint aPos   = p_GetAttribLocation(prog, "aPos");

    GLuint vbo;
    p_GenBuffers(1, &vbo);
    p_BindBuffer(GL_ARRAY_BUFFER, vbo);
    p_EnableVertexAttribArray(aPos);
    p_VertexAttribPointer(aPos, 3, GL_FLOAT, GL_FALSE, 0, 0);

    glEnable(GL_DEPTH_TEST);
    glDepthFunc(GL_LESS);

    // Prior transparent pass left depth writes disabled; the opaque
    // pipeline never restores GL_TRUE before rendering opaque geometry.
    glDepthMask(GL_FALSE);

    for (int frame = 0; frame < 4; frame++) {
        glViewport(0, 0, 400, 300);
        glClearColor(0.f, 0.f, 0.f, 1.f);
        glClearDepth(1.0);
        glClear(GL_COLOR_BUFFER_BIT | GL_DEPTH_BUFFER_BIT);

        // Opaque near quad (should win depth test at every pixel).
        draw_quad(vbo, uColor, -0.5f, 1.f, 0.f, 0.f, 1.f);
        // Opaque far quad (would be rejected if depth had been written).
        draw_quad(vbo, uColor,  0.5f, 0.f, 0.f, 1.f, 1.f);

        glXSwapBuffers(dpy, win);
    }

    unsigned char px[4] = {0};
    glReadPixels(200, 150, 1, 1, GL_RGBA, GL_UNSIGNED_BYTE, px);
    printf("center RGBA = %u %u %u %u\n", px[0], px[1], px[2], px[3]);

    glXMakeCurrent(dpy, None, NULL);
    glXDestroyContext(dpy, ctx);
    XDestroyWindow(dpy, win);
    XCloseDisplay(dpy);
    return 0;
}