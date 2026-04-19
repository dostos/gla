// SOURCE: synthetic (no upstream)
// Stencil mask is 0 when the "stencil prepass" attempts to write; later
// stencil test sees all zeros and the masked draw shows through everywhere.
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
typedef GLuint (*PFNGLCREATEPROGRAMPROC)(void);
typedef void   (*PFNGLATTACHSHADERPROC)(GLuint, GLuint);
typedef void   (*PFNGLLINKPROGRAMPROC)(GLuint);
typedef void   (*PFNGLUSEPROGRAMPROC)(GLuint);
typedef GLint  (*PFNGLGETATTRIBLOCATIONPROC)(GLuint, const char*);
typedef GLint  (*PFNGLGETUNIFORMLOCATIONPROC)(GLuint, const char*);
typedef void   (*PFNGLUNIFORM4FPROC)(GLint, GLfloat, GLfloat, GLfloat, GLfloat);
typedef void   (*PFNGLGENBUFFERSPROC)(GLsizei, GLuint*);
typedef void   (*PFNGLBINDBUFFERPROC)(GLenum, GLuint);
typedef void   (*PFNGLBUFFERDATAPROC)(GLenum, ptrdiff_t, const void*, GLenum);
typedef void   (*PFNGLVERTEXATTRIBPOINTERPROC)(GLuint, GLint, GLenum, GLboolean, GLsizei, const void*);
typedef void   (*PFNGLENABLEVERTEXATTRIBARRAYPROC)(GLuint);
typedef void   (*PFNGLGETSHADERIVPROC)(GLuint, GLenum, GLint*);
typedef void   (*PFNGLGETSHADERINFOLOGPROC)(GLuint, GLsizei, GLsizei*, char*);

static PFNGLCREATESHADERPROC            glCreateShader_;
static PFNGLSHADERSOURCEPROC            glShaderSource_;
static PFNGLCOMPILESHADERPROC           glCompileShader_;
static PFNGLCREATEPROGRAMPROC           glCreateProgram_;
static PFNGLATTACHSHADERPROC            glAttachShader_;
static PFNGLLINKPROGRAMPROC             glLinkProgram_;
static PFNGLUSEPROGRAMPROC              glUseProgram_;
static PFNGLGETATTRIBLOCATIONPROC       glGetAttribLocation_;
static PFNGLGETUNIFORMLOCATIONPROC      glGetUniformLocation_;
static PFNGLUNIFORM4FPROC               glUniform4f_;
static PFNGLGENBUFFERSPROC              glGenBuffers_;
static PFNGLBINDBUFFERPROC              glBindBuffer_;
static PFNGLBUFFERDATAPROC              glBufferData_;
static PFNGLVERTEXATTRIBPOINTERPROC     glVertexAttribPointer_;
static PFNGLENABLEVERTEXATTRIBARRAYPROC glEnableVertexAttribArray_;
static PFNGLGETSHADERIVPROC             glGetShaderiv_;
static PFNGLGETSHADERINFOLOGPROC        glGetShaderInfoLog_;

#define LOAD(name) name##_ = (PFN##_TYPE)glXGetProcAddress((const GLubyte*)#name)
#define L(T, n) n##_ = (T)glXGetProcAddress((const GLubyte*)#n)

static void load_gl(void) {
    L(PFNGLCREATESHADERPROC,            glCreateShader);
    L(PFNGLSHADERSOURCEPROC,            glShaderSource);
    L(PFNGLCOMPILESHADERPROC,           glCompileShader);
    L(PFNGLCREATEPROGRAMPROC,           glCreateProgram);
    L(PFNGLATTACHSHADERPROC,            glAttachShader);
    L(PFNGLLINKPROGRAMPROC,             glLinkProgram);
    L(PFNGLUSEPROGRAMPROC,              glUseProgram);
    L(PFNGLGETATTRIBLOCATIONPROC,       glGetAttribLocation);
    L(PFNGLGETUNIFORMLOCATIONPROC,      glGetUniformLocation);
    L(PFNGLUNIFORM4FPROC,               glUniform4f);
    L(PFNGLGENBUFFERSPROC,              glGenBuffers);
    L(PFNGLBINDBUFFERPROC,              glBindBuffer);
    L(PFNGLBUFFERDATAPROC,              glBufferData);
    L(PFNGLVERTEXATTRIBPOINTERPROC,     glVertexAttribPointer);
    L(PFNGLENABLEVERTEXATTRIBARRAYPROC, glEnableVertexAttribArray);
    L(PFNGLGETSHADERIVPROC,             glGetShaderiv);
    L(PFNGLGETSHADERINFOLOGPROC,        glGetShaderInfoLog);
}

static GLuint compile(GLenum type, const char* src) {
    GLuint s = glCreateShader_(type);
    glShaderSource_(s, 1, &src, NULL);
    glCompileShader_(s);
    GLint ok = 0;
    glGetShaderiv_(s, GL_COMPILE_STATUS, &ok);
    if (!ok) { char log[1024]; glGetShaderInfoLog_(s, sizeof log, NULL, log); fprintf(stderr, "shader: %s\n", log); exit(1); }
    return s;
}

static const char* VS =
    "#version 120\n"
    "attribute vec2 aPos;\n"
    "void main(){ gl_Position = vec4(aPos, 0.0, 1.0); }\n";

static const char* FS =
    "#version 120\n"
    "uniform vec4 uColor;\n"
    "void main(){ gl_FragColor = uColor; }\n";

int main(void) {
    Display* dpy = XOpenDisplay(NULL);
    if (!dpy) { fprintf(stderr, "no display\n"); return 1; }
    int attr[] = { GLX_RGBA, GLX_DOUBLEBUFFER, GLX_DEPTH_SIZE, 24, GLX_STENCIL_SIZE, 8, None };
    XVisualInfo* vi = glXChooseVisual(dpy, DefaultScreen(dpy), attr);
    if (!vi) { fprintf(stderr, "no visual\n"); return 1; }
    Window root = RootWindow(dpy, vi->screen);
    XSetWindowAttributes swa = {0};
    swa.colormap = XCreateColormap(dpy, root, vi->visual, AllocNone);
    swa.event_mask = StructureNotifyMask;
    Window w = XCreateWindow(dpy, root, 0, 0, 400, 300, 0, vi->depth, InputOutput, vi->visual,
                             CWColormap | CWEventMask, &swa);
    XMapWindow(dpy, w);
    GLXContext ctx = glXCreateContext(dpy, vi, NULL, True);
    glXMakeCurrent(dpy, w, ctx);

    load_gl();

    GLuint vs = compile(GL_VERTEX_SHADER, VS);
    GLuint fs = compile(GL_FRAGMENT_SHADER, FS);
    GLuint prog = glCreateProgram_();
    glAttachShader_(prog, vs);
    glAttachShader_(prog, fs);
    glLinkProgram_(prog);
    glUseProgram_(prog);

    GLint loc_pos = glGetAttribLocation_(prog, "aPos");
    GLint loc_col = glGetUniformLocation_(prog, "uColor");

    // Fullscreen quad (two triangles).
    float quad[] = { -1,-1,  1,-1,  1,1,   -1,-1,  1,1,  -1,1 };
    // Center quad (covers middle ~half of screen).
    float center[] = { -0.5f,-0.5f,  0.5f,-0.5f,  0.5f,0.5f,
                       -0.5f,-0.5f,  0.5f,0.5f,  -0.5f,0.5f };

    GLuint vbo;
    glGenBuffers_(1, &vbo);

    glEnable(GL_STENCIL_TEST);

    // We want: stencil prepass writes 1 in the center region, then a
    // "masked draw" renders red everywhere but only passes where stencil==1.
    // Expected: red only in the center half. Background clear is blue.
    // BUG: a lingering glStencilMask(0x00) from an earlier setup path (here
    // set right before the prepass, as it would be after some UI/text code
    // disabled writes) causes the prepass to be a silent no-op. Stencil
    // stays all zero; the masked draw therefore fails everywhere and
    // nothing red is shown.

    for (int frame = 0; frame < 3; ++frame) {
        glViewport(0, 0, 400, 300);
        glClearColor(0.05f, 0.10f, 0.45f, 1.0f);
        glClearStencil(0);
        glClear(GL_COLOR_BUFFER_BIT | GL_STENCIL_BUFFER_BIT);

        // "Text/UI subsystem earlier turned writes off and forgot to restore."
        glStencilMask(0x00);

        // --- Stencil prepass: draw center quad, try to write 1 everywhere it covers. ---
        glStencilFunc(GL_ALWAYS, 1, 0xFF);
        glStencilOp(GL_KEEP, GL_KEEP, GL_REPLACE);
        glColorMask(GL_FALSE, GL_FALSE, GL_FALSE, GL_FALSE);

        glBindBuffer_(GL_ARRAY_BUFFER, vbo);
        glBufferData_(GL_ARRAY_BUFFER, sizeof center, center, GL_STREAM_DRAW);
        glEnableVertexAttribArray_(loc_pos);
        glVertexAttribPointer_(loc_pos, 2, GL_FLOAT, GL_FALSE, 0, (void*)0);
        glUniform4f_(loc_col, 0, 0, 0, 0);
        glDrawArrays(GL_TRIANGLES, 0, 6);

        // --- Masked draw: fullscreen red, only where stencil == 1. ---
        glColorMask(GL_TRUE, GL_TRUE, GL_TRUE, GL_TRUE);
        glStencilFunc(GL_EQUAL, 1, 0xFF);
        glStencilOp(GL_KEEP, GL_KEEP, GL_KEEP);

        glBufferData_(GL_ARRAY_BUFFER, sizeof quad, quad, GL_STREAM_DRAW);
        glVertexAttribPointer_(loc_pos, 2, GL_FLOAT, GL_FALSE, 0, (void*)0);
        glUniform4f_(loc_col, 0.95f, 0.10f, 0.10f, 1.0f);
        glDrawArrays(GL_TRIANGLES, 0, 6);

        glXSwapBuffers(dpy, w);
    }

    unsigned char px[4] = {0};
    glReadPixels(200, 150, 1, 1, GL_RGBA, GL_UNSIGNED_BYTE, px);
    printf("center RGBA = %u %u %u %u\n", px[0], px[1], px[2], px[3]);

    glXMakeCurrent(dpy, None, NULL);
    glXDestroyContext(dpy, ctx);
    XDestroyWindow(dpy, w);
    XCloseDisplay(dpy);
    return 0;
}