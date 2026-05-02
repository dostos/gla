// SOURCE: synthetic (no upstream)
// Culling mode set to GL_FRONT_AND_BACK — every triangle is discarded,
// framebuffer keeps clear color only.
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
typedef GLint  (*PFNGLGETATTRIBLOCATIONPROC)(GLuint, const GLchar*);
typedef void   (*PFNGLGENBUFFERSPROC)(GLsizei, GLuint*);
typedef void   (*PFNGLBINDBUFFERPROC)(GLenum, GLuint);
typedef void   (*PFNGLBUFFERDATAPROC)(GLenum, GLsizeiptr, const void*, GLenum);
typedef void   (*PFNGLENABLEVERTEXATTRIBARRAYPROC)(GLuint);
typedef void   (*PFNGLVERTEXATTRIBPOINTERPROC)(GLuint, GLint, GLenum, GLboolean, GLsizei, const void*);
typedef GLXContext (*PFNGLXCREATECONTEXTATTRIBSARBPROC)(Display*, GLXFBConfig, GLXContext, Bool, const int*);

static PFNGLCREATESHADERPROC           glCreateShader_;
static PFNGLSHADERSOURCEPROC           glShaderSource_;
static PFNGLCOMPILESHADERPROC          glCompileShader_;
static PFNGLGETSHADERIVPROC            glGetShaderiv_;
static PFNGLGETSHADERINFOLOGPROC       glGetShaderInfoLog_;
static PFNGLCREATEPROGRAMPROC          glCreateProgram_;
static PFNGLATTACHSHADERPROC           glAttachShader_;
static PFNGLLINKPROGRAMPROC            glLinkProgram_;
static PFNGLGETPROGRAMIVPROC           glGetProgramiv_;
static PFNGLUSEPROGRAMPROC             glUseProgram_;
static PFNGLGETATTRIBLOCATIONPROC      glGetAttribLocation_;
static PFNGLGENBUFFERSPROC             glGenBuffers_;
static PFNGLBINDBUFFERPROC             glBindBuffer_;
static PFNGLBUFFERDATAPROC             glBufferData_;
static PFNGLENABLEVERTEXATTRIBARRAYPROC glEnableVertexAttribArray_;
static PFNGLVERTEXATTRIBPOINTERPROC    glVertexAttribPointer_;

#define LOAD(p, name) p = (void*)glXGetProcAddress((const GLubyte*)name)

static const char* VS =
    "#version 120\n"
    "attribute vec2 aPos;\n"
    "void main() { gl_Position = vec4(aPos, 0.0, 1.0); }\n";

static const char* FS =
    "#version 120\n"
    "void main() { gl_FragColor = vec4(0.9, 0.2, 0.3, 1.0); }\n";

static GLuint compile(GLenum type, const char* src) {
    GLuint s = glCreateShader_(type);
    glShaderSource_(s, 1, &src, NULL);
    glCompileShader_(s);
    GLint ok = 0;
    glGetShaderiv_(s, GL_COMPILE_STATUS, &ok);
    if (!ok) {
        char log[1024]; glGetShaderInfoLog_(s, sizeof log, NULL, log);
        fprintf(stderr, "shader: %s\n", log); exit(1);
    }
    return s;
}

int main(void) {
    Display* dpy = XOpenDisplay(NULL);
    if (!dpy) { fprintf(stderr, "XOpenDisplay failed\n"); return 1; }

    int attribs[] = { GLX_RGBA, GLX_DEPTH_SIZE, 24, GLX_DOUBLEBUFFER, None };
    XVisualInfo* vi = glXChooseVisual(dpy, DefaultScreen(dpy), attribs);
    if (!vi) { fprintf(stderr, "glXChooseVisual failed\n"); return 1; }

    Window root = RootWindow(dpy, vi->screen);
    XSetWindowAttributes swa = {0};
    swa.colormap = XCreateColormap(dpy, root, vi->visual, AllocNone);
    swa.event_mask = StructureNotifyMask;
    Window win = XCreateWindow(dpy, root, 0, 0, 400, 300, 0, vi->depth,
                               InputOutput, vi->visual,
                               CWColormap | CWEventMask, &swa);
    XMapWindow(dpy, win);

    GLXContext ctx = glXCreateContext(dpy, vi, NULL, GL_TRUE);
    glXMakeCurrent(dpy, win, ctx);

    LOAD(glCreateShader_,           "glCreateShader");
    LOAD(glShaderSource_,           "glShaderSource");
    LOAD(glCompileShader_,          "glCompileShader");
    LOAD(glGetShaderiv_,            "glGetShaderiv");
    LOAD(glGetShaderInfoLog_,       "glGetShaderInfoLog");
    LOAD(glCreateProgram_,          "glCreateProgram");
    LOAD(glAttachShader_,           "glAttachShader");
    LOAD(glLinkProgram_,            "glLinkProgram");
    LOAD(glGetProgramiv_,           "glGetProgramiv");
    LOAD(glUseProgram_,             "glUseProgram");
    LOAD(glGetAttribLocation_,      "glGetAttribLocation");
    LOAD(glGenBuffers_,             "glGenBuffers");
    LOAD(glBindBuffer_,             "glBindBuffer");
    LOAD(glBufferData_,             "glBufferData");
    LOAD(glEnableVertexAttribArray_, "glEnableVertexAttribArray");
    LOAD(glVertexAttribPointer_,    "glVertexAttribPointer");

    GLuint vs = compile(GL_VERTEX_SHADER, VS);
    GLuint fs = compile(GL_FRAGMENT_SHADER, FS);
    GLuint prog = glCreateProgram_();
    glAttachShader_(prog, vs);
    glAttachShader_(prog, fs);
    glLinkProgram_(prog);

    /* Full-viewport quad as two CCW triangles. */
    float verts[] = {
        -0.9f, -0.9f,   0.9f, -0.9f,   0.9f,  0.9f,
        -0.9f, -0.9f,   0.9f,  0.9f,  -0.9f,  0.9f,
    };
    GLuint vbo;
    glGenBuffers_(1, &vbo);
    glBindBuffer_(GL_ARRAY_BUFFER, vbo);
    glBufferData_(GL_ARRAY_BUFFER, sizeof verts, verts, GL_STATIC_DRAW);

    glViewport(0, 0, 400, 300);

    /* Engine policy: cull back faces to reduce overdraw.
     * Author fat-fingered GL_FRONT_AND_BACK instead of GL_BACK. */
    glEnable(GL_CULL_FACE);
    glFrontFace(GL_CCW);
    glCullFace(GL_FRONT_AND_BACK);

    for (int frame = 0; frame < 4; ++frame) {
        glClearColor(0.05f, 0.05f, 0.08f, 1.0f);
        glClear(GL_COLOR_BUFFER_BIT);

        glUseProgram_(prog);
        GLint loc = glGetAttribLocation_(prog, "aPos");
        glBindBuffer_(GL_ARRAY_BUFFER, vbo);
        glEnableVertexAttribArray_(loc);
        glVertexAttribPointer_(loc, 2, GL_FLOAT, GL_FALSE, 0, (void*)0);

        glDrawArrays(GL_TRIANGLES, 0, 6);

        glXSwapBuffers(dpy, win);
    }

    unsigned char px[4] = {0};
    glReadPixels(200, 150, 1, 1, GL_RGBA, GL_UNSIGNED_BYTE, px);
    printf("center pixel RGBA = %u %u %u %u\n", px[0], px[1], px[2], px[3]);

    glXMakeCurrent(dpy, None, NULL);
    glXDestroyContext(dpy, ctx);
    XDestroyWindow(dpy, win);
    XFreeColormap(dpy, swa.colormap);
    XFree(vi);
    XCloseDisplay(dpy);
    return 0;
}