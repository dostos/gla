// SOURCE: synthetic (no upstream)
// Uniform never uploaded: glUniform called before glUseProgram, so it
// silently targets the previous program (or no program) and the active
// program's uniform keeps its default value of 0.
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
typedef void   (*PFNGLUNIFORM4FPROC)(GLint, GLfloat, GLfloat, GLfloat, GLfloat);
typedef void   (*PFNGLGENBUFFERSPROC)(GLsizei, GLuint*);
typedef void   (*PFNGLBINDBUFFERPROC)(GLenum, GLuint);
typedef void   (*PFNGLBUFFERDATAPROC)(GLenum, GLsizeiptr, const void*, GLenum);
typedef void   (*PFNGLVERTEXATTRIBPOINTERPROC)(GLuint, GLint, GLenum, GLboolean, GLsizei, const void*);
typedef void   (*PFNGLENABLEVERTEXATTRIBARRAYPROC)(GLuint);
typedef GLint  (*PFNGLGETATTRIBLOCATIONPROC)(GLuint, const char*);

static PFNGLCREATESHADERPROC            pglCreateShader;
static PFNGLSHADERSOURCEPROC            pglShaderSource;
static PFNGLCOMPILESHADERPROC           pglCompileShader;
static PFNGLGETSHADERIVPROC             pglGetShaderiv;
static PFNGLGETSHADERINFOLOGPROC        pglGetShaderInfoLog;
static PFNGLCREATEPROGRAMPROC           pglCreateProgram;
static PFNGLATTACHSHADERPROC            pglAttachShader;
static PFNGLLINKPROGRAMPROC             pglLinkProgram;
static PFNGLGETPROGRAMIVPROC            pglGetProgramiv;
static PFNGLUSEPROGRAMPROC              pglUseProgram;
static PFNGLGETUNIFORMLOCATIONPROC      pglGetUniformLocation;
static PFNGLUNIFORM4FPROC               pglUniform4f;
static PFNGLGENBUFFERSPROC              pglGenBuffers;
static PFNGLBINDBUFFERPROC              pglBindBuffer;
static PFNGLBUFFERDATAPROC              pglBufferData;
static PFNGLVERTEXATTRIBPOINTERPROC     pglVertexAttribPointer;
static PFNGLENABLEVERTEXATTRIBARRAYPROC pglEnableVertexAttribArray;
static PFNGLGETATTRIBLOCATIONPROC       pglGetAttribLocation;

#define LOAD(name) p##name = (PFN##name##PROC_UPPER)glXGetProcAddress((const GLubyte*)#name)
static void load_gl(void) {
    pglCreateShader            = (PFNGLCREATESHADERPROC)glXGetProcAddress((const GLubyte*)"glCreateShader");
    pglShaderSource            = (PFNGLSHADERSOURCEPROC)glXGetProcAddress((const GLubyte*)"glShaderSource");
    pglCompileShader           = (PFNGLCOMPILESHADERPROC)glXGetProcAddress((const GLubyte*)"glCompileShader");
    pglGetShaderiv             = (PFNGLGETSHADERIVPROC)glXGetProcAddress((const GLubyte*)"glGetShaderiv");
    pglGetShaderInfoLog        = (PFNGLGETSHADERINFOLOGPROC)glXGetProcAddress((const GLubyte*)"glGetShaderInfoLog");
    pglCreateProgram           = (PFNGLCREATEPROGRAMPROC)glXGetProcAddress((const GLubyte*)"glCreateProgram");
    pglAttachShader            = (PFNGLATTACHSHADERPROC)glXGetProcAddress((const GLubyte*)"glAttachShader");
    pglLinkProgram             = (PFNGLLINKPROGRAMPROC)glXGetProcAddress((const GLubyte*)"glLinkProgram");
    pglGetProgramiv            = (PFNGLGETPROGRAMIVPROC)glXGetProcAddress((const GLubyte*)"glGetProgramiv");
    pglUseProgram              = (PFNGLUSEPROGRAMPROC)glXGetProcAddress((const GLubyte*)"glUseProgram");
    pglGetUniformLocation      = (PFNGLGETUNIFORMLOCATIONPROC)glXGetProcAddress((const GLubyte*)"glGetUniformLocation");
    pglUniform4f               = (PFNGLUNIFORM4FPROC)glXGetProcAddress((const GLubyte*)"glUniform4f");
    pglGenBuffers              = (PFNGLGENBUFFERSPROC)glXGetProcAddress((const GLubyte*)"glGenBuffers");
    pglBindBuffer              = (PFNGLBINDBUFFERPROC)glXGetProcAddress((const GLubyte*)"glBindBuffer");
    pglBufferData              = (PFNGLBUFFERDATAPROC)glXGetProcAddress((const GLubyte*)"glBufferData");
    pglVertexAttribPointer     = (PFNGLVERTEXATTRIBPOINTERPROC)glXGetProcAddress((const GLubyte*)"glVertexAttribPointer");
    pglEnableVertexAttribArray = (PFNGLENABLEVERTEXATTRIBARRAYPROC)glXGetProcAddress((const GLubyte*)"glEnableVertexAttribArray");
    pglGetAttribLocation       = (PFNGLGETATTRIBLOCATIONPROC)glXGetProcAddress((const GLubyte*)"glGetAttribLocation");
}

static const char* VS =
    "#version 120\n"
    "attribute vec2 aPos;\n"
    "void main(){ gl_Position = vec4(aPos, 0.0, 1.0); }\n";

static const char* FS =
    "#version 120\n"
    "uniform vec4 uTint;\n"
    "void main(){ gl_FragColor = uTint; }\n";

static GLuint compile(GLenum kind, const char* src) {
    GLuint s = pglCreateShader(kind);
    pglShaderSource(s, 1, &src, NULL);
    pglCompileShader(s);
    GLint ok = 0; pglGetShaderiv(s, GL_COMPILE_STATUS, &ok);
    if (!ok) { char log[1024]; pglGetShaderInfoLog(s, 1024, NULL, log); fprintf(stderr, "shader: %s\n", log); exit(1); }
    return s;
}

static void setup_tint_and_draw(GLuint prog, GLint locTint) {
    // Configure the draw: we want a bright orange tint.
    // Author intent: (1.0, 0.55, 0.1, 1.0)
    pglUniform4f(locTint, 1.0f, 0.55f, 0.1f, 1.0f);
    pglUseProgram(prog);
    glDrawArrays(GL_TRIANGLES, 0, 3);
}

int main(void) {
    Display* dpy = XOpenDisplay(NULL);
    if (!dpy) { fprintf(stderr, "no display\n"); return 1; }
    int attrs[] = { GLX_RGBA, GLX_DOUBLEBUFFER, GLX_DEPTH_SIZE, 24, None };
    XVisualInfo* vi = glXChooseVisual(dpy, DefaultScreen(dpy), attrs);
    Colormap cmap = XCreateColormap(dpy, RootWindow(dpy, vi->screen), vi->visual, AllocNone);
    XSetWindowAttributes swa; swa.colormap = cmap; swa.event_mask = 0;
    Window win = XCreateWindow(dpy, RootWindow(dpy, vi->screen), 0, 0, 400, 300, 0,
                               vi->depth, InputOutput, vi->visual, CWColormap | CWEventMask, &swa);
    XMapWindow(dpy, win);
    GLXContext ctx = glXCreateContext(dpy, vi, NULL, GL_TRUE);
    glXMakeCurrent(dpy, win, ctx);
    load_gl();

    GLuint vs = compile(GL_VERTEX_SHADER, VS);
    GLuint fs = compile(GL_FRAGMENT_SHADER, FS);
    GLuint prog = pglCreateProgram();
    pglAttachShader(prog, vs);
    pglAttachShader(prog, fs);
    pglLinkProgram(prog);
    GLint linked = 0; pglGetProgramiv(prog, GL_LINK_STATUS, &linked);
    if (!linked) { fprintf(stderr, "link failed\n"); return 1; }

    GLint locPos  = pglGetAttribLocation(prog, "aPos");
    GLint locTint = pglGetUniformLocation(prog, "uTint");

    GLfloat tri[] = { -0.9f,-0.9f,  0.9f,-0.9f,  0.0f, 0.9f };
    GLuint vbo; pglGenBuffers(1, &vbo);
    pglBindBuffer(GL_ARRAY_BUFFER, vbo);
    pglBufferData(GL_ARRAY_BUFFER, sizeof(tri), tri, GL_STATIC_DRAW);
    pglEnableVertexAttribArray(locPos);
    pglVertexAttribPointer(locPos, 2, GL_FLOAT, GL_FALSE, 0, (void*)0);

    for (int f = 0; f < 3; ++f) {
        glViewport(0, 0, 400, 300);
        glClearColor(0.0f, 0.0f, 0.0f, 1.0f);
        glClear(GL_COLOR_BUFFER_BIT);
        setup_tint_and_draw(prog, locTint);
        glXSwapBuffers(dpy, win);
    }

    unsigned char px[4] = {0,0,0,0};
    glReadPixels(200, 150, 1, 1, GL_RGBA, GL_UNSIGNED_BYTE, px);
    printf("center RGBA = %u %u %u %u\n", px[0], px[1], px[2], px[3]);

    glXMakeCurrent(dpy, None, NULL);
    glXDestroyContext(dpy, ctx);
    XDestroyWindow(dpy, win);
    XFreeColormap(dpy, cmap);
    XFree(vi);
    XCloseDisplay(dpy);
    return 0;
}