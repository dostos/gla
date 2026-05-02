// SOURCE: synthetic (no upstream)
// Stencil test enabled by a prior UI pass leaks into the main 3D pass;
// the 3D geometry fails GL_EQUAL against stencil ref=1 everywhere the
// UI didn't write, so the scene renders as pure clear color.
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

#ifndef GL_ARRAY_BUFFER
#define GL_ARRAY_BUFFER 0x8892
#endif
#ifndef GL_STATIC_DRAW
#define GL_STATIC_DRAW 0x88E4
#endif
#ifndef GL_FRAGMENT_SHADER
#define GL_FRAGMENT_SHADER 0x8B30
#endif
#ifndef GL_VERTEX_SHADER
#define GL_VERTEX_SHADER 0x8B31
#endif
#ifndef GL_COMPILE_STATUS
#define GL_COMPILE_STATUS 0x8B81
#endif
#ifndef GL_LINK_STATUS
#define GL_LINK_STATUS 0x8B82
#endif

typedef char GLchar;
typedef ptrdiff_t GLsizeiptr;
typedef ptrdiff_t GLintptr;

typedef GLuint (*PFNGLCREATESHADERPROC)(GLenum);
typedef void   (*PFNGLSHADERSOURCEPROC)(GLuint, GLsizei, const GLchar* const*, const GLint*);
typedef void   (*PFNGLCOMPILESHADERPROC)(GLuint);
typedef void   (*PFNGLGETSHADERIVPROC)(GLuint, GLenum, GLint*);
typedef void   (*PFNGLGETSHADERINFOLOGPROC)(GLuint, GLsizei, GLsizei*, GLchar*);
typedef GLuint (*PFNGLCREATEPROGRAMPROC)(void);
typedef void   (*PFNGLATTACHSHADERPROC)(GLuint, GLuint);
typedef void   (*PFNGLLINKPROGRAMPROC)(GLuint);
typedef void   (*PFNGLGETPROGRAMIVPROC)(GLuint, GLenum, GLint*);
typedef void   (*PFNGLUSEPROGRAMPROC)(GLuint);
typedef void   (*PFNGLGENBUFFERSPROC)(GLsizei, GLuint*);
typedef void   (*PFNGLBINDBUFFERPROC)(GLenum, GLuint);
typedef void   (*PFNGLBUFFERDATAPROC)(GLenum, GLsizeiptr, const void*, GLenum);
typedef GLint  (*PFNGLGETATTRIBLOCATIONPROC)(GLuint, const GLchar*);
typedef void   (*PFNGLENABLEVERTEXATTRIBARRAYPROC)(GLuint);
typedef void   (*PFNGLVERTEXATTRIBPOINTERPROC)(GLuint, GLint, GLenum, GLboolean, GLsizei, const void*);
typedef GLint  (*PFNGLGETUNIFORMLOCATIONPROC)(GLuint, const GLchar*);
typedef void   (*PFNGLUNIFORM4FPROC)(GLint, GLfloat, GLfloat, GLfloat, GLfloat);

static PFNGLCREATESHADERPROC            glCreateShader_;
static PFNGLSHADERSOURCEPROC            glShaderSource_;
static PFNGLCOMPILESHADERPROC           glCompileShader_;
static PFNGLGETSHADERIVPROC             glGetShaderiv_;
static PFNGLGETSHADERINFOLOGPROC        glGetShaderInfoLog_;
static PFNGLCREATEPROGRAMPROC           glCreateProgram_;
static PFNGLATTACHSHADERPROC            glAttachShader_;
static PFNGLLINKPROGRAMPROC             glLinkProgram_;
static PFNGLGETPROGRAMIVPROC            glGetProgramiv_;
static PFNGLUSEPROGRAMPROC              glUseProgram_;
static PFNGLGENBUFFERSPROC              glGenBuffers_;
static PFNGLBINDBUFFERPROC              glBindBuffer_;
static PFNGLBUFFERDATAPROC              glBufferData_;
static PFNGLGETATTRIBLOCATIONPROC       glGetAttribLocation_;
static PFNGLENABLEVERTEXATTRIBARRAYPROC glEnableVertexAttribArray_;
static PFNGLVERTEXATTRIBPOINTERPROC     glVertexAttribPointer_;
static PFNGLGETUNIFORMLOCATIONPROC      glGetUniformLocation_;
static PFNGLUNIFORM4FPROC               glUniform4f_;

#define LOAD(name) name##_ = (PFN##name##PROC_UPPER)glXGetProcAddress((const GLubyte*)#name)

static void* load(const char* n) { return (void*)glXGetProcAddress((const GLubyte*)n); }

static GLuint make_program(const char* vs, const char* fs) {
    GLuint v = glCreateShader_(GL_VERTEX_SHADER);
    glShaderSource_(v, 1, &vs, NULL);
    glCompileShader_(v);
    GLint ok = 0;
    glGetShaderiv_(v, GL_COMPILE_STATUS, &ok);
    if (!ok) { char log[1024]; glGetShaderInfoLog_(v, 1024, NULL, log); fprintf(stderr, "vs: %s\n", log); exit(1); }
    GLuint f = glCreateShader_(GL_FRAGMENT_SHADER);
    glShaderSource_(f, 1, &fs, NULL);
    glCompileShader_(f);
    glGetShaderiv_(f, GL_COMPILE_STATUS, &ok);
    if (!ok) { char log[1024]; glGetShaderInfoLog_(f, 1024, NULL, log); fprintf(stderr, "fs: %s\n", log); exit(1); }
    GLuint p = glCreateProgram_();
    glAttachShader_(p, v);
    glAttachShader_(p, f);
    glLinkProgram_(p);
    glGetProgramiv_(p, GL_LINK_STATUS, &ok);
    if (!ok) { fprintf(stderr, "link failed\n"); exit(1); }
    return p;
}

static const char* VS =
    "#version 120\n"
    "attribute vec2 a_pos;\n"
    "void main() { gl_Position = vec4(a_pos, 0.0, 1.0); }\n";

static const char* FS =
    "#version 120\n"
    "uniform vec4 u_color;\n"
    "void main() { gl_FragColor = u_color; }\n";

int main(void) {
    Display* dpy = XOpenDisplay(NULL);
    if (!dpy) { fprintf(stderr, "XOpenDisplay failed\n"); return 1; }
    int attrs[] = { GLX_RGBA, GLX_DEPTH_SIZE, 24, GLX_STENCIL_SIZE, 8, GLX_DOUBLEBUFFER, None };
    XVisualInfo* vi = glXChooseVisual(dpy, DefaultScreen(dpy), attrs);
    if (!vi) { fprintf(stderr, "no visual\n"); return 1; }
    Window root = RootWindow(dpy, vi->screen);
    XSetWindowAttributes swa;
    swa.colormap = XCreateColormap(dpy, root, vi->visual, AllocNone);
    swa.event_mask = ExposureMask;
    Window win = XCreateWindow(dpy, root, 0, 0, 400, 300, 0, vi->depth, InputOutput,
                               vi->visual, CWColormap | CWEventMask, &swa);
    XMapWindow(dpy, win);
    GLXContext ctx = glXCreateContext(dpy, vi, NULL, GL_TRUE);
    glXMakeCurrent(dpy, win, ctx);

    glCreateShader_            = load("glCreateShader");
    glShaderSource_            = load("glShaderSource");
    glCompileShader_           = load("glCompileShader");
    glGetShaderiv_             = load("glGetShaderiv");
    glGetShaderInfoLog_        = load("glGetShaderInfoLog");
    glCreateProgram_           = load("glCreateProgram");
    glAttachShader_            = load("glAttachShader");
    glLinkProgram_             = load("glLinkProgram");
    glGetProgramiv_            = load("glGetProgramiv");
    glUseProgram_              = load("glUseProgram");
    glGenBuffers_              = load("glGenBuffers");
    glBindBuffer_              = load("glBindBuffer");
    glBufferData_              = load("glBufferData");
    glGetAttribLocation_       = load("glGetAttribLocation");
    glEnableVertexAttribArray_ = load("glEnableVertexAttribArray");
    glVertexAttribPointer_     = load("glVertexAttribPointer");
    glGetUniformLocation_      = load("glGetUniformLocation");
    glUniform4f_               = load("glUniform4f");

    GLuint prog = make_program(VS, FS);
    glUseProgram_(prog);
    GLint a_pos = glGetAttribLocation_(prog, "a_pos");
    GLint u_color = glGetUniformLocation_(prog, "u_color");

    float ui_quad[] = { -0.9f, 0.8f,  -0.7f, 0.8f,  -0.9f, 0.9f,
                        -0.7f, 0.8f,  -0.7f, 0.9f,  -0.9f, 0.9f };
    float scene_tri[] = { -0.6f, -0.6f,  0.6f, -0.6f,  0.0f, 0.7f };

    GLuint ui_vbo, scene_vbo;
    glGenBuffers_(1, &ui_vbo);
    glBindBuffer_(GL_ARRAY_BUFFER, ui_vbo);
    glBufferData_(GL_ARRAY_BUFFER, sizeof(ui_quad), ui_quad, GL_STATIC_DRAW);
    glGenBuffers_(1, &scene_vbo);
    glBindBuffer_(GL_ARRAY_BUFFER, scene_vbo);
    glBufferData_(GL_ARRAY_BUFFER, sizeof(scene_tri), scene_tri, GL_STATIC_DRAW);

    for (int frame = 0; frame < 3; ++frame) {
        glViewport(0, 0, 400, 300);
        glClearColor(0.10f, 0.12f, 0.18f, 1.0f);
        glClearStencil(0);
        glClear(GL_COLOR_BUFFER_BIT | GL_STENCIL_BUFFER_BIT | GL_DEPTH_BUFFER_BIT);

        // --- UI pass: stencil out a small HUD mask region, write ref=1 there ---
        glEnable(GL_STENCIL_TEST);
        glStencilFunc(GL_ALWAYS, 1, 0xFF);
        glStencilOp(GL_KEEP, GL_KEEP, GL_REPLACE);
        glStencilMask(0xFF);
        glBindBuffer_(GL_ARRAY_BUFFER, ui_vbo);
        glEnableVertexAttribArray_(a_pos);
        glVertexAttribPointer_(a_pos, 2, GL_FLOAT, GL_FALSE, 0, 0);
        glUniform4f_(u_color, 0.9f, 0.9f, 0.2f, 1.0f);
        glDrawArrays(GL_TRIANGLES, 0, 6);

        // UI "inside mask" draw: only where stencil == 1
        glStencilFunc(GL_EQUAL, 1, 0xFF);
        glStencilOp(GL_KEEP, GL_KEEP, GL_KEEP);
        glStencilMask(0x00);
        glUniform4f_(u_color, 0.2f, 0.9f, 0.9f, 1.0f);
        glDrawArrays(GL_TRIANGLES, 0, 6);

        // --- Main 3D pass ---
        glBindBuffer_(GL_ARRAY_BUFFER, scene_vbo);
        glVertexAttribPointer_(a_pos, 2, GL_FLOAT, GL_FALSE, 0, 0);
        glUniform4f_(u_color, 0.95f, 0.25f, 0.15f, 1.0f);
        glDrawArrays(GL_TRIANGLES, 0, 3);

        glXSwapBuffers(dpy, win);
    }

    unsigned char px[4] = {0};
    glReadPixels(200, 150, 1, 1, GL_RGBA, GL_UNSIGNED_BYTE, px);
    printf("center RGBA: %u %u %u %u\n", px[0], px[1], px[2], px[3]);

    glXMakeCurrent(dpy, None, NULL);
    glXDestroyContext(dpy, ctx);
    XDestroyWindow(dpy, win);
    XCloseDisplay(dpy);
    return 0;
}